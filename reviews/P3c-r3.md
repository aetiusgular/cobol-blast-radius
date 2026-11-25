# Review: P3c round 3 (PR #12)

- Head reviewed: `e69f3a0f63c01e2053a662981e4910dd6cd6be40` (three commits on `main` at `9e27735`)
- Reviewer: a fresh forge-review session. It did not write this code.
- Date: 2026-11-25
- Verdict: **PASS**. The only finding is a minor S (S1), carried to P4. It does not block.

## What was checked

| Item | Result |
|---|---|
| Scope | `git diff --stat 9e27735 e69f3a0 -- tests contracts fixtures scripts .github` is empty: no contract, red-test, fixture or grader edits. Locally, `node scripts/lane-scope.mjs P3c` gives `lane-scope: lane P3c clean since 9e27735cc7ff (15 path(s))`, and `scripts/check-isolation.py` gives `check-isolation: ok`. |
| Tests not weakened | No file under `tests/` changed. `git diff c54c6d4 e69f3a0 -- approval/tests` removes no line; it only adds `RadiusIncludes` (2 tests) and `test_a_supplied_radius_must_include_the_predicted_items`. |
| CI on the head | Run 45558047905: `ci`, `report` and `guard` pass. The log shows `cobc (GnuCOBOL) 3.2.0`, `Ran 31`, `Ran 23` and `Ran 40 tests`, `lane-scope: lane P3c clean since 9e27735cc7ff (15 path(s))` and `forge-gate: P3c passed`. `forge/eval` (not an eval phase) and `forge/guard` are success. |
| Local re-run | `python3 -m unittest discover -s approval/tests -t .` gives `Ran 40 tests ... OK`. The cobc-dependent suites were not re-run locally; the CI log above is the evidence for them. |
| CB-P3c-r2-S1 fix | `approval/allowlist.py:93` `check_radius_includes` refuses a supplied radius missing any predicted member, program, job or dataset. `approval/cli.py:57` calls it with the full predictor whenever `--radius` is given, for both `approve` and `deny`. With round 2's `cli.py` swapped in, the new CLI test fails (`FAILED (failures=1)`); with round 3's it passes. A wider radius is still decided, and the test shows it reaching `deny` (exit 4). |
| Attribution | `git log --format=%B 9e27735..e69f3a0` has no `Co-Authored-By`, `anthropic`, `claude` or "Generated with" line. The CI attribution scan passed on the PR body. |
| Decisions logged | One new P3c row in `DECISIONS.md` (agent's call, with reason and what reverses it). |
| Lane README | `approval/README.md` documents the new refusal and says what ran in round 3, including that GnuCOBOL was not built locally. |

## Findings

### CB-P3c-r3-S1: a runset that does not describe the tree narrows the predicted radius, and the record does not show which runset was used (S, minor, P4)

- **Evidence.** The round 3 check compares a supplied radius with one predicted from the caller's own `--root` and `--runset` (`approval/cli.py:57`), so it is only as wide as that runset. On a scratch copy of `fixtures/mini` with `fixtures/mini/changes/field-label.json` and the rules `[{"pattern":"MINI.SUMFILE","kind":"dataset","action":"deny"},{"pattern":"**","action":"allow"}]`:
  ```
  approve --runset fixtures/mini/runset.json          rc=4  deny
  predict (default runset, contracts/runset.json)     members ['MINICNST'] programs [] jobs [] datasets []
  approve (default runset)                            rc=0  approve, decision allow
  grep TOTAX app/cpy/MINICNST.cpy  ->  05  MC-LABEL  PIC X(8)  VALUE 'TOTAX'.
  ```
  The approval record (`contracts/allowlist.md`, "Approval record") holds the radius but not the runset or its hash, so the ledger cannot show that the decision was made against a runset for another tree.
- **Why minor.** This is not a hole the round 3 fix opened. `approve` without `--radius` behaves the same, and round 2's review listed it under "Not findings" as a usage error. The default `--runset` is right for the default `--root`. The caller already runs as a user who can write `--root` (SECURITY.md A-2), so the allowlist guards against mistakes, not against the operator. Neither a stale file nor an edited file causes it: the caller has to pass a mismatched tree and runset.
- **Fix (for P4, not applied here).** Either require `--runset` whenever `--root` is not the default, or check the runset against the tree (for example `carddemo_commit` against the tree, or each runset program present under `program_dirs`). Also put the runset's sha256 in the approval record. Both change `contracts/allowlist.md`, so they go through P4 (BUILD_OUTLINE section 2, rule 3).

## Not findings (noted)

- `decide --radius X` still decides a supplied radius without the new check. It writes nothing and applies nothing, so it is a query, not a gate.
- `check_radius_includes` does not type-check the radius lists. A string in place of a list gets refused (its characters do not contain the predicted names), and an unhashable entry raises and exits 2. Both fail closed.
