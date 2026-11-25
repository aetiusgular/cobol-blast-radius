## cobol-blast-radius P5: blast radius against GnuCOBOL output diffs

Release rows: git `9a4cd0827216`, CardDemo `59cc6c2f`, `cobc (GnuCOBOL) 3.2.0`, machine `AMD Ryzen 5 9600X 6-Core Processor|121.2 GiB|no GPU`, 2026-11-25. No model. Unit: (change, output dataset) pairs, micro averaged. Every table stands alone.

### 1. Recall and precision

| run | split | changes | scored | changed | predicted | hits | recall | precision | run_id |
|---|---|---|---|---|---|---|---|---|---|
| E0 (e0-one-hop@1) | dev | 20 | 20 | 32 | 55 | 14 | 0.438 | 0.255 | `2026-11-25-7e3247468869` |
| E0 (e0-one-hop@1) | heldout | 40 | 40 | 75 | 120 | 46 | 0.613 | 0.383 | `2026-11-25-6575fbf03a54` |
| E1 (graph-dataflow@1) | dev | 20 | 20 | 32 | 51 | 32 | 1.000 | 0.627 | `2026-11-25-feb2bc8ff724` |
| E1 (graph-dataflow@1) | heldout | 40 | 40 | 75 | 120 | 73 | 0.973 | 0.608 | `2026-11-25-27739e5f37d7` |

### 2. Per change class

| run | split | class | scored | changed | predicted | hits | recall | precision |
|---|---|---|---|---|---|---|---|---|
| E0 | dev | copybook_field | 6 | 16 | 25 | 9 | 0.562 | 0.360 |
| E0 | dev | jcl_step | 4 | 6 | 8 | 1 | 0.167 | 0.125 |
| E0 | dev | noop | 4 | 0 | 9 | 0 | — | 0.000 |
| E0 | dev | program_logic | 6 | 10 | 13 | 4 | 0.400 | 0.308 |
| E0 | heldout | copybook_field | 12 | 42 | 69 | 35 | 0.833 | 0.507 |
| E0 | heldout | jcl_step | 8 | 26 | 19 | 4 | 0.154 | 0.211 |
| E0 | heldout | noop | 8 | 0 | 16 | 0 | — | 0.000 |
| E0 | heldout | program_logic | 12 | 7 | 16 | 7 | 1.000 | 0.438 |
| E1 | dev | copybook_field | 6 | 16 | 17 | 16 | 1.000 | 0.941 |
| E1 | dev | jcl_step | 4 | 6 | 19 | 6 | 1.000 | 0.316 |
| E1 | dev | noop | 4 | 0 | 0 | 0 | — | — |
| E1 | dev | program_logic | 6 | 10 | 15 | 10 | 1.000 | 0.667 |
| E1 | heldout | copybook_field | 12 | 42 | 47 | 42 | 1.000 | 0.894 |
| E1 | heldout | jcl_step | 8 | 26 | 53 | 26 | 1.000 | 0.491 |
| E1 | heldout | noop | 8 | 0 | 0 | 0 | — | — |
| E1 | heldout | program_logic | 12 | 7 | 20 | 5 | 0.714 | 0.250 |

### 3. No-op controls (correct = nothing changed and nothing predicted)

| run | split | correct | incorrect | excluded | incorrect ids |
|---|---|---|---|---|---|
| E0 | dev | 0 | 4 | 0 | S-051, S-053, S-056, S-059 |
| E0 | heldout | 0 | 8 | 0 | S-049, S-050, S-052, S-054, S-055, S-057, S-058, S-060 |
| E1 | dev | 4 | 0 | 0 | — |
| E1 | heldout | 8 | 0 | 0 | — |

### 4. Misses, false alarms, exclusions

| run | split | changes with a miss | missed pairs | false-alarm pairs | excluded (reason: n) | predicted outside the output universe | unverifiable (CICS or not in the run set) | predict errors |
|---|---|---|---|---|---|---|---|---|
| E0 | dev | 3 | 18 | 41 | 0 | 1 | 1 | 0 |
| E0 | heldout | 6 | 29 | 74 | 0 | 2 | 38 | 0 |
| E1 | dev | 0 | 0 | 19 | 0 | 1 | 1 | 0 |
| E1 | heldout | 2 | 2 | 47 | 0 | 1 | 38 | 0 |

Table 3 of SPEC.md ("reachable but unchanged", split into "path not exercised" and "change is equivalent") is not produced: the harness gives a byte diff and cannot tell the two apart, so false alarms are counted only as one column above.

### 5. Repeat run `repeat` (eval.md rule 4)

| check | result | note |
|---|---|---|
| scored code matches the release's | pass | 548bcf693398edd4 vs 548bcf693398edd4 |
| E0 dev repeat (20 changes) identical to release run 2026-11-25-7e3247468869 | pass | identical apart from run_id, date, git_sha, git_dirty, machine |
| E1 dev repeat (20 changes) identical to release run 2026-11-25-feb2bc8ff724 | pass | identical apart from run_id, date, git_sha, git_dirty, machine |
