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
