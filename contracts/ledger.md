# Ledger (P3c)

A folder holding `ledger.jsonl` (one entry per line, append-only) and `objects/` (file contents by SHA-256).

## Entry (`ledger-entry.schema.json`)

| Field | Meaning |
|---|---|
| `seq` | 1 for the first entry, then +1 each time. |
| `ts` | ISO 8601 time of writing. |
| `kind` | `approve` (the change was applied), `deny` (recorded, not applied), `revert` (an earlier approve was undone). |
| `record` | The approval record (`allowlist.md`) for `approve` and `deny`; `null` for `revert`. |
| `reverts` | For `revert`, the `seq` of the entry it undoes; otherwise `null`. |
| `files` | Each file the entry wrote: `{"path", "before_sha256", "after_sha256"}`, paths relative to the tree root. Both contents are stored in `objects/<sha256>`. Empty for `deny`. |
| `prev_sha256` | `entry_sha256` of the previous entry; 64 zeros for `seq` 1. |
| `entry_sha256` | SHA-256 of the entry's canonical JSON without this field. |

**Canonical JSON:** `json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` encoded as UTF-8. Each line of `ledger.jsonl` is the canonical JSON of the whole entry, `entry_sha256` included.

## Operations

- `approve(record, root)`: refuses a `deny` decision; applies `record.change` to the files under `root` (all or nothing, `change.md`), stores before and after contents, appends an `approve` entry.
- `deny(record)`: appends a `deny` entry and touches no file.
- Every append (`approve`, `deny`, `revert`) holds an exclusive lock on the folder and runs `verify()` first. It refuses to append to a chain that does not verify, so tampering is never buried under valid entries.
- `verify()`: returns `{"ok": bool, "problems": [{"seq": int or null, "problem": str}]}`. It recomputes each `entry_sha256`, checks each `prev_sha256` link and checks that `seq` runs 1, 2, 3 with no gap. An edited, deleted, inserted or reordered entry makes `ok` false. It also checks that every object an entry names exists and hashes to its name. It also returns `entries` (the count) and `head_sha256` (the last entry's `entry_sha256`, or `null` when empty). The chain cannot show a deleted last entry, so keep `head_sha256` outside the ledger folder and check it later with the CLI's `verify --expect-head` (SECURITY.md A-1).
- `revert(seq, root)`: the target must be an `approve` that has not been reverted. Each file must currently hash to its `after_sha256`; if one does not, nothing is written and the revert fails. Otherwise every file is restored byte for byte from `before_sha256` and a `revert` entry is appended. No existing line of `ledger.jsonl` is ever rewritten.
