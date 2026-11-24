#!/usr/bin/env python3
"""Lane isolation (contracts/seams.md, written in P2): radius never imports
groundtruth or approval; groundtruth never imports radius or approval; and
nothing under radius/ names a heldout change id or the word "heldout", so
it cannot select heldout rows from the split (contracts/eval.md rule 1)."""
import ast
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FORBIDDEN = {"radius": {"groundtruth", "approval"}, "groundtruth": {"radius", "approval"}}
fails = []

for pkg, banned in FORBIDDEN.items():
    for p in sorted((REPO / pkg).rglob("*.py")):
        tree = ast.parse(p.read_text(), str(p))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            elif isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in ("import_module", "__import__"):
                names = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            for n in names:
                if n.split(".")[0] in banned:
                    fails.append(f"{p.relative_to(REPO)}:{node.lineno} imports {n}")

heldout = {json.loads(ln)["id"] for ln in (REPO / "contracts/split.jsonl").read_text().splitlines()
           if json.loads(ln)["split"] == "heldout"}
for p in sorted((REPO / "radius").rglob("*")):
    if p.is_file() and "__pycache__" not in p.parts:
        text = p.read_text(errors="replace")
        for m in set(re.findall(r"S-\d{3}", text)) & heldout:
            fails.append(f"{p.relative_to(REPO)} names heldout change {m}")
        if re.search(r"heldout", text, re.IGNORECASE):
            fails.append(f"{p.relative_to(REPO)} names the heldout split (radius reads dev rows only)")

if fails:
    for f in fails:
        print("FAIL", f)
    sys.exit(1)
print("check-isolation: ok")
