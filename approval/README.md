# approval/: allowlist, approval record, hash-chained ledger, eval runner, CLI (lane P3c)

Standard library only. `approval` may import `radius` and `groundtruth` through the names in `contracts/seams.md`; neither imports it.

## Allowlist (`allowlist.py`, `contracts/allowlist.md`)

`decide(radius, rules)` turns every member, program, job and dataset in a radius into an item and gives each the strictest action among the rules that match it (`deny` > `ask` > `allow`). An item no rule matches asks. The change takes the strictest item, so reordering a rule file never changes a decision. `*` and `?` stop at a dot and `**` does not. Everything else in a pattern is literal, and patterns match the whole name, case-sensitively. A malformed rule (unknown action or kind, empty pattern, extra key) raises `RuleError` rather than being skipped.

## Ledger (`ledger.py`, `contracts/ledger.md`)

A folder with `ledger.jsonl` (one canonical-JSON entry per line) and `objects/<sha256>` (every file's content before and after). Each entry carries the SHA-256 of the entry before it.

- `approve` refuses a `deny` decision. It stores the before contents first, applies the change all or nothing (through `groundtruth.changes.apply`), then appends. If anything fails after the files are written, it writes the old bytes back.
- `deny` appends and touches no file.
- `revert(seq)` works only on an `approve` that has not been reverted. Every file must still hash to that entry's `after_sha256`, so a later edit to the same file has to be reverted first. Otherwise nothing is written. The revert entry lists each file with its before and after swapped.
- `verify` recomputes every entry hash, checks every `prev_sha256` link, `seq` running 1, 2, 3, canonical form, the field set, that each object exists and hashes to its name, and that each revert names an earlier approve that has not been reverted yet. It returns `ok`, `problems`, plus `entries` and `head_sha256`.
- Every write takes an exclusive `flock` and first runs `verify`. A ledger that does not verify is never added to, so tampering stays visible.

**What the chain cannot catch on its own.** A deleted *last* entry, or a whole chain rewritten consistently by someone with write access, still verifies. `head_sha256` exists for that case: keep it somewhere else (a commit, the PR) and pass it back with `verify --expect-head`. `decided_by` is whatever the caller types, not an authenticated identity (SECURITY.md A-1, A-2).

## Eval runner (`evalrun.py`, `contracts/eval.md`)

`run(split, split_path, eval_doc, root, runset, out_path, predict, ground_truth)`:

- For `heldout`, refuses before any work (`SplitHashMismatch`) unless `split_path` hashes to `eval.md`'s `split-sha256`. A `dev` run may use another file. Its rows record the file's real hash and `split_matches_contract`.
- One `change` row per change in the split: `changed`, `predicted` (cut to the output universe `changed` ∪ `unchanged`), `predicted_outside_universe`, `true_positive` / `false_positive` / `false_negative`, `unverifiable`, `status_changes`, exclusion, and per-change recall and precision.
- A predictor that raises gives an empty prediction, which counts as misses, and the row keeps `predict_error`. A ground-truth error stops the run, because the grader's result is never guessed.
- One `summary` row: micro recall and precision over the changes that are not excluded, `per_class` (one table per class), the `noop` table (correct when both lists are empty), `excluded_by_reason`, `predict_errors` and the outside-universe count. In this row the counts are `changed_count` and `predicted_count`, because `changed` and `predicted` are lists in the schema.
- Every row has the section 6 fields: `machine` is read at run time (`$FORGE_MACHINE_FILE`, else `/proc/cpuinfo`, `/proc/meminfo` and `nvidia-smi`), `git_sha` comes with `git_dirty`, and `model_revision`, `quant` and `runtime` are `null` because no model runs. `cobc_version` is the harness's own reading.
- Rows are **appended** to `out_path`, so a repeat run and its predecessor both stay (negative results ship).

## CLI (`python3 -m approval.cli`)

```
predict  --change C [--root R] [--runset S] [--e0]
decide   (--change C | --radius X) --allowlist A [--root R] [--runset S]
approve  --change C --allowlist A --root R --ledger L --by WHO [--confirm] [--note N] [--radius X]
deny     --change C --root R --ledger L --by WHO [--allowlist A] [--note N]
verify   --ledger L [--expect-head SHA]
revert   --ledger L --seq N --root R
eval     --split dev|heldout --out results/E<k>-<split>.jsonl [--predictor full|e0] [--split-path P] [--root R] [--runset S] [--workdir W]
```

`--root` defaults to `vendor/carddemo` and `--runset` to `contracts/runset.json`. Output is JSON on stdout. `approve` exits 0 when the change is applied. On `ask` without `--confirm` it exits 3 and writes nothing. On `deny` it exits 4 and records a deny entry without applying the change. `verify` exits 1 when the ledger is not ok. Errors print `{"error": ...}` on stderr and exit 2. `approve` and `deny` run only the predictor and never the harness (SECURITY.md G-1). `eval` runs the harness once for the baseline and once per change, and stops if a run-set program does not compile in the baseline, because every diff after that would be empty.

## What ran (P3c, 2026-11-25, on the session's Linux workstation)

- `bash scripts/test.sh`: contracts, isolation and all lane unit tests pass, including the 32 in `approval/tests/`.
- `bash scripts/forge-gate.sh P3c`: the red tests of P3a, P3b and P3c are green, lane-scope is clean, and the split hash matches.
- A CLI smoke run in the session scratchpad on a copy of `fixtures/mini`: approve (allow, ask without and with `--confirm`, deny), verify, revert twice (the tree came back byte for byte), a second revert of the same entry refused, a truncated tail caught only by `--expect-head`, and `eval --split dev` over the six fixture changes, with the real harness (GnuCOBOL 3.2.0) and the real predictor. A heldout run on a file that is not the frozen split was refused, and no output file was written. Those numbers are fixture plumbing checks, so no results row was written.
- No eval ran on CardDemo's split. E0 and E1 run in P5 (eval.md rule 3).
