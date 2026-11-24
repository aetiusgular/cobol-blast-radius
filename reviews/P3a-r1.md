# Review: P3a round 1 (PR #6)

- Head reviewed: `ca2218715c789b0e821502bf0b9b5565c2396a9c` (one commit on `eddf7f6`)
- Reviewer: a fresh forge-review session. It did not write this code.
- Date: 2026-11-24
- Verdict: **PASS**. There are no S findings. One C finding and two E findings are all minor, and the one D finding is minor and not about a number.

## What was checked

| Item | Result |
|---|---|
| Scope | `git diff --stat origin/main...HEAD` touches 19 files. All are under `groundtruth/` or are every-lane files: `.forge/state.json`, `DECISIONS.md`, `SECURITY.md`, `README.md`. `git diff --stat origin/main...HEAD -- tests contracts fixtures scripts .github` is empty, so no contract edits and no red-test edits. |
| Tests not weakened | No file under `tests/` changed. The 31 new lane tests in `groundtruth/tests/` assert behaviour. The CardDemo class is `skipUnless(vendor/carddemo)`, and CI fetches CardDemo, so it ran: the CI log shows `Ran 31 tests ... OK`, with no skips. |
| CI on the head | Run 45500346880: `ci`, `report` and `guard` pass. The log shows `cobc (GnuCOBOL) 3.2.0` and `test.sh: ok`. All 8 P3a red tests are green, and every P3b and P3c red test fails for its stated reason. It also shows `lane-scope: lane P3a clean ... (19 path(s))`, `forge-gate: P3a passed` and `attribution scan: clean`. `forge/eval` (not an eval phase) and `forge/guard` are success. |
| Local re-run | Local cobc needs GMP headers and there is no sudo, so I ran `scripts/setup.sh` in an `ubuntu:24.04` container on this host: AMD Ryzen 5 9600X (`/proc/cpuinfo`), MemTotal 127044444 kB, Python 3.12.3, `cobc (GnuCOBOL) 3.2.0`. In a clone at the head, `bash scripts/test.sh` printed `Ran 31 tests ... OK` and `test.sh: ok`, and `bash scripts/forge-gate.sh P3a` printed `forge-gate: P3a passed`. |
| Baseline | Ran `harness.run` on `vendor/carddemo` with `contracts/runset.json`. All 7 run-set programs compile with no diagnostics. All 59 steps are `ok` or `skipped`: the skips are SDSF steps, and POSTTRAN rc is 4. The run reports 28 outputs, including 7 `SYSOUT:` names for COBOL steps and no utility SYSOUT. `root` is unchanged: a tree hash before and after is equal. |
| Dev changes | Ran the 20 dev changes (no heldout) against that baseline. All 4 noops give an empty `changed` and no status changes. Error-path edits behave as the code says. S-022 (`MOVE 16`→`17 TO APPL-RESULT` on EOF) abends READXREF through CEE3ABD. S-029 abends INTCALC, so SYSTRAN(+1) is deleted by its abnormal DISP, and COMBTRAN then ends on the JCL error `SYSTRAN(0) not found`. Edits inside error paths only give no change: S-024, S-030, S-034. A second run of a changed case (S-022) gave identical `compile`, `steps` and `outputs`. |
| Generator | `generate(cls, seed)` called twice gives identical JSON for seeds 1 to 12 in each class. Each class has candidates: copybook_field 118, program_logic 399, jcl_step 30, noop 1583. `compile_break` is always a bool. The generator reproduces 9 of the 20 dev rows exactly. This is expected: `make-split.py` skips candidates it already used. The PR claims only shared operators and the same draw order, not reproduction. |
| Contracts honoured | `cobol.compile_program` and `syntax_ok` pass `runset["cobc_flags"]` plus `-I` and output flags only (`groundtruth/cobol.py:78`, `:93`). `changes.plan` refuses paths outside the tree (`changes.py:34`) and checks every edit before writing. `diff` is pure over its two arguments. |
| Isolation | `scripts/check-isolation.py` passes in CI. `grep -rni heldout groundtruth/` finds only the README line saying heldout was not run. |
| Security items | G-1 (no sandbox) and G-2 (no output-size cap) are in `SECURITY.md` with owner P4. `git diff origin/main...HEAD \| grep gitleaks:allow` matches only a context line of the existing T-2 row. |
| Requests for integration | RFI-P3a-1 reproduced (see E2 below). For RFI-P3a-2, the baseline has `AWS.M2.CARDDEMO.TRANSACT.DALY` and `AWS.M2.CARDDEMO.TRANREPT` at 0 bytes, and `TRANREPT.jcl:43-44` bounds the INCLUDE at 2022-01-01 to 2022-07-06 while the clock is 2022/07/18. RFI-P3a-3 changes only the schema text. |
| Decisions logged | `DECISIONS.md` has 12 P3a rows. Each is marked as the agent's call and has a reason. |

## Findings

### CB-P3a-r1-E1: KEYS and LRECL edits run where z/OS would fail OPEN (E, minor)

- **Evidence.** Dev S-040 (`READACCT.jcl:43`, `LRECL=110`→`111`) and S-043 (`TRANCATG.jcl:40`, `KEYS(6 0)`→`KEYS(7 0)`) both give 0 changed outputs and no status changes. On z/OS, a program whose FD record length or key does not match the dataset fails OPEN with status 39. Three of the 4 dev `jcl_step` changes are KEYS or LRECL edits (S-037, S-040, S-043). `groundtruth/README.md` ("Known limits") states this limit.
- **Why minor.** SPEC defines ground truth as GnuCOBOL execution, and the limit is disclosed. It does not change the headline formula. It does bias the per-class `jcl_step` table toward "unchanged".
- **Fix.** Not needed for P3a. P4 decides between emulating status 39 in the harness (it knows each cluster's key and record size from DEFINE) and reporting the `jcl_step` rows of these edit types with this caveat in P5.

### CB-P3a-r1-E2: under the current dialect, POSTTRAN rejects almost every transaction (E, minor here, routed to P4)

- **Evidence.** In the baseline, `AWS.M2.CARDDEMO.DALYREJS` has 299 records of 430 bytes, all with reason `0102` at offset 350, out of 300 daily transactions. With `cobc_flags` set to `["-std=ibm","-fsign=EBCDIC"]` it has 38, all `0102`, and `TRANSACT.VSAM.KSDS` grows from 17850 to 109200 bytes.
- **Why minor here.** `contracts/runset.md` forbids the harness to change the dialect. The lane raised RFI-P3a-1 under rule 3, which is the correct route.
- **Fix.** P4 should decide RFI-P3a-1 and RFI-P3a-2 before any heldout ground truth runs. Otherwise the POSTTRAN and TRANREPT outputs mostly reflect the reject path and an empty report.

### CB-P3a-r1-C1: PARM and COND on an EXEC PROC are applied differently from z/OS (C, minor, latent)

- **Evidence.** `groundtruth/jcl.py:366-368` copies an unqualified `PARM` or `COND` from the EXEC PROC statement to every proc step that lacks its own. On z/OS, an unqualified PARM goes to the first proc step and nullifies PARM on the later steps. An unqualified COND overrides COND on every step. No run-set job has PARM or COND on an EXEC PROC: grepping the 20 job files finds `PARM=` only on `INTCALC.jcl:22`, an EXEC PGM. The generator only edits existing values, so no generated or split change reaches this code.
- **Fix.** Optional. Match z/OS, or report `unsupported` when an EXEC PROC carries an unqualified PARM or COND.

### CB-P3a-r1-D1: dangling DECISIONS.md reference (D, minor, not about a number)

- **Evidence.** `groundtruth/utilities.py:8` says ASCII collation in SORT is a call that "DECISIONS.md records". No DECISIONS.md row mentions sort collation (`grep -in collat DECISIONS.md` finds nothing). The limit is stated in `groundtruth/README.md` ("Known limits").
- **Fix.** Point the docstring at `groundtruth/README.md`, or add the row, in the next change to the lane.
