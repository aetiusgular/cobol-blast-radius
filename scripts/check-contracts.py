#!/usr/bin/env python3
"""Contract checks scripts/test.sh runs in every phase (written in P2).

- every contracts/*.json parses;
- contracts/split.jsonl: 60 rows that pass change.schema.json, ids S-001..S-060,
  the class and split counts eval.md states, and (when vendor/carddemo is
  present) every `before` line matches CardDemo at the pinned commit;
- fixtures/mini/changes/*.json pass the schema and match the fixture tree;
- every job file in CardDemo's app/jcl is in runset.json's jobs or excluded_jobs;
- every run set pins its cobc dialect in cobc_flags.
"""
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from tests.red._support import schema_errors  # noqa: E402

fails = []


def check(ok, msg):
    if not ok:
        fails.append(msg)


def lines_of(path):
    return path.read_bytes().decode("ascii", errors="replace").split("\n")


def check_change(ch, root, where):
    errs = schema_errors(ch, json.loads((REPO / "contracts/change.schema.json").read_text()))
    check(not errs, f"{where}: {errs[:3]}")
    if root is None:
        return
    for e in ch.get("edits", []):
        p = root / e["file"]
        if not p.is_file():
            fails.append(f"{where}: {e['file']} missing under {root}")
            continue
        lines = lines_of(p)
        if e["op"] == "replace":
            check(0 < e["line"] <= len(lines) and lines[e["line"] - 1] == e["before"],
                  f"{where}: line {e['line']} of {e['file']} is not `before`")
        else:
            check(e["before"] is None and 0 <= e["line"] <= len(lines), f"{where}: bad insert_after")


for p in sorted((REPO / "contracts").glob("*.json")):
    try:
        json.loads(p.read_text())
    except ValueError as exc:
        fails.append(f"{p.name}: {exc}")

carddemo = REPO / "vendor/carddemo"
cd_root = carddemo if (carddemo / "app/cbl").is_dir() else None
if cd_root is None:
    print("check-contracts: vendor/carddemo missing, split lines not checked against CardDemo (run scripts/setup.sh)")

rows = [json.loads(ln) for ln in (REPO / "contracts/split.jsonl").read_text().splitlines()]
check(len(rows) == 60, f"split has {len(rows)} rows, eval.md says 60")
check([r["id"] for r in rows] == [f"S-{i:03d}" for i in range(1, 61)], "split ids are not S-001..S-060 in order")
for r in rows:
    check_change(r, cd_root, f"split {r.get('id')}")
    check(r.get("split") in ("dev", "heldout"), f"split {r.get('id')}: no split field")
want = {("copybook_field", "dev"): 6, ("copybook_field", "heldout"): 12,
        ("program_logic", "dev"): 6, ("program_logic", "heldout"): 12,
        ("jcl_step", "dev"): 4, ("jcl_step", "heldout"): 8,
        ("noop", "dev"): 4, ("noop", "heldout"): 8}
got = Counter((r["class"], r["split"]) for r in rows)
check(dict(got) == want, f"split counts {dict(got)} differ from eval.md {want}")

for p in sorted((REPO / "fixtures/mini/changes").glob("*.json")):
    check_change(json.loads(p.read_text()), REPO / "fixtures/mini", f"fixture {p.name}")

runset = json.loads((REPO / "contracts/runset.json").read_text())
for name, rs in (("contracts/runset.json", runset),
                 ("fixtures/mini/runset.json", json.loads((REPO / "fixtures/mini/runset.json").read_text())),
                 ("fixtures/mini/runset-ebcdic.json", json.loads((REPO / "fixtures/mini/runset-ebcdic.json").read_text()))):
    flags = rs.get("cobc_flags")
    check(isinstance(flags, list) and flags and all(isinstance(f, str) and f.startswith("-std=") for f in flags),
          f"{name}: cobc_flags must be a non-empty list of -std= dialect flags (runset.md)")
if cd_root is not None:
    named = {j["job"] for j in runset["jobs"]} | {j["job"] for j in runset["excluded_jobs"]}
    on_disk = {p.stem.upper() for p in (cd_root / "app/jcl").iterdir()}
    check(named == on_disk, f"runset jobs+excluded {sorted(named ^ on_disk)} differ from app/jcl")
    for j in runset["jobs"]:
        check((cd_root / j["file"]).is_file(), f"runset job file {j['file']} missing")
    for i in runset["inputs"]:
        base = REPO if i.get("from") == "repo" else cd_root
        check((base / i["path"]).is_file(), f"runset input {i['path']} missing")

if fails:
    for f in fails:
        print("FAIL", f)
    sys.exit(1)
print(f"check-contracts: ok ({len(rows)} split rows)")
