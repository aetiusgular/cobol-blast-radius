# Change format (`change.schema.json`)

A proposed change to CardDemo, as concrete line edits. The example below is illustrative. The generator (P3a) writes it, the harness (P3a) applies it, the predictor (P3b) reads it, and the approval record and ledger (P3c) store it and apply it.

```json
{
  "id": "S-017",
  "class": "copybook_field",
  "seed": 20261124017,
  "summary": "CVACT01Y: ACCT-CURR-BAL PIC S9(10)V99 to S9(11)V99",
  "edits": [
    {"file": "app/cpy/CVACT01Y.cpy", "line": 9, "op": "replace",
     "before": "           05  ACCT-CURR-BAL                     PIC S9(10)V99.", "after": "..."}
  ],
  "compile_break": false
}
```

| Field | Rule |
|---|---|
| `id` | Unique in its file. The frozen split uses `S-001` to `S-060`. |
| `class` | `copybook_field`, `program_logic`, `jcl_step` or `noop`. A `noop` changes only comments; its true radius is empty. |
| `seed` | The seed it was generated from, or `null` for a hand-written change. |
| `summary` | One human line. **The predictor must not read it**: it predicts from `edits` and the source tree alone. |
| `edits` | One or more edits, applied in order. `file` is relative to the CardDemo root. `line` is 1-based and refers to the file as it stands before this edit. |
| `op` | `replace`: line `line` must equal `before` exactly, and becomes `after`. `insert_after`: `before` is `null`, and `after` becomes a new line after line `line` (0 inserts at the top). |
| `compile_break` | `true` when the generator knows the change does not compile. `false` when it is expected to compile. `null` when nobody checked. The harness's compile result is the truth either way. |

**Lines.** A file is split on `\n`. A line does not include its `\n`, and a `\r` before it stays part of the line. Applying an edit keeps every other byte of the file, including a missing final newline.

**Applying is all or nothing.** If any `before` does not match, nothing is written and the apply fails with the file, the line, and both texts.
