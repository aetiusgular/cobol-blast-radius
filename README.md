# cobol-blast-radius

The blast radius of a COBOL change, checked against compiled golden outputs.

Built in phases with the forge method. P1 (research and spec) is merged: `SPEC.md` states the build and its headline number, blast-radius recall against GnuCOBOL output diffs on CardDemo, and `research/P1.md` has the sources. P2 (the base) is merged: `contracts/` holds the seams and the frozen 60-change split, `fixtures/` a small CardDemo-shaped app, and `tests/red/` one failing test per corner case per lane. P3a (the ground-truth harness and the seeded-change generator, `groundtruth/`) is merged; `groundtruth/README.md` says how it runs CardDemo's batch jobs under GnuCOBOL and where it can differ from z/OS. P3b (the graph and the blast-radius predictor, `radius/`) is merged; `radius/README.md` says how the static prediction is made and where it over-reports. P3c (the allowlist, the hash-chained approval ledger with revert, the eval runner and the CLI, `approval/`) is in review; `approval/README.md` says what each command does and what the ledger cannot catch on its own. No eval has run yet.

Set up with `bash scripts/setup.sh` (GnuCOBOL 3.2 and CardDemo at its pinned commit), then `bash scripts/test.sh` and `bash scripts/forge-gate.sh <phase>`.
