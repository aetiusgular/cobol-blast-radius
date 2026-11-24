# groundtruth/ (lane P3a)

The ground truth for the blast radius: build the run set with GnuCOBOL, run its jobs, and byte-compare every output before and after a change. Contracts: `contracts/ground-truth.md`, `contracts/runset.md`, `contracts/change.md`, `contracts/seams.md`. This package never imports `radius/` or `approval/` (`scripts/check-isolation.py`).

| Module | What |
|---|---|
| `changes.py` | `apply(change, root)`: line edits, all or nothing. `plan()` checks every edit before anything is written. |
| `diff.py` | `diff(baseline, after)`: changed and unchanged outputs, the exclusion reason, step status changes. Pure. |
| `harness.py` | `run(root, runset, workdir, change=None)`: copy the tree, apply the change, build, run every job, hash every output. |
| `jcl.py` | The JCL reader: statements, continuations, in-stream data, concatenation, PROCs (in-stream and `JCLLIB`), symbolic parameters, procstep DD overrides. |
| `catalog.py` | The dataset catalog: sequential files, GDG bases and generations, indexed files, alternate indexes, paths. Output names and canonical bytes. |
| `utilities.py` | IDCAMS (DELETE, DEFINE CLUSTER/AIX/PATH/GDG, REPRO, BLDINDEX, IF/SET), SORT (FIELDS, INCLUDE/OMIT COND, SYMNAMES), IEBGENER, IEFBR14. |
| `cobol.py` | cobc calls, the step driver, the indexed-file loader, the stubs. |
| `generate.py` | `generate(cls, seed, root, runset)`: one seeded change of a class, with `compile_break` decided by `cobc -fsyntax-only`. |
| `stubs/` | COBOL stand-ins for `CEE3ABD` (ends the step as an abend) and `COBDATFT` (CardDemo's assembler date formatter, the same byte moves as `app/asm/COBDATFT.asm`). |

## How a run works

1. `root` is copied into `workdir/src` and the change is applied to the copy. `root` is never written.
2. Every run-set program is built as a module with `cobc -m` plus the run set's `cobc_flags`, run from inside the copy with relative paths, so diagnostics repeat across runs.
3. Inputs are loaded as fixed-length records: ASCII lines are padded or truncated to `lrecl`, EBCDIC records are converted from code page 037. The counts go in `input_notes`.
4. Jobs run in run-set order. A COBOL step runs through a small driver (`GTDRIVER`) that CALLs the program with an IBM-style PARM area: a halfword length, then the text. Each DD becomes a `DD_<name>` environment variable. `DISPLAY` output is the step's `SYSOUT` DD. `FUNCTION CURRENT-DATE` is fixed by `COB_CURRENT_DATE` and `TZ=UTC`.
5. A VSAM KSDS is a GnuCOBOL indexed file (Berkeley DB). IDCAMS loads and unloads it through a generated COBOL loader for its shape (record size, prime key, alternate keys). BLDINDEX rebuilds the file with the alternate key, so a program that declares `ALTERNATE RECORD KEY` finds it.
6. Dispositions follow DISP: NEW, MOD, OLD and SHR on allocation; the normal disposition after a step; the abnormal one after an abend. GDG relative numbers are fixed at job start, and LIMIT rolls off the oldest generation.
7. An abend (a `CEE3ABD` call, a libcob runtime error or a timeout) or a missing dataset ends the job. Later steps are `not_run` unless COND=EVEN or ONLY. A run-set program that did not compile cannot start, so its step is `not_run` and the job ends, as with a missing load module.
8. Outputs are every dataset a step created or wrote that exists at the end, plus the SYSOUT of COBOL steps, hashed over their canonical bytes (`contracts/runset.md`).

Two fields go beyond `run-result.schema.json`, which allows extra fields: `apply_error` (the ApplyError text, or null), which `diff` maps to `apply_failure`, and `cics_only`, which `diff` maps to `cics_only`. A third, `notes`, holds harness messages: JCL errors, abends, unsupported statements. `notes` is not part of the repeat check.

## Known limits of the stand-in

These are places where this ground truth can differ from z/OS. They are listed so P4 and P5 can weigh them, and so no result claims more than the harness does.

- GnuCOBOL's indexed handler does not check a program's declared record key against the file, and GnuCOBOL ignores DCB LRECL. On z/OS a key-length or record-length mismatch fails OPEN with file status 39. Here the program runs. A `jcl_step` change to `KEYS(...)` or `LRECL=` can therefore give a different ground truth from a mainframe.
- SORT compares bytes in the data's own code. The run set's data is ASCII, so CH fields sort in ASCII order, not EBCDIC order.
- Utility messages (IDCAMS and SORT SYSPRINT) are the harness's own and are not outputs, per the contract.
- An unsupported statement ends its step with status `unsupported` and a note. The harness never guesses.
- Sign convention and clock: see Requests for integration in the P3a PR (`-fsign=EBCDIC`, and a clock inside TRANREPT's date window). Until P4 decides, the harness runs exactly what `contracts/runset.json` says.

## What ran (P3a)

- `bash scripts/test.sh`: contracts, isolation, compile, and the lane unit tests in `groundtruth/tests/`, which cover the JCL reader, SORT and IDCAMS parsing, apply and diff edge cases, a synthetic job set (GDG rolloff, COND, concatenated SORTIN, KSDS key order, a JCL error ending a job, an apply failure), the compile-break check, and the CardDemo baseline repeating across two work folders with every run-set program built and every step `ok` or `skipped`.
- `bash scripts/forge-gate.sh P3a`: the P3a red tests are green, and the P3b and P3c red tests still fail for their stated reasons.
- The 20 dev changes of the frozen split were run through the harness while building it, to find crashes and non-determinism. Every dev noop gave an empty diff. Heldout changes were not run: heldout is for P5, once.
- Machine, read at run time: AMD Ryzen 5 9600X (`/proc/cpuinfo`), `/proc/meminfo` MemTotal 127044444 kB, Linux 7.0.0, Python 3.14.4, `cobc (GnuCOBOL) 3.2.0` built by `scripts/setup.sh` flags (BDB, no XML). Base commit `eddf7f6`, 2026-11-24.
