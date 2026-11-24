# Graph (P3b)

`radius.graph.build(root)` parses the sources under a CardDemo-shaped root (`app/cbl`, `app/cpy`, `app/jcl`, `app/proc`, `app/ctl`) and returns an object with two attributes:

- `nodes`: a set of node ids (strings).
- `edges`: a set of `(src, kind, dst)` tuples of node ids.

The red tests and the eval runner read only these two attributes. Anything else on the object is P3b's own.

## Node ids

| Node | Id | Example |
|---|---|---|
| Program | `program:<PROGRAM-ID or member>` | `program:CBACT04C` |
| Copybook | `copybook:<member>` | `copybook:CVACT01Y` |
| Copybook field | `field:<member>.<data-name as written in the copybook>` | `field:CVACT01Y.ACCT-CURR-BAL` |
| Job | `job:<job name>` | `job:POSTTRAN` |
| Step | `step:<job>.<step>` or, inside a PROC, `step:<job>.<step>.<procstep>` | `step:TRANREPT.STEP05R.PRC001` |
| DD | `dd:<step id without the prefix>.<ddname>` | `dd:POSTTRAN.STEP15.DALYTRAN` |
| Dataset | `dataset:<name>` with names as in `runset.md` (GDG base, `SYSOUT:` names) | `dataset:AWS.M2.CARDDEMO.SYSTRAN` |

Names are upper case. A program that does not compile, or that uses `EXEC CICS`, is still a node. A utility a step runs (`IDCAMS`, `SORT`, `IEBGENER`, `IEFBR14`, `SDSF`) is a program node too.

## Edge kinds

| Kind | From, to |
|---|---|
| `COPY` | program to copybook, or copybook to copybook (nested COPY). One edge per COPY statement target; REPLACING does not change the target. |
| `DECLARES` | copybook to one of its fields |
| `CALL` | program to program (static `CALL 'X'`) |
| `RUNS` | job to step |
| `EXEC_PGM` | step to program, after PROC expansion and symbolic substitution |
| `HAS_DD` | step to DD |
| `DSN` | DD to dataset, after symbolic substitution, with the GDG generation stripped |
| `READS` | step to dataset the step reads |
| `WRITES` | step to dataset the step creates or writes (including `SYSOUT:` names) |

`READS` and `WRITES` are the data-flow edges. A dataset written by one step and read by a later one links the two through the dataset node; that is how impact crosses jobs.
