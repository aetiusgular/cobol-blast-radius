# cobol-blast-radius

The blast radius of a COBOL change, checked against compiled golden outputs.

Built in phases with the forge method. P1 (research and spec) is merged: `SPEC.md` states the build and its headline number, blast-radius recall against GnuCOBOL output diffs on CardDemo, and `research/P1.md` has the sources. P2 (the base) is merged: `contracts/` holds the seams and the frozen 60-change split, `fixtures/` a small CardDemo-shaped app, and `tests/red/` one failing test per corner case per lane. P3a (the ground-truth harness and the seeded-change generator, `groundtruth/`) is in review; `groundtruth/README.md` says how it runs CardDemo's batch jobs under GnuCOBOL and where it can differ from z/OS. No eval has run yet.

Set up with `bash scripts/setup.sh` (GnuCOBOL 3.2 and CardDemo at its pinned commit), then `bash scripts/test.sh` and `bash scripts/forge-gate.sh <phase>`.
