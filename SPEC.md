# SPEC: cobol-blast-radius

Written in P1 (2026-11-23). Evidence and scoring are in `research/P1.md`. Later phases do not reopen the pick (BUILD_OUTLINE.md section 2). A change to the headline number goes through a Request for integration, and P4 decides.

## What it is

You propose a change to CardDemo: a copybook field, a program statement or a JCL step. The tool reports its blast radius: the programs, batch jobs and output datasets the change reaches. The report goes on an approval record. Approval is checked against an allowlist and written to a hash-chained ledger that can revert the change.

The prediction is static and deterministic. The ground truth is execution: GnuCOBOL compiles and runs the batch chain before and after the change, and the output datasets are byte-diffed. The graph never sees the diff.

Static impact graphs already exist (AWS Transform's dependency JSON, IBM ADDI, Imogen's parser, HyperDocs). This build adds two things none of them publish: a measured accuracy for the static prediction against execution, and that prediction on the agent's approval step.

## Headline number

**Blast-radius recall on the heldout set:** of the output datasets that actually change when a seeded change runs under GnuCOBOL, the fraction the static blast radius predicted.

- **Unit:** a (seeded change, output dataset) pair. Recall = |predicted and changed| / |changed|, summed over the heldout changes (micro average).
- **N = 60 seeded changes**, split 20 dev and 40 heldout. P2 generates, freezes and hashes the split in `contracts/eval.md`. Tuning uses dev only. Heldout runs once per release.
- **Ground truth, from outside the system under test:** for each change, `cobc` (GnuCOBOL 3.2) builds every batch program in the run set and the frozen step runner executes the chosen jobs on CardDemo's shipped ASCII data. An output dataset counts as changed when its bytes differ from the baseline run. The graph code does not import the harness, and the harness does not import the graph.
- **Why recall leads:** on an approval card, a missed impact is the costly error, and a false alarm is the cheap one. Precision is reported in its own table and is never folded into a composite (section 6, item 6).

### Reported beside it, one table each

1. Precision on the same pairs.
2. Recall and precision for each change class: copybook field, program logic, JCL step, no-op control.
3. Reachable but unchanged: outputs the graph flags that execution leaves the same, split into "path not exercised by the data" and "change is equivalent", where the harness can tell them apart.
4. Changes left out: ones that do not compile, or that touch only CICS programs, each with its count and reason. They never count toward recall.
5. E0 baseline: "every job that runs a program which COPYs the changed member, or runs the changed program" (one hop, no data flow), on the same split.

## Scope

**In**
- CardDemo at pinned commit `59cc6c2fd7ebd7ef7925cad552a01a4b8b6e4d5e`. The batch side covers `app/cbl` programs without `EXEC CICS`, their copybooks in `app/cpy`, and the JCL in `app/jcl` and `app/proc` that runs them.
- A graph with nodes for program, copybook, copybook field, JCL job, step, DD and dataset. Edges are COPY, CALL, EXEC PGM, DD to DSN, and dataset written by one step and read by a later one.
- A seeded-change generator with the four classes above. It is deterministic from a seed and lives on the eval side.
- A ground-truth harness: a GnuCOBOL build, a JCL step runner for only the subset the chosen jobs use (EXEC PGM, DD DSN to file, IDCAMS DEFINE and REPRO, SORT FIELDS, IEBGENER), and a byte diff of the outputs.
- An approval record: the change, the predicted radius, allowlist rule hits (allow, ask or deny, per dataset, program or job pattern) and the decision. The ledger is append-only, each entry carries the SHA-256 of the previous one, a `verify` command checks the chain, and `revert <entry>` restores the pre-change files and appends a revert entry.
- A CLI to run this and a JSON output format. Names are generic. No company name appears in package, CLI or flags.

**Out**
- CICS online programs. They stay in the graph as nodes, and their impacts are marked "predicted, not verifiable".
- Db2, IMS and MQ optional modules.
- A real mainframe, TN3270, z/OSMF, or any vendor's product or account.
- An LLM that proposes changes. Nothing in the core needs a model, so P5 runs on ubuntu-latest. If a later phase adds one, it moves to the box with five-run bands.
- Production change management.

## Features to test (P2 writes at least one red test per feature)

| ID | Feature | Corner cases P2 should cover |
|---|---|---|
| F1 | Parse CardDemo batch sources into the graph | COPY REPLACING; copybooks nested in copybooks; PROC expansion and symbolic parameters in JCL; GDG relative generations (`(+1)`, `(0)`); programs that fail to compile still appear as nodes |
| F2 | Predict the blast radius of a change | field-level change versus whole copybook; a change only inside a paragraph that is never PERFORMed; datasets passed between jobs; a no-op change, which must give an empty radius |
| F3 | Ground-truth harness | baseline is identical across two runs (determinism); EBCDIC versus ASCII data handled; a compile failure is reported, not hidden; outputs compared byte for byte |
| F4 | Seeded-change generator | the same seed gives the same change; each class produces a change that compiles, or one that is marked as a compile-break |
| F5 | Allowlist | first match wins, or the strictest wins (P2 picks and writes it in a contract); a pattern matches both dataset names and members; an empty allowlist means everything asks |
| F6 | Hash-chained ledger | `verify` catches an edited entry, a deleted entry and a reordered entry; `revert` restores the files byte for byte and appends an entry, never rewrites one |
| F7 | Eval runner | writes `results/*.jsonl` rows with the section 6 fields; reads the machine at run time; refuses to run heldout when the split hash does not match |

## Suggested lanes (P2 decides the final map)

| Lane | Owns | Depends on, through contracts only |
|---|---|---|
| P3a | Ground-truth harness and seeded-change generator (F3, F4) | contract: change format and output-diff format |
| P3b | Graph and blast-radius predictor (F1, F2) | contract: change format and radius format |
| P3c | Approval record, allowlist, ledger, revert and CLI (F5, F6), plus the eval runner (F7) | contracts: radius format and ledger entry format |

P3a and P3b must not read each other's code. That keeps the ground truth independent.

## Eval plan (P5)

- E0 is the one-hop baseline above, run before any tuning of the graph.
- E1 is the full graph on dev while tuning, then once on heldout.
- No model, so no five-run bands. A repeat run at the same commit must give identical rows. Any difference is a bug, not noise.
- Each row names the CardDemo commit, the GnuCOBOL version (`cobc --version`), the machine read at run time, the git SHA and the date.
- Negative results ship. If recall on heldout is low, the README leads with that number and the failure case.

## Feasibility already shown (P1)

`results/P1-feasibility.jsonl`, run `P1-feasibility-cobc-syntax-1`: 10 of 13 non-CICS CardDemo programs pass a GnuCOBOL 3.2.0 syntax check at the pinned commit. This is a probe, not an eval number, and it is not a headline.

## Licences

CardDemo is Apache-2.0 with a NOTICE. GnuCOBOL's compiler is GPL-3+ and its runtime libcob is LGPL-3+. Both are used as installed tools, and nothing of theirs is vendored. Details are in `research/P1.md`, section 7.
