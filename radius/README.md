# radius/: the graph and the blast-radius predictor (lane P3b)

`radius.graph.build(root)` turns a CardDemo-shaped tree into the graph in `contracts/graph.md`. `radius.predict.predict(change, root, runset)` returns the static blast radius in `contracts/radius.md`, and `radius.predict.predict_e0` returns the one-hop E0 baseline from SPEC.md. The code uses only the Python standard library, never runs a program, and imports nothing from `groundtruth/` or `approval/`.

## How the full predictor works

1. **Two sides.** The predictor applies the change's `edits` in memory and parses the tree twice, before and after. An edited line counts only when its meaning changes: for COBOL, columns 8 to 72 of a line that is not a comment; for JCL, a line that is not `//*`; for control members, the text outside `/* */`. A comment-only edit therefore changes nothing.
2. **Parsing with provenance.** COBOL is tokenised in fixed format. Every `COPY` (nested ones and `REPLACING` included) is expanded, and each token keeps the file and line it came from, so a line in a copybook leads to the data item it defines in each program. Data items get byte offsets and sizes from their PIC, USAGE, OCCURS and REDEFINES. The procedure division is split into paragraphs and statements, and each statement records the conditions that enclose it: IF, EVALUATE, inline PERFORM UNTIL, and AT END or INVALID KEY phrases. JCL is read with continuations, in-stream data, PROC expansion with symbolic parameters, procstep DD overrides, concatenation and GDG relative generations.
3. **Seeds.** An edited data entry whose only change is its VALUE taints that item's bytes. Any other change (PIC, USAGE, OCCURS, REDEFINES, a new entry) is a layout change: it taints the item and every byte after it in its record, and, in an FD record, also the file's shape. An edited statement is seeded: its targets, its outputs and the scope it controls all count as changed. Edits outside data items and statements (SELECT, PROGRAM-ID, division headers) make every output of the program change.
4. **Inside a program.** Taint runs to a fixed point over the statements in paragraphs that can run. Reachability comes from the entry paragraph, PERFORM (THRU), GO TO and fall-through, so a paragraph that nothing performs, jumps to or falls into contributes nothing. Data flows through MOVE (a group move keeps byte positions), arithmetic, STRING, UNSTRING, INSPECT, SET, CALL USING, READ INTO and WRITE FROM. Control flows from any changed condition to everything in its scope, including paragraphs it performs. A changed condition that guards STOP RUN, GOBACK or GO TO makes every output of the program change, and one that guards `CALL 'CEE3ABD'` (abend) also changes every later step of the job.
5. **Across steps and jobs.** Run-set jobs are walked in order. A dataset is either content-changed (the record bytes) or shape-changed (record count, length, keys or existence). A program step that reads a changed dataset gets its file's record tainted, plus the file's status and AT END conditions when the shape changed. A SORT, REPRO or IEBGENER passes its input's level to its output, and a SORT with INCLUDE or OMIT turns content into shape. A changed JCL statement shape-changes the outputs it governs: an EXEC changes the whole step, a DD changes that file, and a utility step changes everything it writes.
6. **The radius.** `datasets` lists the changed datasets that a run-set step writes, named as in `runset.md`. `steps`, `jobs` and `programs` are the steps with at least one changed output, their jobs and their programs. `why` gives one path of node ids from the edited member to each dataset. `unverifiable` lists programs that no run-set step runs (the CICS programs and batch programs outside the run set) whose tokens the edit touches.

## E0

E0 is the naive baseline: every output of every run-set job that runs a program which COPYs a changed member (nested COPYs included), runs a changed program, or is or expands a changed JCL member. It does no data flow and no check of whether an edited line means anything, so a comment edit counts too.

## Known limits (static over-approximation)

- The analysis ignores statement order. A value that is stored and then always overwritten before anyone reads it (for example `MOVE 8 TO APPL-RESULT` just before an OPEN that resets it) still counts. That costs precision, not recall.
- A dataset stays changed once it is changed, even if a later step deletes and redefines it. A GDG base must work that way, because its earlier generations remain. A plain dataset that is rebuilt from clean inputs is over-reported.
- The predictor does not model whether a changed path runs on the shipped data. SPEC.md table 3 ("reachable but unchanged") measures this.
- WRITE status depends only on key bytes for indexed files and on nothing for sequential ones. A data-dependent I/O error (for example, a duplicate key caused by non-key bytes) is not modelled.
- DISPLAY output is attributed to the step's `SYSOUT` DD. A step with no `SYSOUT DD SYSOUT=*` has no SYSOUT output.

## What ran (P3b, 2026-11-24, on the session's Linux workstation)

- `bash scripts/test.sh`: contracts, isolation and every lane's unit tests pass, the 19 in `radius/tests/` included.
- `bash scripts/forge-gate.sh P3b`: P3a's and P3b's red tests are green, P3c's fail for their stated reason, lane-scope is clean, and the split hash matches.
- `radius.graph.build` on CardDemo at the pinned commit parses all 31 programs and 38 job files with `errors == []`.
- A crash sweep in the session scratchpad, not committed: 186 synthetic one-line edits across the run-set jobs, programs, two copybooks, REPROC and REPROCT. Each went through both predictors, and none raised or broke the schema.
- The 20 dev rows were predicted and inspected for plausibility. No ground truth was compared, and no harness run was made from this lane: eval rule 3 runs E0 before any tuning is recorded, and that happens in P5.
