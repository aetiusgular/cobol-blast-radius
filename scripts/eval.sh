#!/usr/bin/env bash
# The single entry point the box runs (BUILD_OUTLINE.md sections 6 and 8).
# forge's eval workflow runs it inside srt with the network limited to
# 127.0.0.1, from the repo root, with FORGE_REPO, FORGE_PR, FORGE_SHA,
# FORGE_PHASE and FORGE_MACHINE_FILE (machine labels read on the host at run
# time) in the environment. It writes results/*.jsonl rows (results/README.md)
# and results/summary.md, which becomes the PR comment.
#
#   bash scripts/eval.sh            the box: E0 and E1 on dev again, compared
#                                   with the committed release rows (exit 1 on
#                                   any difference); rows in results/P5-box-*.jsonl
#   bash scripts/eval.sh repeat     the same, rows in results/P5-repeat-*.jsonl
#   bash scripts/eval.sh release    once per release: E0 and E1 on dev and heldout
#
# No model runs, so there are no five-run bands: a repeat must be identical
# (contracts/eval.md rule 4). The box repeats dev only; heldout ran once, in
# the release run (rule 2).
#
# Needs, with no network (srt allows 127.0.0.1 only):
#   - GnuCOBOL 3.2: `cobc` on PATH, or under vendor/gnucobol or
#     /opt/forge-tools/gnucobol. LD_LIBRARY_PATH is set from its prefix here,
#     because the sandbox passes only PATH, HOME, LANG and FORGE_* through.
#   - CardDemo at the run set's commit in vendor/carddemo, or a checkout at
#     /opt/forge-tools/share/carddemo that is copied there.
# Exit 0 pass, 1 repeat differs, 2 usage or release refused, 3 toolchain or
# CardDemo missing.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
mode="${1:-box}"
case "$mode" in box|repeat|release) ;; *) echo "usage: scripts/eval.sh [box|repeat|release]" >&2; exit 2 ;; esac

missing() {
  echo "eval.sh: $1" >&2
  mkdir -p results
  { echo "## cobol-blast-radius eval: not run"; echo; echo "$1"; echo
    echo "The box needs GnuCOBOL 3.2 and a CardDemo checkout at \`$want_sha\` readable without network (see scripts/eval.sh)."
  } > results/summary.md
  exit 3
}

want_sha=$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["carddemo_commit"])' contracts/runset.json) || exit 2

is_32() { "$1" --version 2>/dev/null | head -n1 | grep -q 'GnuCOBOL) 3\.2'; }
cobc_bin=""
for c in "$(command -v cobc || true)" "$PWD/vendor/gnucobol/bin/cobc" /opt/forge-tools/gnucobol/bin/cobc; do
  [[ -n "$c" && -x "$c" ]] || continue
  prefix="$(cd "$(dirname "$c")/.." && pwd)"
  if LD_LIBRARY_PATH="$prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" is_32 "$c"; then cobc_bin="$c"; break; fi
done
[[ -n "$cobc_bin" ]] || missing "GnuCOBOL 3.2 not found (PATH, vendor/gnucobol, /opt/forge-tools/gnucobol)."
prefix="$(cd "$(dirname "$cobc_bin")/.." && pwd)"
export PATH="$prefix/bin:$PATH" LD_LIBRARY_PATH="$prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
echo "eval.sh: $(cobc --version | head -n1) at $cobc_bin"

head_of() { git -c core.fsmonitor=false -C "$1" rev-parse HEAD 2>/dev/null; }
if [[ "$(head_of vendor/carddemo)" != "$want_sha" ]]; then
  src=/opt/forge-tools/share/carddemo
  [[ "$(head_of "$src")" == "$want_sha" ]] || missing "CardDemo at $want_sha not found (vendor/carddemo, $src)."
  rm -rf vendor/carddemo && mkdir -p vendor && cp -a "$src" vendor/carddemo || missing "could not copy $src"
fi
echo "eval.sh: CardDemo at $want_sha"

case "$mode" in
  release) exec python3 -I scripts/p5-eval.py release ;;
  *)       exec python3 -I scripts/p5-eval.py repeat --tag "$mode" ;;
esac
