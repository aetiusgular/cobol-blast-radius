# Review: P3b round 2 (PR #8)

- Head reviewed: `f98a0a9c715091e098ae4731f3219252745837fa` (one commit on round 1's head `954c55b`)
- Reviewer: a fresh forge-review session. It did not write this code.
- Date: 2026-11-25
- Verdict: **FIX**. One C finding is above minor (C1). It is fixed in round 3.

## What was checked

| Item | Result |
|---|---|
| Scope | `git diff --stat main...f98a0a9` touches 14 files, all under `radius/` or every-lane files (`.forge/state.json`, `DECISIONS.md`, `SECURITY.md`, `README.md`, `reviews/`). `git diff --stat main...f98a0a9 -- tests contracts fixtures scripts .github` is empty: no contract, red-test or grader edits. |
| Tests not weakened | `git diff 954c55b f98a0a9 -- radius/tests` only adds two tests. Nothing under `tests/` changed. |
| CI on the head | Run 45523541148: `ci`, `report`, `guard` pass. The log shows `Ran 21 tests` for `radius/tests`, all 10 P3b red tests green, `lane-scope: lane P3b clean since 5bfb5fe16e20 (14 path(s))`, `forge-gate: P3b passed` and `attribution scan: clean`. `forge/eval` (not an eval phase) and `forge/guard` are success. |
| Local re-run | CardDemo fetched at `59cc6c2` with `scripts/fetch-carddemo.sh`. `python3 -m unittest discover -s radius/tests -t .` gave `Ran 21 tests ... OK`. `forge-gate.sh P3b` locally: P3b and P3c red tests as expected, lane-scope clean; the 6 failures are P3a red tests that stop with `cobc not found` (no `cobc` on this host; remote ci builds it, and no P3a file changed). |
| Round 1 fixes | **r1-C1:** the probe `CBTRN03C.cbl:173` `>=` to `>` now gives `['AWS.M2.CARDDEMO.TRANREPT', 'SYSOUT:TRANREPT.STEP10R.SYSOUT']`, and so do `:174` `<=` to `<` and `:171` `'N'` to `'X'`. **r1-S1:** `radius/source.py:110` checks `p.resolve().is_relative_to(self.root.resolve())`, and `test_tree_reads_nothing_outside_its_root` covers `../` and absolute paths. **r1-D1:** the count is gone from `radius/README.md`; 21 matches the test run. |
| Round 1 closed | #7 is closed with a comment that links #8. |
| Decisions logged | Two new P3b rows in `DECISIONS.md`, each an agent's call with a reason. |
| No ground truth | The round-3 fix, like round 2's, follows from COBOL semantics. No harness output was compared (eval rule 3). |

## Findings

### CB-P3b-r2-C1: a change that removes the `NEXT SENTENCE` gives an empty radius (C, above minor)

- **Evidence.** Round 2 made a hot `NEXT SENTENCE` control its sentence, but only on the after side (`radius/cobol.py` `analyse`). A change that replaces or deletes the jump itself leaves no `NEXT SENTENCE` on the after side. The before-side loop in `radius/predict.py` (`ProgramSeed.__init__`, the `for p in B.paras` block) models a removed statement's assigns, moves, sinks, PERFORMs, STOP and abend, but not `next_sentence` or `goto`. Probes on CBTRN03C at `f98a0a9`:
  ```
  X3 app/cbl/CBTRN03C.cbl 177 'NEXT SENTENCE' -> 'CONTINUE'
    full: []
    e0  : ['AWS.M2.CARDDEMO.TRANREPT', 'AWS.M2.CARDDEMO.TRANSACT.BKUP', 'AWS.M2.CARDDEMO.TRANSACT.DALY', 'SYSOUT:TRANREPT.STEP10R.SYSOUT']
  X6 app/cbl/CBTRN03C.cbl 175 'CONTINUE' -> 'NEXT SENTENCE'
    full: ['AWS.M2.CARDDEMO.TRANREPT', 'SYSOUT:TRANREPT.STEP10R.SYSOUT']
  ```
  With `CONTINUE` at line 177, a record outside the date window no longer leaves the read loop; it falls through to `DISPLAY TRAN-RECORD` and `1100-WRITE-TRANSACTION-REPORT`. That is live code in a run-set program's main loop, and `radius.md` allows an empty radius only for a noop or code that cannot run. X6, the mirror edit, is handled, so the round-2 rule holds for one side only.
- **Why above minor.** It is the same silent miss as r1-C1, on the line round 2 fixed, and E0 catches it while the full predictor does not. The frozen split's `program_logic` generator mutates literals, not statements, so the scored set is unlikely to contain it. But the approval step (P3c, P4) predicts on proposed changes, and deleting or replacing a jump is an ordinary edit.
- **Fix (applied in round 3).** In the before-side loop, a removed `NEXT SENTENCE` seeds every after-side statement of the same sentence in the same-named paragraph, which matches the after-side rule. A removed `GO TO` puts its paragraph and its target paragraphs in the change's context and sets `terminates`, which mirrors a hot `GO TO` in `analyse`. After the fix, X3 gives `['AWS.M2.CARDDEMO.TRANREPT', 'SYSOUT:TRANREPT.STEP10R.SYSOUT']`. All 20 dev predictions (full and E0) are byte-identical to `f98a0a9`. New lane tests: `test_removed_jump_controls_what_it_skipped` (NEXT SENTENCE and GO TO subtests) and `test_removed_next_sentence_reaches_the_report`. All three fail on `f98a0a9` and pass on the fix. `Ran 23 tests ... OK`.

## Not findings (noted for P4)

- The statement splitter (`radius/cobol.py:855` and `:877`) reads any word that starts with `END-` as a scope terminator, so `GO TO END-PARA` resolves no target. `END-PARA` is a legal user-defined name. No CardDemo paragraph starts with `END-`, so it is not reachable today. Found while writing the GO TO test, which uses `DONE-PARA`.
- The run-set programs have no `GO TO` (only `GOBACK`, already modelled as `terminates`). The GO TO half of the fix has a unit test but no CardDemo probe.
