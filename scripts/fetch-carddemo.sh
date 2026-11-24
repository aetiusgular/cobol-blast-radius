#!/usr/bin/env bash
# Fetch CardDemo at the pinned commit into vendor/carddemo (gitignored).
# CardDemo is Apache-2.0 (LICENSE and NOTICE kept in the checkout); nothing
# of it is committed here (DECISIONS.md, P1). Idempotent.
set -euo pipefail
cd "$(dirname "$0")/.."
url=https://github.com/aws-samples/aws-mainframe-modernization-carddemo.git
sha=$(jq -r .carddemo_commit contracts/runset.json)
dst=vendor/carddemo
if [[ -d "$dst/.git" ]] && [[ "$(git -C "$dst" rev-parse HEAD 2>/dev/null)" == "$sha" ]]; then
  echo "carddemo: $dst already at $sha"; exit 0
fi
rm -rf "$dst"; mkdir -p "$dst"
git -C "$dst" init -q
git -C "$dst" remote add origin "$url"
git -C "$dst" fetch -q --depth 1 origin "$sha"
git -C "$dst" -c advice.detachedHead=false checkout -q FETCH_HEAD
got=$(git -C "$dst" rev-parse HEAD)
[[ "$got" == "$sha" ]] || { echo "carddemo: got $got, wanted $sha" >&2; exit 1; }
echo "carddemo: $dst at $sha"
