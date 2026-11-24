#!/usr/bin/env python3
"""Build the frozen eval split (contracts/eval.md) from CardDemo at the pinned commit.

    python3 -I scripts/make-split.py [--carddemo vendor/carddemo] [--out contracts/split.jsonl]

P2 ran this once and froze its output; contracts/eval.md holds the hash. It is
kept so a reviewer can rebuild the split and get the same bytes. No later
phase reruns it to change the split.

Deterministic: candidates are enumerated in a fixed file and line order, and
change n of the split is drawn with random.Random(seed), seed = 20261124000 + n:
first a file, then a line in it, among its class's candidates that no earlier
change used. The edits only change characters
inside columns 8 to 72 of COBOL source and keep every line's length, so
sequence areas and continuation columns are untouched.

The split never runs a compiler: whether a change compiles is ground truth's
call (`compile_break` is null for every change here).
"""
import argparse
import json
import random
import re
import sys
from pathlib import Path

MASTER_SEED = 20261124
COUNTS = {"copybook_field": 18, "program_logic": 18, "jcl_step": 12, "noop": 12}
DEV_SHARE = {"copybook_field": 6, "program_logic": 6, "jcl_step": 4, "noop": 4}

REPO = Path(__file__).resolve().parent.parent


def read_lines(path):
    return path.read_bytes().decode("ascii").split("\n")


def cobol_code(line):
    """Columns 8-72 of a fixed-format line, and whether it is a comment."""
    if len(line) < 7:
        return "", True
    indicator = line[6]
    return line[7:72], indicator in "*/"


def program_file(root, name):
    for p in sorted((root / "app/cbl").iterdir()):
        if p.stem.upper() == name:
            return p
    raise SystemExit(f"make-split: no source for {name}")


def copybooks_of(path):
    out = []
    for line in read_lines(path):
        code, comment = cobol_code(line)
        if comment:
            continue
        m = re.search(r"\bCOPY\s+([A-Z0-9]+)", code)
        if m:
            out.append(m.group(1))
    return out


def bump_digit(ch):
    return "8" if ch == "9" else str(int(ch) + 1)


def bump_char(ch):
    if ch.isdigit():
        return bump_digit(ch)
    if ch.isalpha():
        return "Y" if ch.upper() == "Z" else chr(ord(ch.upper()) + 1)
    return "X"


def splice(line, start, end, new):
    assert len(new) == end - start
    return line[:start] + new + line[end:]


# ------------------------------------------------------------ candidates
def copybook_candidates(root, members):
    """PIC size changes and VALUE literal changes on elementary items."""
    out = []
    for member in members:
        path = root / "app/cpy" / f"{member}.cpy"
        rel = f"app/cpy/{path.name}"
        for i, line in enumerate(read_lines(path), start=1):
            code, comment = cobol_code(line)
            if comment or " PIC " not in f" {code} ":
                continue
            name = re.match(r"\s*\d\d\s+([A-Z0-9-]+)", code)
            if not name:
                continue
            m = re.search(r"VALUE\s+(?:'([^']*)'|(\d+))", code)
            if m:
                if m.group(1):
                    lit = m.group(1)
                    pos = 7 + m.start(1) + len(lit) - 1
                    new = bump_char(line[pos])
                else:
                    pos = 7 + m.end(2) - 1
                    new = bump_digit(line[pos])
                out.append((rel, i, line, splice(line, pos, pos + 1, new),
                            f"{member}: {name.group(1)} VALUE literal changed"))
                continue
            m = re.search(r"PIC\s+S?[X9]\((\d+)\)", code)
            if m and m.group(1)[-1] != "9":
                pos = 7 + m.end(1) - 1
                n = int(m.group(1))
                out.append((rel, i, line, splice(line, pos, pos + 1, bump_digit(line[pos])),
                            f"{member}: {name.group(1)} PIC size {n} to {n + 1}"))
    return out


LOGIC_PATTERNS = [
    (re.compile(r"\bMOVE\s+(\d+)\s+TO\b"), "numeric MOVE literal"),
    (re.compile(r"\bADD\s+(\d+)\s+TO\b"), "ADD literal"),
    (re.compile(r"\b(?:IF|WHEN|UNTIL)\b.*?[=<>]\s*(\d+)\b"), "comparison literal"),
    (re.compile(r"\bCOMPUTE\b.*?[*/+-]\s*(\d+)\b"), "COMPUTE literal"),
    (re.compile(r"\bMOVE\s+'([^']+)'\s+TO\b"), "string MOVE literal"),
    (re.compile(r"\bDISPLAY\s+'([^']+)'"), "DISPLAY literal"),
]


def logic_candidates(root, programs):
    out = []
    for prog in programs:
        path = program_file(root, prog)
        rel = f"app/cbl/{path.name}"
        in_proc = False
        for i, line in enumerate(read_lines(path), start=1):
            code, comment = cobol_code(line)
            if comment:
                continue
            if "PROCEDURE DIVISION" in code:
                in_proc = True
                continue
            if not in_proc:
                continue
            for rx, what in LOGIC_PATTERNS:
                m = rx.search(code)
                if not m:
                    continue
                lit = m.group(1)
                pos = 7 + m.end(1) - 1
                new = bump_char(line[pos]) if not lit.isdigit() else bump_digit(line[pos])
                if new == line[pos]:
                    continue
                out.append((rel, i, line, splice(line, pos, pos + 1, new), f"{prog}: {what} changed"))
                break
    return out


def jcl_candidates(root, jobs):
    out = []
    for job in jobs:
        rel = job["file"]
        for i, line in enumerate(read_lines(root / rel), start=1):
            if line.startswith("//*"):
                continue
            body = line[:72]
            m = re.search(r"PARM='(\d+)'", body)
            if m:
                pos = m.end(1) - 1
                out.append((rel, i, line, splice(line, pos, pos + 1, bump_digit(line[pos])), f"{job['job']}: PARM changed"))
                continue
            m = re.search(r"FIELDS=\(([A-Z0-9-]+),A[,)]", body)
            if m and "SORT" in body:
                pos = m.end(1) + 1
                out.append((rel, i, line, splice(line, pos, pos + 1, "D"), f"{job['job']}: sort order A to D"))
                continue
            m = re.search(r"C'(\d{4}-\d\d-\d)(\d)'", body)
            if m:
                pos = m.start(2)
                out.append((rel, i, line, splice(line, pos, pos + 1, bump_digit(line[pos])), f"{job['job']}: SYMNAMES date changed"))
                continue
            m = re.search(r"^([A-Z-]+),(\d+),(\d+),(CH|ZD)\s*$", body.rstrip())
            if m:
                pos = m.end(3) - 1
                out.append((rel, i, line, splice(line, pos, pos + 1, bump_digit(line[pos])), f"{job['job']}: SYMNAMES length changed"))
                continue
            m = re.search(r"LRECL=(\d+)", body)
            if m:
                pos = m.end(1) - 1
                out.append((rel, i, line, splice(line, pos, pos + 1, bump_digit(line[pos])), f"{job['job']}: DCB LRECL changed"))
                continue
            m = re.search(r"KEYS\((\d+)[ ,](\d+)\)", body)
            if m:
                pos = m.end(1) - 1
                out.append((rel, i, line, splice(line, pos, pos + 1, bump_digit(line[pos])), f"{job['job']}: VSAM key length changed"))
                continue
            m = re.search(r"COND=\((\d+),LT\)", body)
            if m:
                pos = m.end(1) - 1
                out.append((rel, i, line, splice(line, pos, pos + 1, bump_digit(line[pos])), f"{job['job']}: COND code changed"))
    return out


def noop_candidates(root, programs, members, jobs):
    """Comment-only edits: rewrite an existing comment line's text, or insert one."""
    out = []
    files = [f"app/cbl/{program_file(root, p).name}" for p in programs]
    files += [f"app/cpy/{m}.cpy" for m in members]
    for rel in files:
        lines = read_lines(root / rel)
        for i, line in enumerate(lines, start=1):
            code, comment = cobol_code(line)
            if len(line) >= 7 and line[6] == "*" and code.strip():
                # rewrite the comment text in place, same length
                text = line[7:72]
                new_text = ("CHANGED " + text.strip())[: len(text)].ljust(len(text))
                if new_text != text:
                    out.append((rel, i, line, line[:7] + new_text + line[72:], f"{Path(rel).stem}: comment text changed", "replace"))
            elif not comment and code.strip().endswith(".") and i < len(lines):
                nxt = lines[i] if i < len(lines) else ""
                if len(nxt) >= 7 and nxt[6] == "-":
                    continue
                out.append((rel, i, None, "      * reviewed: no functional change", f"{Path(rel).stem}: comment line inserted", "insert_after"))
    for job in jobs:
        rel = job["file"]
        lines = read_lines(root / rel)
        for i, line in enumerate(lines, start=1):
            if i == 1 or i >= len(lines):
                continue
            nxt = lines[i]
            # after a complete statement only: this line does not continue, the next starts a new one
            if line.startswith("//") and not line.startswith("//*") and not line[:72].rstrip().endswith(",") \
                    and nxt.startswith("//") and not nxt.startswith("// ") and not nxt.startswith("//*"):
                out.append((rel, i, None, "//* reviewed: no functional change", f"{job['job']}: JCL comment inserted", "insert_after"))
    return out


# ------------------------------------------------------------ build
def draw(seed, cands, used):
    """One change: random.Random(seed) picks a file among the class's files that
    still have unused candidates, then a candidate in that file, so a file with
    many matching lines does not crowd out the rest."""
    pool = [c for c in cands if (c[0], c[1]) not in used]
    if not pool:
        raise SystemExit("make-split: ran out of candidates")
    rng = random.Random(seed)
    files = sorted({c[0] for c in pool})
    f = files[rng.randrange(len(files))]
    in_file = [c for c in pool if c[0] == f]
    c = in_file[rng.randrange(len(in_file))]
    used.add((c[0], c[1]))
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--carddemo", default=str(REPO / "vendor/carddemo"))
    ap.add_argument("--out", default=str(REPO / "contracts/split.jsonl"))
    args = ap.parse_args()
    root = Path(args.carddemo)
    runset = json.loads((REPO / "contracts/runset.json").read_text())
    programs = runset["programs"]
    members = sorted({m for p in programs for m in copybooks_of(program_file(root, p))})
    jobs = runset["jobs"]

    pools = {
        "copybook_field": copybook_candidates(root, members),
        "program_logic": logic_candidates(root, programs),
        "jcl_step": jcl_candidates(root, jobs),
        "noop": noop_candidates(root, programs, members, jobs),
    }
    used = set()
    changes = []
    n = 0
    for cls in COUNTS:
        picks = []
        for _ in range(COUNTS[cls]):
            n += 1
            seed = MASTER_SEED * 1000 + n
            picks.append((n, seed, draw(seed, pools[cls], used)))
        # dev/heldout inside the class, from its own seeded shuffle
        order = list(range(len(picks)))
        random.Random(f"{MASTER_SEED}:{cls}:split").shuffle(order)
        dev = set(order[: DEV_SHARE[cls]])
        for k, (n_k, seed, c) in enumerate(picks):
            op = c[5] if len(c) > 5 else "replace"
            changes.append({
                "id": f"S-{n_k:03d}",
                "class": cls,
                "seed": seed,
                "split": "dev" if k in dev else "heldout",
                "summary": c[4],
                "edits": [{"file": c[0], "line": c[1], "op": op, "before": c[2], "after": c[3]}],
                "compile_break": None,
            })
    with open(args.out, "w", encoding="ascii", newline="\n") as f:
        for ch in changes:
            f.write(json.dumps(ch, sort_keys=True, separators=(",", ":")) + "\n")
    counts = {c: sum(1 for x in changes if x["class"] == c) for c in COUNTS}
    print(f"make-split: {len(changes)} changes, {counts}, pools {({k: len(v) for k, v in pools.items()})}", file=sys.stderr)


if __name__ == "__main__":
    main()
