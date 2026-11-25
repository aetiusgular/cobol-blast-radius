# Review: P3c round 2 (PR #11)

- Head reviewed: `c54c6d439816c3e98f9baba47577be8859327fd8` (two commits on `main` at `9e27735`)
- Reviewer: a fresh forge-review session. It did not write this code.
- Date: 2026-11-25
- Verdict: **FIX**. One S finding is above minor (S1, a remainder of CB-P3c-r1-S1). It is fixed in round 3.

## What was checked

| Item | Result |
|---|---|
| Scope | `git diff --stat 9e27735 c54c6d4` touches 14 files, all under `approval/` or every-lane files (`.forge/state.json`, `DECISIONS.md`, `SECURITY.md`, `README.md`, `reviews/`). `git diff 9e27735 --stat -- tests contracts fixtures scripts .github` is empty: no contract, red-test, fixture or grader edits. |
| Tests not weakened | No file under `tests/` changed. The round 2 diff to `approval/tests/` (`git diff 2baa069 c54c6d4 -- approval/tests`) only adds tests. |
| CI on the head | Run 45551349446: `ci`, `report` and `guard` pass. The log shows `cobc (GnuCOBOL) 3.2.0`, `Ran 31`, `Ran 23` and `Ran 37 tests ... OK`, all 30 red tests of P3a, P3b and P3c green, `lane-scope: lane P3c clean since 9e27735cc7ff (14 path(s))` and `forge-gate: P3c passed`. `forge/eval` (not an eval phase) and `forge/guard` are success. |
| Local re-run | GnuCOBOL could not be built on the review machine (`configure: error: neither GMP nor MPIR library are found`), so the cobc-dependent suites were not re-run locally and the CI log above is the evidence for them. `python3 -m unittest discover -s approval/tests -t .` gives `Ran 37 tests ... OK` locally. |
| CB-P3c-r1-S1 fix | `approval/allowlist.py` `check_radius_covers` refuses a radius for another change or one missing an edited member. The r1 probe (members emptied) now exits 2 and writes nothing. On CardDemo at `59cc6c2`, the full and E0 radii of all 20 dev changes pass the check (40 checked, 0 refused), so it does not refuse real radii. Heldout was not read. |
| CB-P3c-r1-E1 fix | `evalrun.run` reads the split once, hashes those bytes and passes them to `load_split`. |
| Decisions logged | Two new P3c rows in `DECISIONS.md`, each an agent's call with a reason. |
| Lane README | `approval/README.md` says what ran in round 2 and documents the refusal. |

## Findings

### CB-P3c-r2-S1: a supplied radius that keeps the edited member but drops a downstream item still bypasses a deny rule (S, medium)

- **Evidence.** Round 2 checks only `members` (`approval/allowlist.py:79` `check_radius_covers`). The programs, jobs and datasets that `decide` turns into items still come from the `--radius` file as given (`approval/cli.py:47` `_radius`). Probe on a scratch copy of `fixtures/mini` with `fixtures/mini/changes/field-label.json`, `--runset fixtures/mini/runset.json` and the rules `[{"pattern":"MINI.SUMFILE","kind":"dataset","action":"deny"},{"pattern":"**","action":"allow"}]`:
  ```
  predict: members ['MINICNST'] programs ['MINISUM'] jobs ['MINIJOB2'] datasets ['MINI.SUMFILE', 'SYSOUT:MINIJOB2.STEP2.SYSOUT']
  approve (predicted radius)                                     rc=4   seq 1 deny, file untouched
  approve --radius <same radius, programs/jobs/datasets []>      rc=0   seq 2 approve, decision allow
  grep TOTAX app/cpy/MINICNST.cpy -> 05  MC-LABEL  PIC X(8)  VALUE 'TOTAX'.
  ```
  The ledger now holds a deny for the change followed by an allow for the same change, and the change to a file whose output the rules deny was applied. A stale radius file (predicted before the tree gained a new reader of the dataset) gets the same result without anyone intending it.
- **Why above minor.** It is the same failure as CB-P3c-r1-S1, which round 1 rated medium: a CLI flag turns a deny into an allow and the ledger records the allow. Round 2 closed the members case only.
- **Fix (applied in round 3).** `approve` and `deny` given `--radius` also predict the radius (the full predictor, which is what they use without `--radius`) and refuse, exit 2 with nothing written, a supplied radius that leaves out any member, program, job or dataset of the predicted one (`approval.allowlist.check_radius_includes`). A supplied radius may still add items, which can only make the decision stricter. New tests: `RadiusIncludes` (two tests) and `test_a_supplied_radius_must_include_the_predicted_items` (the probe above; it fails on round 2's `cli.py`).

## Not findings (noted)

- `approve` and `deny` default `--runset` to `contracts/runset.json`. On a tree that is not CardDemo (for example `fixtures/mini` without `--runset`), the predicted radius is members only, so a dataset rule never fires. That is a usage error the README's defaults line covers; P4 may want `--runset` to be required whenever `--root` is not the default.
- `evalrun.score` leaves predicted datasets outside the diff's universe out of precision and reports them in `predicted_outside_universe` and the summary count. That is shown, not hidden; P5 should report it beside precision.
