# Review: P3b round 3 (PR #9)

- Head reviewed: `2e4f325051ac0610ab7f9f3bba2251afb2a0682a` (one commit on round 2's head `f98a0a9`)
- Reviewer: a fresh forge-review session. It did not write this code.
- Date: 2026-11-25
- Verdict: **PASS**. No S, C, E or D findings. The round-2 finding CB-P3b-r2-C1 is fixed, and the probes below found no new miss.

## What was checked

| Item | Result |
|---|---|
| Scope | `git diff --stat main...HEAD -- tests contracts fixtures scripts .github` is empty. Outside `radius/`, the only files touched are every-lane files: `.forge/state.json`, `DECISIONS.md`, `README.md`, `SECURITY.md` and `reviews/`. Round 3 itself (`git diff --stat f98a0a9 2e4f325`) touches 7 files: 15 added lines in `radius/predict.py`, two new tests, README and DECISIONS lines, state, and `reviews/P3b-r2.md`. |
| Tests not weakened | `git diff f98a0a9 2e4f325 -- radius/tests` only adds `test_removed_jump_controls_what_it_skipped` (two subtests) and `test_removed_next_sentence_reaches_the_report`. Nothing under `tests/` changed. |
| New tests fail before the fix | I copied the round-3 test files onto a worktree at `f98a0a9` and ran the two tests: `FAILED (failures=3)`, with both subtests (NEXT SENTENCE and GO TO) and the CardDemo test failing. On `2e4f325`, `python3 -m unittest discover -s radius/tests -t .` gives `Ran 23 tests ... OK`. |
| CI on the head | Run 45530613767: `ci`, `report` and `guard` pass. The log shows `Ran 23 tests`, `test.sh: ok`, `lane-scope: lane P3b clean since 5bfb5fe16e20 (15 path(s))`, `forge-gate: P3b passed` and `attribution scan: clean`. `forge/eval` (not an eval phase) and `forge/guard` are success. |
| Dev predictions unchanged | I ran `predict` and `predict_e0` on the 20 dev rows at `f98a0a9` and at `2e4f325`. The JSON output is byte-identical (`cmp` is silent). I compared no ground truth (eval rule 3). |
| r2-C1 fix | `radius/predict.py:176-190`: in the before-side loop, a removed `NEXT SENTENCE` seeds every after-side statement of the same sentence in the same-named paragraph, which matches the after-side rule in `cobol.analyse` (`radius/cobol.py:1330-1336`). A removed `GO TO` puts its paragraph and its targets in `ctx` and sets `terminates`, which mirrors a hot `GO TO` (`radius/cobol.py:1358-1364`). The fall-through rule at `radius/cobol.py:1373-1376` then reaches the paragraph after a removed `GO TO`. |
| Round 2 closed | #8 is closed with a comment that links #9. |
| Decisions logged | One new P3b row in `DECISIONS.md`, marked as the agent's call, with a reason. |
| Docs | `radius/README.md` gives 23 tests, which matches CI. The new limits bullet describes the removed-jump rule, and it matches the code. |

## Hand-written probes (radius on `2e4f325`)

```
CBTRN03C.cbl:177 NEXT SENTENCE -> CONTINUE          ['AWS.M2.CARDDEMO.TRANREPT', 'SYSOUT:TRANREPT.STEP10R.SYSOUT']
CBTRN03C.cbl:177 NEXT SENTENCE -> comment line      ['AWS.M2.CARDDEMO.TRANREPT', 'SYSOUT:TRANREPT.STEP10R.SYSOUT']
synthetic: A. GO TO C. B. DISPLAY G1. C. STOP RUN.
  GO TO C -> CONTINUE (B now falls through)         {'SYSOUT': 'shape'}, terminates
  GO TO C -> GO TO B                                {'SYSOUT': 'shape'}, terminates
synthetic: NEXT SENTENCE removed in sentence 2      {'SYSOUT': 'shape'}
  same, plus an earlier period removed (the
  sentence index shifts by one)                     {'SYSOUT': 'shape'}, terminates
```

Every probe that changes which statements run gets a non-empty radius. One variant, replacing `NEXT SENTENCE` with `CONTINUE.`, gives an empty radius. That edit leaves a stray `END-IF` after a period, so the program does not compile, and the predictor's empty radius for it is not a recall miss.

## Not findings (noted for P4 and P5)

- A removed `GO TO` sets `terminates`, so every output file and SYSOUT of the program becomes `shape`. This costs precision, not recall. The run-set programs have no `GO TO`, so it does not show up on dev.
- The r2 note still stands: the statement splitter reads any word that starts with `END-` as a scope terminator, so `GO TO END-PARA` resolves no target. CardDemo has no such paragraph.
- RFI-P3b-1 and RFI-P3b-2 still wait for P4.
