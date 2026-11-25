# Cross-lane tests (P4)

These tests run the three lanes together, through the seams in `contracts/seams.md` only. `scripts/test.sh` runs them in every phase from P4 on.

| File | What it joins |
|---|---|
| `test_mini.py` | The predictor (P3b), the harness and diff (P3a) and the approval CLI, ledger and eval runner (P3c) on `fixtures/mini`: shared dataset names, schemas of every document that crosses a lane, the approve, verify and revert loop, the run-set check (CB-P3c-r3-S1), and the harness's output cap (SECURITY.md G-2). |
| `test_carddemo.py` | The run set as P4 changed it (RFI-P3a-1, RFI-P3a-2) on CardDemo at the pinned commit: every program builds, every step ends `ok` or `skipped`, the baseline repeats, TRANREPT has records, the graph names every output the harness scores, and the graph has the `LIB(MEMBER)` node (RFI-P3b-1). |

They need `cobc` 3.2 and `vendor/carddemo` (`scripts/setup.sh`). Nothing here runs the frozen split: E0 comes first, in P5 (`contracts/eval.md` rule 3).
