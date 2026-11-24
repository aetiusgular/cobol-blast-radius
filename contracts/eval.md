# Eval contract (frozen in P2)

split-sha256: a13f5b01ff3330650ac9bcff725c54f84e2364366cdec336dbb3bf9d347341e2
split-path: contracts/split.jsonl

`scripts/forge-gate.sh` recomputes the hash in every phase after P2. Changing one byte of `contracts/split.jsonl` fails the gate. A new split is a new P2 decision, logged as Tony's call.

## The split

- 60 changes in the change format (`change.md`), one JSON object per line, each with a `split` field: **20 dev, 40 heldout**.
- Built by `scripts/make-split.py` from CardDemo at `59cc6c2fd7ebd7ef7925cad552a01a4b8b6e4d5e`, master seed 20261124. Running it again on that commit gives the same bytes.
- Per class, dev / heldout: `copybook_field` 6 / 12, `program_logic` 6 / 12, `jcl_step` 4 / 8, `noop` 4 / 8.
- Every change targets a run-set program, a copybook a run-set program COPYs, or a run-set job file (`runset.json`).
- `compile_break` is `null` for all 60: P2 did not decide compilability; the harness does. P2's syntax check (`results/P2-split-syntax.jsonl`, a sanity check and not an eval) found no syntax error in the 44 COBOL-side changes.

## Rules

1. **Tune on dev only.** The graph lane (P3b) builds and tests against `fixtures/` and the dev rows. It does not read the heldout rows, and nothing in `radius/` may name a heldout change id or the word `heldout` (`scripts/check-isolation.py`); code that reads the split filters on `"dev"`.
2. **Heldout runs once per release**, through the eval runner, which refuses to run heldout when the file's SHA-256 is not the one above (`approval.evalrun.SplitHashMismatch`).
3. **E0 runs first**, on dev and heldout, before any tuning of the graph is recorded. E0 is the one-hop baseline in SPEC.md.
4. **No model, so no five-run bands.** A repeat run at the same commit must give identical rows apart from `run_id` and `date`. A difference is a bug.

## Scoring

For each heldout change that is not excluded (`diff.excluded` false):

- `changed` = the harness's `diff.changed` (ground truth).
- `predicted` = the radius's `datasets`, intersected with the baseline's output universe, which the runner reads from the diff as `changed` ∪ `unchanged`. Predicted names outside the universe are counted in their own column (`predicted_outside_universe`) and do not enter precision.

Over the split, as micro averages over (change, output dataset) pairs:

- **Recall** (the headline) = Σ |predicted ∩ changed| / Σ |changed|.
- **Precision** = Σ |predicted ∩ changed| / Σ |predicted|.
- Each per class, in its own table. Never a composite.

A `noop` change with empty `changed` and empty `predicted` adds nothing to either sum; it is reported in a no-op table as correct (both empty) or not. Excluded changes are counted by reason and never enter recall.

## Rows (`results-row.schema.json`)

One row per (run, change) in `results/E<k>-<split>.jsonl`, plus one summary row per run. Every row carries the section 6 fields (`run_id`, `git_sha`, `machine` read at run time, `model_revision`, `quant`, `runtime`, `date`), and also `carddemo_commit`, `cobc_version`, `split`, `split_sha256` and `predictor`.

`machine` is read at run time: the contents of `$FORGE_MACHINE_FILE` when that variable is set (the box), otherwise `<cpu model from /proc/cpuinfo>|<MemTotal in GiB from /proc/meminfo>|<nvidia-smi GPU name, or "no GPU">`.
