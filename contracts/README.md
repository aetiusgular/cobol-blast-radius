# contracts/

Written in P2. The seams the lanes build against. Lanes do not edit this folder; changes go under "Requests for integration" in the PR and P4 applies them.

| File | What | Producer, consumer |
|---|---|---|
| `seams.md` | The Python entry points of each lane, and who may import whom | all |
| `runset.json`, `runset.md` | The batch run set, dataset naming, the output universe, canonical bytes | P3a runs it, P3b reasons over it |
| `change.md`, `change.schema.json` | A proposed change as line edits | P3a writes and applies, P3b reads, P3c stores |
| `graph.md` | Graph node ids and edge kinds | P3b |
| `radius.md`, `radius.schema.json` | The predicted blast radius | P3b writes, P3c reads |
| `ground-truth.md`, `run-result.schema.json`, `diff.schema.json` | Harness run result and output diff | P3a writes, P3c reads |
| `allowlist.md`, `allowlist.schema.json` | Allowlist rules, strictest-wins decision, approval record | P3c |
| `ledger.md`, `ledger-entry.schema.json` | Hash-chained ledger, verify and revert | P3c |
| `eval.md`, `results-row.schema.json`, `split.jsonl` | The frozen split, scoring, results rows | P3c's runner, P5 |

The schemas use a small subset of JSON Schema (type, enum, required, properties, additionalProperties, items, minItems, minimum, minLength, pattern); `tests/red/_support.py` checks it with the standard library.

`eval.md` freezes the split (BUILD_OUTLINE.md section 6). `scripts/forge-gate.sh` reads two lines from it:

```
split-sha256: <64 hex characters>
split-path: <file or folder in the repo>
```

A file hashes as its sha256. A folder hashes as the sha256 of the `sha256sum` lines of its files, sorted by path, paths relative to the folder:

```
(cd <folder> && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum) | sha256sum
```

Leave out `split-path` only when the split cannot live in the repo (data terms); the gate then checks that the hash is present but cannot recompute it.
