# Ground-truth formats (P3a)

## Run result (`run-result.schema.json`)

What `groundtruth.harness.run(root, runset, workdir, change=None)` returns for one full run of the run set, with `change` applied to a copy of `root` first (the original tree is never modified).

| Field | Meaning |
|---|---|
| `change_id` | The change's `id`, or `null` for the baseline. |
| `carddemo_commit` | From the run set. |
| `cobc_version` | First line of `cobc --version`, read at run time. |
| `clock` | The `COB_CURRENT_DATE` value used. |
| `compile` | For each program in the run set: `{"ok": bool, "diagnostics": "<cobc stderr, trimmed>"}`, built with the run set's `cobc_flags` (`runset.md`). A failure is reported here, never hidden. |
| `steps` | Every step in run order: `{"job", "step", "procstep", "program", "status", "rc"}`. `status` is `ok`, `abend`, `skipped` (SDSF, or a COND test), `unsupported` (outside the step-runner subset), or `not_run` (its program did not compile, or an earlier step in the job ended the job). |
| `outputs` | For each output dataset name (see `runset.md`): `{"sha256": "<of the canonical bytes>" or null when absent, "bytes": int, "generations": int}`. |
| `input_notes` | Lines padded, truncated or converted, per input. |
| `apply_error` | `null`, or the reason the change did not apply (an edit's `before` did not match). When set, nothing was built or run. `diff` reads it for `apply_failure`. |
| `cics_only` | `true` when no edited file is a run-set job, PROC or control member, a run-set program, or a copybook a run-set program COPYs (nested COPYs included), and CICS programs reach every edited file. `diff` reads it for `cics_only`. |
| `notes` | Human-readable lines about steps that did not end `ok` (JCL errors, abends, harness limits). Not compared. |

Two baseline runs on the same machine must give identical `compile`, `steps` and `outputs`.

## Output diff (`diff.schema.json`)

What `groundtruth.diff.diff(baseline, after)` returns.

| Field | Meaning |
|---|---|
| `change_id` | From `after`. |
| `changed` | Output names whose `sha256` differs, including present in one run and absent in the other. Sorted. |
| `unchanged` | The rest of the baseline's output universe. Sorted. |
| `excluded` | `true` when the change cannot be scored. |
| `exclusion_reason` | `null`, `compile_failure` (a run-set program compiled in the baseline but not after), `apply_failure` (an edit's `before` did not match), or `cics_only` (every edited member is reached only by CICS programs). |
| `status_changes` | Steps whose `status` or `rc` differ, as `{"step": "<job>.<step>[.<procstep>]", "before": ..., "after": ...}`. |

A changed output is a changed output, whatever the reason (a different record, an abend that leaves a file short, a step that no longer runs). The diff does not judge why.
