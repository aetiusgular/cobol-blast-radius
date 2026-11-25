# Radius format (`radius.schema.json`)

What `radius.predict.predict(change, root, runset)` returns: the static prediction of what a change reaches. It is computed from the change's `edits` and the source tree only. The predictor never runs a program and never reads a harness result.

| Field | Meaning |
|---|---|
| `change_id` | The change's `id`. |
| `members` | Members the edits touch (`app/cpy/CVACT01Y.cpy` gives `CVACT01Y`). |
| `fields` | Copybook fields whose definition the edits change (`CVACT01Y.ACCT-CURR-BAL`). Empty for a change that is not inside a data definition. |
| `programs` | Programs whose behaviour may change. |
| `jobs`, `steps` | Jobs and steps (step ids without the `step:` prefix) that may behave differently. |
| `datasets` | Output datasets (names as in `runset.md`) whose bytes may change. **This is the list that is scored.** |
| `unverifiable` | Node ids the change reaches that ground truth cannot run: programs that no run-set step runs (CICS programs among them, and batch programs outside the run set) and anything only they write. Reported, never scored (P4, RFI-P3b-2). |
| `why` | For each entry in `datasets`, one path of node ids from an edited member to that dataset. |
| `predictor` | `{"name": ..., "version": ...}`, so a results row can say which predictor made it. |

Lists are sorted and hold no duplicates. A `noop` change, and a change only inside code that cannot run (a paragraph nothing PERFORMs, GO TOs or falls into), must give empty `programs`, `jobs`, `steps` and `datasets`.

The E0 baseline (SPEC.md) is a predictor too, and returns the same format with `predictor.name` = `e0-one-hop`.
