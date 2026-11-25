# results/

Run artifacts (BUILD_OUTLINE.md section 6). One JSON object per line in `results/*.jsonl`. Every row carries:

| Field | What |
|---|---|
| `run_id` | unique per run |
| `git_sha` | commit the run used |
| `machine` | read at run time (`nvidia-smi`, `/proc/cpuinfo`, `/proc/meminfo`; on the box, `$FORGE_MACHINE_FILE`), never copied from a notes file |
| `model_revision` | Hugging Face commit or vendor revision; `null` when no model runs |
| `quant` | quantization; `null` when none |
| `runtime` | serving runtime and version; `null` when none |
| `date` | ISO 8601 |

Any number in a README, PR, `DEFENSE.md` or outreach draft points to a row here. Negative results stay.

| File | What |
|---|---|
| `P1-feasibility.jsonl` | P1 probe: GnuCOBOL syntax check of the non-CICS programs. Not an eval. |
| `P2-split-syntax.jsonl` | P2 sanity check of the split's COBOL-side changes. Not an eval. |
| `P4-runset-rfi.jsonl` | P4 probe of the grader's configuration (`scripts/p4-runset-probe.py`): the CardDemo baseline before P4, with each of RFI-P3a-1 and RFI-P3a-2 alone, and after P4. Not an eval: no prediction is scored. |
| `E0-dev.jsonl`, `E0-heldout.jsonl` | P5 release run of E0, the one-hop baseline (SPEC.md), on the frozen split. One row per change plus one summary row. |
| `E1-dev.jsonl`, `E1-heldout.jsonl` | P5 release run of E1, the full graph, on the frozen split. Heldout runs once per release (`contracts/eval.md` rule 2). |
| `P5-release.json` | The release runs' ids, git SHA and `code_digest` (sha256 over the tracked files that decide a score). A repeat checks that digest first. |
| `P5-repeat-E0-dev.jsonl`, `P5-repeat-E1-dev.jsonl` | P5 repeat of E0 and E1 on dev at the same commit. Identical to the release rows apart from run_id, date, git_sha, git_dirty and machine (`scripts/p5-eval.py repeat`). |
| `summary.md` | The results tables made from the release rows, plus the last repeat check. `scripts/eval.sh` rewrites it, and the box posts it as the PR comment. |
| `P5-failure-case.md` | The one failure case: the two heldout pairs E1 missed. |

`P5-box-*.jsonl` rows come from the box (`scripts/eval.sh` with no argument) and are uploaded as the eval workflow's artifact, not committed.
