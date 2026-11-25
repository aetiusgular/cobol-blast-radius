#!/usr/bin/env python3
"""P4 probe for RFI-P3a-1 (-fsign=EBCDIC) and RFI-P3a-2 (clock in TRANREPT's window).

    python3 scripts/p4-runset-probe.py results/P4-runset-rfi.jsonl [workdir]

Runs the CardDemo baseline (no change, so no split row is touched) under the
run set before P4 and after it, plus each RFI alone, and appends one row per
configuration: POSTTRAN's reject count and reasons (DALYREJS, reason code at
offset 350 of each 430-byte record), and the bytes of TRANSACT.DALY and
TRANREPT. A probe of the grader's configuration, not an eval: no prediction
is scored.
"""
import collections
import copy
import datetime
import json
import sys
import tempfile
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from approval.evalrun import cobc_version, git_state, machine  # noqa: E402
from groundtruth import harness  # noqa: E402

BEFORE = {"clock": "2022/07/18 10:00:00", "cobc_flags": ["-std=ibm"]}
CONFIGS = [
    ("before-P4", {}),
    ("fsign-only", {"cobc_flags": ["-std=ibm", "-fsign=EBCDIC"]}),
    ("clock-only", {"clock": "2022/07/01 10:00:00.00"}),
    ("after-P4", None),  # contracts/runset.json as committed
]
LRECL, REASON = 430, slice(350, 354)


def rejects(ds):
    data = b"".join(p.read_bytes() for p in sorted(ds.glob("AWS.M2.CARDDEMO.DALYREJS*")))
    recs = [r for r in data.split(b"\n") if r] if b"\n" in data else \
        [data[i:i + LRECL] for i in range(0, len(data), LRECL)]
    return len(recs), dict(collections.Counter(r[REASON].decode("latin-1") for r in recs))


def main():
    out = Path(sys.argv[1])
    work = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(tempfile.mkdtemp(prefix="cbr-p4-"))
    committed = json.loads((REPO / "contracts/runset.json").read_text())
    root = REPO / "vendor/carddemo"
    daily = len((root / "app/data/ASCII/dailytran.txt").read_text().splitlines())
    date = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    sha, dirty = git_state()
    run_id = f"P4-runset-rfi-{date[:10]}-{uuid.uuid4().hex[:8]}"
    rows = []
    for name, over in CONFIGS:
        rs = committed if over is None else {**copy.deepcopy(committed), **BEFORE, **over}
        r = harness.run(root, rs, work / name)
        n, reasons = rejects(work / name / "ds")
        o = r["outputs"]
        rows.append({
            "run_id": run_id, "git_sha": sha, "git_dirty": dirty, "machine": machine(),
            "model_revision": None, "quant": None, "runtime": None, "date": date,
            "phase": "P4", "kind": "grader configuration probe, not an eval",
            "config": name, "clock": rs["clock"], "cobc_flags": rs["cobc_flags"],
            "carddemo_commit": rs["carddemo_commit"], "cobc_version": cobc_version(),
            "all_programs_built": all(v["ok"] for v in r["compile"].values()),
            "steps_not_ok": [f"{s['job']}.{s['step']}:{s['status']}" for s in r["steps"]
                             if s["status"] not in ("ok", "skipped")],
            "daily_transactions": daily, "posttran_rejects": n, "reject_reasons": reasons,
            "transact_daly_bytes": o.get("AWS.M2.CARDDEMO.TRANSACT.DALY", {}).get("bytes"),
            "tranrept_bytes": o.get("AWS.M2.CARDDEMO.TRANREPT", {}).get("bytes"),
            "outputs": len(o), "empty_outputs": sorted(k for k, v in o.items() if not v["bytes"]),
        })
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "a") as fh:
        fh.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    print(json.dumps([{k: r[k] for k in ("config", "posttran_rejects", "transact_daly_bytes", "tranrept_bytes")}
                      for r in rows], indent=1))


if __name__ == "__main__":
    main()
