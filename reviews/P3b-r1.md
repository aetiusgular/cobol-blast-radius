# Review: P3b round 1 (PR #7)

- Head reviewed: `954c55b68884dbbd06d249d9544838e1a0cdbfef` (one commit on `5bfb5fe`)
- Reviewer: a fresh forge-review session. It did not write this code.
- Date: 2026-11-25
- Verdict: **FIX**. One C finding is above minor (C1). S1 and D1 are minor, and D1 is about a number, so it must be fixed anyway. All three are fixed in round 2.

## What was checked

| Item | Result |
|---|---|
| Scope | `git diff --stat origin/main...HEAD` touches 13 files. All are under `radius/` or are every-lane files: `.forge/state.json`, `DECISIONS.md`, `SECURITY.md`, `README.md`. `git diff --stat origin/main...HEAD -- tests contracts fixtures scripts .github` is empty, so there are no contract edits and no red-test edits. |
| Tests not weakened | No file under `tests/` changed. The 19 new lane tests in `radius/tests/` assert behaviour. CI fetched CardDemo, so the CardDemo tests ran: the log shows `Ran 19 tests ... OK` with no skips. |
| CI on the head | Run 45518122756: `ci`, `report` and `guard` pass. The log shows `test.sh: ok`. All 10 P3b red tests and all 8 P3a red tests are green, and all 12 P3c red tests fail for their stated reason. It also shows `lane-scope: lane P3b clean since 5bfb5fe16e20 (13 path(s))`, `forge-gate: P3b passed` and `attribution scan: clean`. `forge/eval` (not an eval phase) and `forge/guard` are success. |
| Local re-run | Fetched CardDemo at `59cc6c2` with `scripts/fetch-carddemo.sh`. `python3 -m unittest discover -s radius/tests -t .` gave `Ran 19 tests ... OK`, and `scripts/check-isolation.py` gave `check-isolation: ok`. `grep -rni heldout radius/` finds nothing. |
| Contracts honoured | Both predictors return every field of `radius.md`, with sorted lists. The 4 dev noops give empty `programs`, `jobs`, `steps` and `datasets`. Neither predictor reads `summary`. E0 follows SPEC.md: every output of every run-set job that runs a program which COPYs the member (nested COPYs included) or runs the changed program. It also counts a job whose own JCL is edited, which SPEC does not name. The PR logs that as an agent's call, and it is the only reading under which E0 is defined for the `jcl_step` class. |
| Dev rows | Both predictors ran on the 20 dev rows (no heldout), at 0.6 to 0.7 s each. I read the outputs for plausibility only. **No ground truth was compared:** eval rule 3 records E0 before any tuning, and a reviewer comparing dev ground truth here would make round 2 a tuning round. The findings below come from COBOL semantics and hand-written probes, not from harness output. |
| Hand-written probes | `CBTRN02C.cbl:407` and `:548` (`>=` to `>`) reach POSTTRAN's outputs and every downstream job. `CBTRN03C.cbl:223` (`WHEN '00'` to `'01'`) reaches TRANREPT and its SYSOUT. An inserted `DISPLAY` in CBACT01C reaches only `SYSOUT:READACCT.STEP05.SYSOUT`. An edit to `app/ctl/REPROCT.ctl` reaches TRANBKP's and TRANREPT's outputs. The 88-level `APPL-AOK VALUE 0` to `VALUE 1` in CBTRN02C reaches everything POSTTRAN feeds. All of these behave as the code's stated rules say. The one exception is C1. |
| Security items | R-1 is in `SECURITY.md` with owner P4. The predictor writes no file and starts no process: `grep -n "subprocess\|open(.*w\|write_text\|socket" radius/*.py` finds nothing. |
| Requests for integration | RFI-P3b-1 (member DSN names) and RFI-P3b-2 (`unverifiable` wording) are contract changes, so rule 3 routes them to P4. Both are logged in DECISIONS.md. |
| Decisions logged | `DECISIONS.md` has 9 P3b rows. Each is marked as the agent's call and has a reason. |

## Findings

### CB-P3b-r1-C1: a changed condition around `NEXT SENTENCE` reaches nothing (C, above minor)

- **Evidence.** `radius/cobol.py:1153` treats `NEXT` as a no-op (`elif v in ("CONTINUE", "EXIT", "NEXT"): pass`). `NEXT SENTENCE` jumps past the next period. In `CBTRN03C.cbl:170-205`, the run-set report program's main loop, that period comes after `END-PERFORM.`, so line 177 leaves the read loop. Whether the loop body after the `IF` runs depends on the date-window condition at lines 173-174. The analysis does not see this. A probe change at line 173, `>=` to `>`, gives:
  ```
  X1 app/cbl/CBTRN03C.cbl 173 'IF TRAN-PROC-TS (1:10) >= WS-START-DATE' -> '> '
    full: []
    e0  : ['AWS.M2.CARDDEMO.TRANREPT', 'AWS.M2.CARDDEMO.TRANSACT.BKUP', 'AWS.M2.CARDDEMO.TRANSACT.DALY', 'SYSOUT:TRANREPT.STEP10R.SYSOUT']
  ```
  The full predictor returns an empty radius for a change to live code that, by the language rules, decides which transactions CBTRN03C displays and reports. `radius.md` allows an empty radius only for a noop or for code that cannot run. The `program_logic` generator mutates comparison operators (dev S-028 is one), so this kind of edit is in scope for the scored set.
- **Why above minor.** Recall is the headline. The miss is silent (an empty radius, not an error), it sits in the main loop of a run-set program, and E0 catches it while the full predictor does not.
- **Fix (applied in round 2).** `Stmt` gains `sentence` (its sentence index in the paragraph) and `next_sentence`. In `analyse`, a `NEXT SENTENCE` that is controlled by a hot condition makes every statement of its sentence controlled, the enclosing inline `PERFORM` included. This follows the PR's own rule for GO TO: it gives up precision, never recall. After the fix, X1 gives `['AWS.M2.CARDDEMO.TRANREPT', 'SYSOUT:TRANREPT.STEP10R.SYSOUT']`, and all 20 dev predictions are the same as before, byte for byte. New lane test: `test_hot_next_sentence_controls_its_whole_sentence`. It fails on `954c55b` and passes on the fix.

### CB-P3b-r1-S1: the predictor reads any path a change names (S, minor)

- **Evidence.** `radius/source.py:109-110` reads `self.root / rel` with no check, and `Sides` reads each edit's `file` (`radius/predict.py:35`). A change with `"file": "../../x"` or an absolute path makes the predictor read that file into memory. The content does not reach the radius (only `member_of(rel)` does), so nothing is disclosed. But P3a's `groundtruth/changes.py` refuses such paths, and `change.md` says `file` is relative to the CardDemo root.
- **Fix (applied in round 2).** `Tree.read` returns `None` for a path that resolves outside the root. New lane test: `test_tree_reads_nothing_outside_its_root`. The R-1 row in `SECURITY.md` now says so.

### CB-P3b-r1-D1: a crash-sweep count with nothing behind it (D, minor, about a number)

- **Evidence.** `radius/README.md` ("What ran") and the PR body say "186 synthetic one-line edits". The sweep ran in the session scratchpad. It has no results row and no committed script, so a reader cannot check the number (BUILD_OUTLINE.md section 9: no number in a README without a results row behind it).
- **Fix (applied in round 2).** The README now describes the sweep without a count and says it has no results row. The test count in the same section is updated from 19 to 21, which matches `Ran 21 tests` from `scripts/test.sh`.

## Not findings (noted for P4 and P5)

- The analysis is flow-insensitive and keeps a dataset changed for the rest of the run. The PR states both limits, and both cost precision, not recall.
- RETURN-CODE is not modelled. In the run set, only `TRANBKP.jcl:51` (`COND=(4,LT)`, after an IDCAMS step) tests a return code, and `CBTRN02C.cbl:230` (`MOVE 4 TO RETURN-CODE`) is in a job with no COND. It is not reachable today. P4 should revisit it if the run set grows.
