# P4 security pass (builder)

Written by the P4 build session, which is not the reviewer: BUILD_OUTLINE section 3 makes a security review part of P4's work. The P4 review round (`P4-r1.md`, a fresh session) checks this pass. Date 2026-11-25, base `9a7eb9b`.

Scope, per section 5: inputs, file writes, subprocess calls, network calls, and anything that runs another tool. Found with `grep -rn "subprocess\.|socket|urllib|http|os.system|eval(|exec(|pickle|shell=True"` over `groundtruth/ radius/ approval/ scripts/` and a read of each hit.

| Surface | Where | Finding | Result |
|---|---|---|---|
| Change input (edit paths) | `groundtruth/changes.py` `plan` | Each edit's path is resolved, symlinks included, and refused when it falls outside the root. `apply` writes all or nothing. | ok |
| Ledger writes and revert | `approval/ledger.py` `_inside`, `_write_restoring` | Revert paths come from the ledger's own entries and are resolved inside `--root`. Every file must still hash to `after_sha256` before anything is written. Appends hold an `flock` and verify the chain first. | ok |
| Allowlist input | `approval/allowlist.py` `check_rules` | Strict: an unknown key, action or kind raises. Patterns compile to escaped regexes, with no user regex. | ok |
| Supplied radius | `approval/cli.py` `_record` | Refused unless it covers the edited members and every predicted item (CB-P3c-r1-S1, CB-P3c-r2-S1). | ok |
| Run set for another tree | `approval/cli.py` `_record`, `allowlist.check_runset_fits` | CB-P3c-r3-S1: CardDemo's run set on the mini tree predicted an empty radius, and a deny rule went unchecked. **Fixed in P4**: the run set must describe the tree, and the record carries `runset_sha256`. What is left is SECURITY.md A-3. | fixed |
| Running compiled programs | `groundtruth/harness.py` `run_program` | Runs the tree's programs as the caller, unsandboxed (G-1). P4 decided `approve` and `deny` never reach it. | open, G-1 |
| Output size | `groundtruth/harness.py` `run_program` | There was no size cap, only a time cap (G-2). **Fixed in P4**: `RLIMIT_FSIZE` caps every file at 256 MiB; stdout and stderr now go to files, so the cap covers them. | mitigated, G-2 |
| `cobc` calls | `groundtruth/cobol.py` | Argument lists, never a shell. The flags come from the run set only, and `check-contracts.py` now limits them to one `-std=` plus `DIALECT_OPTIONS`. | ok |
| `git` calls | `approval/evalrun.py` (the repo only), `approval/allowlist.py` `_git_head` (the caller's `--root`) | `_git_head` runs `git rev-parse` on a tree the caller names. rev-parse runs no hooks; P4 also passes `-c core.fsmonitor=false` so a crafted `.git/config` cannot start a monitor command. | ok |
| `nvidia-smi` | `approval/evalrun.py` `_gpu` | Fixed arguments, a 30-second timeout, output used as a string. | ok |
| Network | everywhere | No socket, HTTP or URL use in the packages. `scripts/setup.sh` and `scripts/fetch-carddemo.sh` download GnuCOBOL (sha256-pinned) and CardDemo (commit-pinned) at setup only. | ok |
| Predictor cost | `radius/` | A crafted source can be slow or large (R-1). It runs only as the caller's own CLI. | open, R-1 |
| Identity | `--by` | Not authenticated (A-2). **P4** adds `applied_as` to the record, the OS account from the effective uid (`pwd.getpwuid(os.geteuid())`, never `$USER`). Signing needs a key, so it is Tony's call. | low, A-2 |
| Ledger tail | `verify` | A deleted last entry needs `--expect-head` (A-1); documented in `contracts/ledger.md`. | open, A-1 |

No high item. One medium stays open: G-1. A harness that decides ground truth by execution has to run the tree's COBOL, so the fix is a sandbox, not code: the P5 box runs evals inside srt with no network. Until then, no approval path reaches the harness. A-2 drops to low with `applied_as`. The P4 exit gate reads "no open S finding above low". G-1 is a SECURITY.md item carried from P3a, not a review finding, and the PR lists it for Tony.
