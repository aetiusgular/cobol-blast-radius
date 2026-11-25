#!/usr/bin/env bash
# ci's "tests and lint" step. Runs in every phase. The red tests are not run
# here: scripts/forge-gate.sh runs them against their expectations.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== contracts parse and the split matches its contract"
python3 -I scripts/check-contracts.py
echo "== lane isolation (radius and groundtruth never import each other)"
python3 -I scripts/check-isolation.py
echo "== python compiles"
python3 -m compileall -q groundtruth radius approval tests scripts >/dev/null
echo "== lane unit tests"
for pkg in groundtruth radius approval; do
  if [[ -d "$pkg/tests" ]]; then
    python3 -m unittest discover -s "$pkg/tests" -t . -p 'test_*.py'
  fi
done
echo "== cross-lane tests (P4)"
if [[ -d tests/integration ]]; then
  python3 -m unittest discover -s tests/integration -t . -p 'test_*.py'
fi
echo "test.sh: ok"
