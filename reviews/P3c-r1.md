# Review: P3c round 1 (PR #10)

- Head reviewed: `2baa069fa877c3f6c2d9449246442b9eb78470e4` (one commit on `main` at `9e27735`)
- Reviewer: a fresh forge-review session. It did not write this code.
- Date: 2026-11-25
- Verdict: **FIX**. One S finding is above minor (S1). It is fixed in round 2, along with the minor E1.

## What was checked

| Item | Result |
|---|---|
| Scope | `git diff --stat 9e27735 2baa069` touches 13 files, all under `approval/` or every-lane files (`.forge/state.json`, `DECISIONS.md`, `SECURITY.md`, `README.md`). `git diff 9e27735 --stat -- tests contracts fixtures scripts .github` is empty: no contract, red-test, fixture or grader edits. |
| Tests not weakened | No file under `tests/` changed. `approval/tests/` is new. |
| CI on the head | Run 45544825053: `ci`, `report`, `guard` pass. The log shows `Ran 31`, `Ran 23` and `Ran 32 tests ... OK` for the three lanes. `forge/eval` (not an eval phase) and `forge/guard` are success. |
| Local re-run | GnuCOBOL 3.2.0 and CardDemo at `59cc6c2`. `bash scripts/test.sh` passes and `bash scripts/forge-gate.sh P3c` gives `forge-gate: P3c passed`: 8 P3a, 10 P3b and 12 P3c red tests green, `lane-scope: lane P3c clean since 9e27735cc7ff (13 path(s))`, split hash matches. The PR body's counts (8, 10, 12, 13 paths, 32 tests) match. |
| F5 allowlist | `approval/allowlist.py` follows `allowlist.md`: strictest wins, `*`/`?` stop at a dot, `**` does not, everything else is literal, an unmatched item asks, and an empty rule list makes every item ask. |
| F6 ledger | `approval/ledger.py` matches `ledger.md`: canonical JSON, `prev_sha256` links, seq, objects checked, deny writes no file, revert needs every file at its `after_sha256` and appends without rewriting a line. Paths are resolved and refused outside the tree (`_inside`). A deleted last entry is not caught by the chain alone, which SECURITY.md A-1 and `verify --expect-head` cover. |
| F7 eval runner | Heldout is refused on a hash mismatch before any work. Rows carry the section 6 fields; `machine` is read at run time. No results row was written and no eval ran, as eval rule 3 requires. |
| Decisions logged | Twelve P3c rows in `DECISIONS.md`, each an agent's call with a reason. |
| Lane README | `approval/README.md` says what ran, where, and that the fixture runs were plumbing checks. |

## Findings

### CB-P3c-r1-S1: a supplied radius that leaves out the edited member bypasses a deny rule (S, medium)

- **Evidence.** `allowlist.md` says "The edited members are always items, so a change with an empty predicted radius still gets a decision", but `decide(radius, rules)` takes the members from the radius alone, and `approval/cli.py` `_record` (line 53 at `2baa069`) only checks that `radius.change_id` equals `change.id`. `approve --radius X` takes the radius from a file. Probe on a scratch copy of `fixtures/mini`, with the rules `[{"pattern":"MINICNST","kind":"member","action":"deny"},{"pattern":"**","action":"allow"}]` and `fixtures/mini/changes/field-label.json` (an edit to `app/cpy/MINICNST.cpy`):
  ```
  predict: members ['MINICNST'] programs ['MINISUM'] jobs ['MINIJOB2'] datasets ['MINI.SUMFILE', 'SYSOUT:MINIJOB2.STEP2.SYSOUT']
  approve (predicted radius)                 rc=4   deny entry, file untouched
  approve --radius <same radius, members []> rc=0   kind approve, decision allow
  grep TOTAX app/cpy/MINICNST.cpy  ->  05  MC-LABEL  PIC X(8)  VALUE 'TOTAX'.
  ```
  The change to a denied member was applied, and the ledger records it as an `allow` approval, so the audit trail shows a decision the rules never gave. A stale radius file (same change id, older edit list) gets the same result without anyone intending it. DECISIONS.md's own row says "A radius without them is malformed", but only the zero-item case was handled.
- **Why above minor.** The allowlist is the gate this lane exists to add (SPEC F5, the brief's "allowlist" for the approval step). A deny that a CLI flag silently turns into an allow, recorded as such, undermines both the gate and the ledger.
- **Fix (applied in round 2).** `approval.allowlist.check_radius_covers(change, radius)` raises `RuleError` unless the radius is for the change and names every member its edits touch (`edited_members`, the `radius.md` rule: `app/cpy/CVACT01Y.cpy` gives `CVACT01Y`). `cli._record`, used by `approve` and `deny`, calls it in place of the bare id check, so the probe above now exits 2 and writes nothing. It stays in the CLI because `decide(radius, rules)` is a contract seam and the red ledger tests pass records with empty members to `Ledger.approve`. New tests: `RadiusCovers` (two tests), `test_a_supplied_radius_must_name_the_edited_members` (fails on `2baa069`'s `cli.py`, passes on round 2) and `test_predicted_radii_name_their_edited_members` (full and E0 radii for all six fixture changes pass the check).

### CB-P3c-r1-E1: the heldout hash and the scored rows come from two reads of the split file (E, minor)

- **Evidence.** `approval/evalrun.py` `run` at `2baa069` hashes `split_path` with `file_hash(split_path)` and then reads it again in `load_split(split_path, split)`. A file replaced between the two reads would be scored while the rows carry the frozen hash. That needs a write to the split during a run, so it is minor.
- **Fix (applied in round 2).** `run` reads the bytes once, hashes them, and `load_split(split_path, split, data)` parses those bytes. New test: `test_rows_come_from_the_bytes_that_were_hashed`.

## Not findings (noted for P4)

- `verify` checks that a revert names an earlier, unreverted approve, but not that its `files` are the target's with before and after swapped. Forging that needs a consistent chain rewrite, which A-1 already lists.
- `Ledger.approve` trusts `record.decision`; only the CLI computes it from the rules. A-2 already says the ledger is an audit trail, not an authority.
- `evalrun.run` takes `root` (seams.md) and does not use it; the callables carry the tree.
