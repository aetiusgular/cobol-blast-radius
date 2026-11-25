# P5 failure case: a change that makes a loop never end

Rows: `results/E1-heldout.jsonl`, run `2026-11-25-27739e5f37d7`, changes `S-020` and `S-025`. These are the only two missed (change, output) pairs in E1 on heldout: 73 of 75 changed pairs were predicted (recall 0.973). Both misses are this one case. The same pattern does not occur in dev, where E1 missed nothing (`results/E1-dev.jsonl`, run `2026-11-25-feb2bc8ff724`).

## The change

`S-020` edits `app/cbl/CBCUS01C.cbl` line 108. `S-025` makes the same edit at line 108 of `app/cbl/CBACT03C.cbl`:

```
-                   MOVE 'Y' TO END-OF-FILE
+                   MOVE 'Z' TO END-OF-FILE
```

The main loop is `PERFORM UNTIL END-OF-FILE = 'Y'` (CBCUS01C line 74). Inside it, every statement is guarded by `IF END-OF-FILE = 'N'`. At end of file the program now sets `'Z'`. The loop condition never becomes true, and the guarded body never runs again, so the program spins without reading, writing or displaying anything.

## What ground truth saw

The harness ran the step until its 300-second step timeout (`groundtruth/harness.py`, `STEP_TIMEOUT`) and recorded `READCUST.STEP05: abend (timeout)` (`READXREF.STEP05` for S-025). `status_changes` on the row shows the step going from `ok`, rc 0, to `abend`. The step's SYSOUT lacks the closing `END OF EXECUTION OF PROGRAM CBCUS01C` line that the baseline ends with, so `SYSOUT:READCUST.STEP05.SYSOUT` (`SYSOUT:READXREF.STEP05.SYSOUT` for S-025) differs from the baseline. It is the only output of the run set that differs.

## What the predictor did

E1 predicted an empty radius for both. The literal `'Z'` reaches `END-OF-FILE`. That field reaches no record or display sink. It feeds only the loop's exit condition and the `IF` guards, and the guards now skip work instead of doing different work. The graph models a changed condition around `STOP RUN`, `GOBACK`, `GO TO`, `NEXT SENTENCE` and `CALL 'CEE3ABD'` as reaching the program's outputs (DECISIONS.md, P3b). It does not model a changed loop exit, so non-termination is not a data flow it follows.

E0, the one-hop baseline, gets both pairs right because it flags every output of a job that runs the changed program (`results/E0-heldout.jsonl`, run `2026-11-25-6575fbf03a54`, program_logic recall 1.000 against E1's 0.714). E0 pays for that with precision: 0.383 overall on heldout, against E1's 0.608.

## What a fix would be, and why P5 did not make it

The recall-safe rule: a changed value that reaches the condition of a `PERFORM UNTIL` (or `VARYING`) makes the program's SYSOUT and every dataset it has open at that point changed. A program that may not terminate changes how its step ends. That rule would also flag the dev false alarms of the same shape, which costs precision only.

P5 did not make the fix, for three reasons. `radius/` is P3b's folder (BUILD_OUTLINE.md section 2, rule 3). The heldout set has now been scored, so a fix shaped by these two rows would be tuning on heldout (contracts/eval.md, rule 1). And the next heldout run is the next release. The fix is listed in the PR as a Request for integration for a later release, to be tuned and checked on dev only.

## Note on the oracle

"Changed" here rests on the harness's timeout. A mainframe job would also abend, on its CPU time limit, but the SYSOUT bytes at that point depend on where the loop was when it was killed. The program displays nothing inside the loop, so the diff is the missing closing display, and it repeats: the E0 and E1 heldout runs agree on both rows.
