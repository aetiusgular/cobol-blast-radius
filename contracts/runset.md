# Run set (`runset.json`)

The batch slice of CardDemo that ground truth executes and that the blast radius is scored on. Both lanes read the same file; neither lane edits it.

| Field | Meaning |
|---|---|
| `carddemo_commit` | The pinned CardDemo commit. `scripts/fetch-carddemo.sh` checks it out into `vendor/carddemo`. |
| `clock` | The value the harness puts in `COB_CURRENT_DATE` for every program it runs, so `FUNCTION CURRENT-DATE` is fixed and the baseline repeats byte for byte. |
| `cobc_flags` | The dialect flags for every `cobc` call that decides ground truth: the harness's build of each program and the generator's `-fsyntax-only` check. The harness adds `-I` for each of `copy_dirs` and its own output flags (`-x` or `-m`), and nothing that changes the dialect. `-std=ibm` is the dialect the P1 probe and P2's split check used. |
| `libraries` | Partitioned data sets that JCL names (`JCLLIB ORDER`, `&CNTLLIB(REPROCT)`), mapped to a folder and the member file extensions. |
| `jobs` | The jobs, in the order they run. A job runs once per harness run. |
| `programs` | The COBOL programs the run set executes. The harness compiles each one; the generator targets only these programs, the copybooks they COPY and the job files in `jobs`. |
| `program_dirs`, `copy_dirs` | Where program sources and copybooks live. |
| `utilities` | The step-runner subset. A statement outside it ends that step with status `unsupported`; the harness reports it and never guesses. |
| `stubs` | Non-COBOL routines that run-set programs CALL. The harness supplies a stand-in for each and records what it does. |
| `inputs` | Datasets that exist before the first job. `encoding` is `ascii` (one record per line, padded with spaces to `lrecl`; a longer line is truncated and counted in the run result's `input_notes`) or `ebcdic-cp037` (fixed `lrecl`-byte records, converted with code page 037). `from: repo` means the path is relative to this repo, not to CardDemo. |
| `excluded_jobs` | Every other job file in `app/jcl`, with the reason it is out. |

## Dataset names

- A dataset is named by its DSN. A GDG generation is named by its base: `AWS.M2.CARDDEMO.SYSTRAN(+1)` and `AWS.M2.CARDDEMO.SYSTRAN(0)` are both `AWS.M2.CARDDEMO.SYSTRAN`. A base counts as changed when the bytes of any generation that exists at the end of the run differ, or when the set of generations differs.
- A VSAM cluster's `.DATA` and `.INDEX` components fold into the cluster name. An alternate index is its own dataset (`AWS.M2.CARDDEMO.CARDXREF.VSAM.AIX`), and its `.PATH`, `.DATA` and `.INDEX` names fold into it.
- `SYSOUT=*` output of a step that runs a run-set COBOL program is named `SYSOUT:<job>.<step>[.<procstep>].<dd>`, for example `SYSOUT:READACCT.STEP05.SYSOUT`, and counts as an output dataset. A utility step's `SYSPRINT` or `SYSOUT` (IDCAMS, SORT, IEBGENER) is not an output: the step runner's messages are not the real utility's.

## Output universe

The outputs scored are every dataset that a run-set step creates or writes and that exists at the end of the baseline run, plus every `SYSOUT:` name the baseline writes. Inputs that no step writes are not outputs. The harness reports the universe in its run result (`outputs`).

## Canonical bytes

- Sequential datasets: the file's bytes as written.
- Indexed (KSDS) clusters and alternate indexes: the records read in key order, concatenated. The physical file of an indexed organisation is not compared, because its layout is not part of the program's behaviour.
- `SYSOUT:` names: the bytes the program wrote to that DD, with no added headers.
