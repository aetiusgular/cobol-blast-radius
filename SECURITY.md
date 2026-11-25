# Security

Open items, rendered into the README in P6. Severity: high, medium, low.

| ID | Severity | Item | Owner | Workaround | Status |
|---|---|---|---|---|---|
| T-1 | low | `ci` runs the PR's own copy of `ci.yml`, so a PR that edits it could post statuses with the workflow token. | Tony | `forge/guard` (base copy) fails any PR that touches `.github/`, and review reads the diff. | open |
| T-2 | low | gitleaks honours inline `gitleaks:allow` comments; a PR could mark a line as allowed. | Tony | Review greps the diff for `gitleaks:allow`. | open |
| T-3 | low | Under the box's `landlock` profile, TCP rules name ports, not addresses: the model port and the proxy (ephemeral) port range are open to any host, not only 127.0.0.1. | Tony | Only for projects with `eval_boundary: landlock`; the box's nftables rules and the proxies' own allowlists still apply. | open |
| G-1 | medium | The ground-truth harness (`groundtruth/harness.py`) compiles and runs the COBOL programs of the tree it is given, with a change applied, as the calling user, with no sandbox. Its environment drops `COB_*` and `DD_*` variables but keeps the rest (`PATH`, `HOME`). A change from outside the frozen split or the generator could run arbitrary code through a COBOL program. | P4 | Run the harness only on the frozen split and generator output. The P5 box runs evals inside srt with no network but the model endpoint. P4 decides whether `approval/` may call the harness on user-proposed changes. | open |
| G-2 | low | A changed program that loops while writing can fill the disk before the per-step timeout ends it. The harness caps time per step, not output size. | P4 | Run in a work folder on a disk with headroom; the box sandbox limits apply in P5. | open |
| R-1 | low | The predictor (`radius/`) parses the edited text of a proposed change in memory. It runs nothing and opens no network connection, but a crafted source can make it slow or large: COPY nesting is capped at 12 levels, but a huge OCCURS count gives a large bitmask, and the fixed-point loop is capped at 200 rounds per program. | P4 | Predict only on the frozen split and generator output until P4 adds input limits for user-proposed changes. | open |
