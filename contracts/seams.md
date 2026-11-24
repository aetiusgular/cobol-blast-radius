# Seams: the Python entry points each lane implements

P2 wrote each function as a stub that raises `NotImplementedError("<module>.<function>")`. A lane replaces the body and keeps the signature. Red tests (`tests/red/`) call only these names. Python 3.12 or later, standard library only; a lane that needs a package asks under Requests for integration (it would go in `scripts/setup.sh`).

## P3a, `groundtruth/` (F3, F4)

| Function | Returns |
|---|---|
| `groundtruth.harness.run(root, runset, workdir, change=None)` | A run result (`ground-truth.md`). `root` is a CardDemo-shaped tree, `runset` the parsed run-set dict, `workdir` an empty folder the harness may use. The harness copies `root` before applying `change`; it never writes under `root`. |
| `groundtruth.diff.diff(baseline, after)` | An output diff (`ground-truth.md`). Pure: reads its two arguments only. |
| `groundtruth.generate.generate(cls, seed, root, runset)` | A change (`change.md`) of class `cls`, the same bytes for the same arguments. `compile_break` is `true` or `false`, never `null`: the generator checks with `cobc -fsyntax-only` and the run set's `cobc_flags`, the same flags the harness builds with. |
| `groundtruth.changes.apply(change, root)` | Applies a change in place under `root`, all or nothing. Raises `groundtruth.changes.ApplyError` on a `before` mismatch. |

## P3b, `radius/` (F1, F2)

| Function | Returns |
|---|---|
| `radius.graph.build(root)` | A graph (`graph.md`). |
| `radius.predict.predict(change, root, runset)` | A radius (`radius.md`) from the full graph predictor. |
| `radius.predict.predict_e0(change, root, runset)` | A radius from the E0 one-hop baseline (SPEC.md). |

## P3c, `approval/` (F5, F6, F7)

| Function | Returns |
|---|---|
| `approval.allowlist.decide(radius, rules)` | A decision (`allowlist.md`). `rules` is the list under `"rules"`. |
| `approval.ledger.Ledger(path)` | A ledger in folder `path` (created if missing), with `approve(record, root)`, `deny(record)`, `verify()`, `revert(seq, root)` and `entries()` (`ledger.md`). |
| `approval.evalrun.run(split, split_path, eval_doc, root, runset, out_path, predict, ground_truth)` | Writes rows (`eval.md`) to `out_path` and returns them. `predict(change)` returns a radius and `ground_truth(change)` returns an output diff, so the runner can be tested without either lane. Raises `approval.evalrun.SplitHashMismatch` before any work when `split == "heldout"` and `split_path` does not hash to `eval_doc`'s `split-sha256`. |
| `approval.evalrun.machine()` | The machine string, read at run time (`eval.md`). |
| `python3 -m approval.cli` | The CLI: `predict`, `decide`, `approve`, `deny`, `verify`, `revert`, `eval`. JSON on stdout. |

## Lane unit tests

A lane's own tests go in `<package>/tests/test_*.py`, with an `__init__.py` in `<package>/tests/`. `scripts/test.sh` runs `python3 -m unittest discover -s <package>/tests -t .` for each package in every phase; `lane-ownership.json`'s `uncollected` rules refuse test files it would not find.

## Who may import whom

- `radius` imports nothing from `groundtruth` or `approval`.
- `groundtruth` imports nothing from `radius` or `approval`.
- `approval` may import both, through the names above only.

`scripts/check-isolation.py` enforces the first two in `scripts/test.sh`, and also fails if anything under `radius/` names a heldout change id or the word `heldout`.
