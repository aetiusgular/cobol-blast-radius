#!/usr/bin/env bash
# ci runs this before scripts/test.sh and the phase gate. Written in P2;
# lanes do not edit it (Requests for integration instead).
#
#   - GnuCOBOL 3.2 (SPEC.md). ubuntu-latest (24.04) packages 3.1.2, so when
#     `cobc` is missing or is not 3.2, this builds the GNU release tarball,
#     pinned by sha256 (the same bytes as Debian's gnucobol3_3.2.orig.tar.xz),
#     into vendor/gnucobol, and on GitHub Actions adds it to GITHUB_PATH and
#     LD_LIBRARY_PATH to GITHUB_ENV for the later steps. Indexed files (the
#     VSAM stand-in) use Berkeley DB, as Debian's package does. XML support
#     is off (--without-xml2): nothing in the run set or fixtures uses XML
#     GENERATE/PARSE, and 3.2's common.c does not build against the libxml2
#     headers on ubuntu-latest (implicit xmlCleanupParser).
#   - CardDemo at the pinned commit, in vendor/carddemo.
# Python is stdlib only (unittest); nothing to pip install.
#
# FORGE_SKIP_COBOL=1 skips the compiler (the red tests in P2 never reach it).
set -euo pipefail
cd "$(dirname "$0")/.."

GC_VERSION=3.2
GC_URL=https://ftp.gnu.org/gnu/gnucobol/gnucobol-3.2.tar.xz
GC_SHA256=3bb48af46ced4779facf41fdc2ee60e4ccb86eaa99d010b36685315df39c2ee2
prefix="$PWD/vendor/gnucobol"

have_32() { command -v cobc >/dev/null && cobc --version | head -n1 | grep -q "GnuCOBOL) ${GC_VERSION}"; }

export_env() {
  export PATH="$prefix/bin:$PATH" LD_LIBRARY_PATH="$prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  if [[ -n "${GITHUB_PATH:-}" ]]; then
    echo "$prefix/bin" >> "$GITHUB_PATH"
    echo "LD_LIBRARY_PATH=$prefix/lib" >> "$GITHUB_ENV"
  fi
}

if [[ "${FORGE_SKIP_COBOL:-0}" != 1 ]]; then
  [[ -x "$prefix/bin/cobc" ]] && export_env
  if ! have_32; then
    if command -v apt-get >/dev/null && sudo -n true 2>/dev/null; then
      sudo apt-get update -qq
      sudo apt-get install -y -qq build-essential libgmp-dev libdb-dev libncurses-dev libjson-c-dev >/dev/null
    fi
    src=$(mktemp -d)
    curl -sSfL -o "$src/gc.tar.xz" "$GC_URL"
    echo "$GC_SHA256  $src/gc.tar.xz" | sha256sum -c -
    tar -xJf "$src/gc.tar.xz" -C "$src"
    (cd "$src/gnucobol-$GC_VERSION" && ./configure -q --prefix="$prefix" --with-db --without-xml2 CFLAGS="-O2 -std=gnu17" >/dev/null \
      && make -s -j"$(nproc)" >/dev/null && make -s install >/dev/null)
    rm -rf "$src"
    export_env
  fi
  have_32 || { echo "setup: cobc ${GC_VERSION} not available" >&2; exit 1; }
  cobc --version | head -n1
fi
python3 --version
bash scripts/fetch-carddemo.sh
