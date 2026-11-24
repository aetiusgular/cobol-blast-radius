"""Seeded change generator (contracts/change.md, F4).

    generate(cls, seed, root, runset) -> change

Deterministic: the same arguments give the same bytes. Candidates are listed
in a fixed file and line order; random.Random(seed) picks a file among the
class's files, then a candidate in it (the frozen split's builder,
scripts/make-split.py, draws the same way). Targets are only the run set's
programs, the copybooks they COPY (nested COPYs included) and the run set's
job files.

Edits change characters inside columns 8 to 72 of COBOL source and keep each
line's length, or insert a comment line. `compile_break` is decided by
`cobc -fsyntax-only` with the run set's `cobc_flags` on a copy of the tree with
the change applied: true when any run-set program then fails the check.
"""
import random
import re
import shutil
import tempfile
from pathlib import Path

from . import changes as gtchanges
from . import cobol

CLASSES = ("copybook_field", "program_logic", "jcl_step", "noop")


def _lines(path):
    return path.read_bytes().decode("utf-8", "surrogateescape").split("\n")


def _code(line):
    """Columns 8-72 and whether the line is a comment."""
    if len(line) < 7:
        return "", True
    return line[7:72], line[6] in "*/"


def _bump_digit(ch):
    return "8" if ch == "9" else str(int(ch) + 1)


def _bump_char(ch):
    if ch.isdigit():
        return _bump_digit(ch)
    if ch.isalpha():
        return "Y" if ch.upper() == "Z" else chr(ord(ch.upper()) + 1)
    return "X"


def _splice(line, start, new):
    return line[:start] + new + line[start + len(new):]


# ------------------------------------------------------------------ targets
def _programs(root, runset):
    out = []
    for name in runset.get("programs", []):
        p = cobol.find_source(root, runset.get("program_dirs", []), name)
        if p is not None:
            out.append((name.upper(), p))
    return out


def _copy_index(root, runset):
    idx = {}
    for d in runset.get("copy_dirs", []):
        folder = Path(root) / d
        if folder.is_dir():
            for p in sorted(folder.iterdir()):
                if p.is_file():
                    idx.setdefault(p.stem.upper(), p)
    return idx


def _members(root, runset):
    idx = _copy_index(root, runset)
    seen = {}

    def walk(path):
        for line in _lines(path):
            code, comment = _code(line)
            if comment:
                continue
            for m in re.finditer(r"\bCOPY\s+['\"]?([A-Z0-9@#$-]+)", code.upper()):
                name = m.group(1)
                if name in idx and name not in seen:
                    seen[name] = idx[name]
                    walk(idx[name])
    for _, p in _programs(root, runset):
        walk(p)
    return [seen[k] for k in sorted(seen)]


def _rel(root, p):
    return str(Path(p).relative_to(root))


# ------------------------------------------------------------------ candidates
# Each candidate: (file, line, before, after, summary, op)

def _copybook_candidates(root, runset):
    out = []
    for path in _members(root, runset):
        rel = _rel(root, path)
        for i, line in enumerate(_lines(path), start=1):
            code, comment = _code(line)
            if comment or " PIC " not in f" {code} ":
                continue
            name = re.match(r"\s*\d\d\s+([A-Z0-9-]+)", code)
            if not name:
                continue
            m = re.search(r"VALUE\s+(?:'([^']+)'|(\d+))", code)
            if m:
                if m.group(1):
                    pos = 7 + m.end(1) - 1
                    new = _bump_char(line[pos])
                else:
                    pos = 7 + m.end(2) - 1
                    new = _bump_digit(line[pos])
                out.append((rel, i, line, _splice(line, pos, new),
                            f"{path.stem}: {name.group(1)} VALUE literal changed", "replace"))
                continue
            m = re.search(r"PIC\s+S?[X9]\((\d+)\)", code)
            if m and m.group(1)[-1] != "9":
                pos = 7 + m.end(1) - 1
                n = int(m.group(1))
                out.append((rel, i, line, _splice(line, pos, _bump_digit(line[pos])),
                            f"{path.stem}: {name.group(1)} PIC size {n} to {n + 1}", "replace"))
    return out


_LOGIC = [
    (re.compile(r"\bMOVE\s+(\d+)\s+TO\b"), "numeric MOVE literal"),
    (re.compile(r"\bADD\s+(\d+)\s+TO\b"), "ADD literal"),
    (re.compile(r"\b(?:IF|WHEN|UNTIL)\b.*?[=<>]\s*(\d+)\b"), "comparison literal"),
    (re.compile(r"\bCOMPUTE\b.*?[*/+-]\s*(\d+)\b"), "COMPUTE literal"),
    (re.compile(r"\bMOVE\s+'([^']+)'\s+TO\b"), "string MOVE literal"),
    (re.compile(r"\bDISPLAY\s+'([^']+)'"), "DISPLAY literal"),
]


def _logic_candidates(root, runset):
    out = []
    for prog, path in _programs(root, runset):
        rel = _rel(root, path)
        in_proc = False
        for i, line in enumerate(_lines(path), start=1):
            code, comment = _code(line)
            if comment:
                continue
            if "PROCEDURE DIVISION" in code:
                in_proc = True
                continue
            if not in_proc:
                continue
            for rx, what in _LOGIC:
                m = rx.search(code)
                if not m:
                    continue
                lit = m.group(1)
                pos = 7 + m.end(1) - 1
                new = _bump_digit(line[pos]) if lit.isdigit() else _bump_char(line[pos])
                if new == line[pos]:
                    continue
                out.append((rel, i, line, _splice(line, pos, new), f"{prog}: {what} changed", "replace"))
                break
    return out


def _jcl_candidates(root, runset):
    out = []
    for job in runset.get("jobs", []):
        rel = job["file"]
        name = job["job"]
        for i, line in enumerate(_lines(Path(root) / rel), start=1):
            if line.startswith("//*"):
                continue
            body = line[:72]
            m = re.search(r"PARM='(\d+)'", body)
            if m:
                pos = m.end(1) - 1
                out.append((rel, i, line, _splice(line, pos, _bump_digit(line[pos])), f"{name}: PARM changed", "replace"))
                continue
            m = re.search(r"FIELDS=\((?:[A-Z0-9-]+|\d+,\d+,[A-Z]{2}),A[,)]", body)
            if m and "SORT" in body:
                pos = m.end() - 2
                out.append((rel, i, line, _splice(line, pos, "D"), f"{name}: sort order A to D", "replace"))
                continue
            m = re.search(r"C'(\d{4}-\d\d-\d)(\d)'", body)
            if m:
                pos = m.start(2)
                out.append((rel, i, line, _splice(line, pos, _bump_digit(line[pos])), f"{name}: SYMNAMES date changed", "replace"))
                continue
            m = re.search(r"^([A-Z-]+),(\d+),(\d+),(CH|ZD)\s*$", body.rstrip())
            if m:
                pos = m.end(3) - 1
                out.append((rel, i, line, _splice(line, pos, _bump_digit(line[pos])), f"{name}: SYMNAMES length changed", "replace"))
                continue
            m = re.search(r"LRECL=(\d+)", body)
            if m:
                pos = m.end(1) - 1
                out.append((rel, i, line, _splice(line, pos, _bump_digit(line[pos])), f"{name}: DCB LRECL changed", "replace"))
                continue
            m = re.search(r"KEYS\((\d+)[ ,](\d+)\)", body)
            if m:
                pos = m.end(1) - 1
                out.append((rel, i, line, _splice(line, pos, _bump_digit(line[pos])), f"{name}: VSAM key length changed", "replace"))
                continue
            m = re.search(r"COND=\((\d+),LT\)", body)
            if m:
                pos = m.end(1) - 1
                out.append((rel, i, line, _splice(line, pos, _bump_digit(line[pos])), f"{name}: COND code changed", "replace"))
    return out


def _noop_candidates(root, runset):
    out = []
    files = [p for _, p in _programs(root, runset)] + _members(root, runset)
    for path in files:
        rel = _rel(root, path)
        lines = _lines(path)
        for i, line in enumerate(lines, start=1):
            code, comment = _code(line)
            if len(line) >= 7 and line[6] == "*" and code.strip():
                text = line[7:72]
                new_text = ("CHANGED " + text.strip())[: len(text)].ljust(len(text))
                if new_text != text:
                    out.append((rel, i, line, line[:7] + new_text + line[72:], f"{path.stem}: comment text changed", "replace"))
            elif not comment and code.strip().endswith(".") and i < len(lines):
                nxt = lines[i]
                if len(nxt) >= 7 and nxt[6] == "-":
                    continue
                out.append((rel, i, None, "      * reviewed: no functional change",
                            f"{path.stem}: comment line inserted", "insert_after"))
    for job in runset.get("jobs", []):
        rel = job["file"]
        lines = _lines(Path(root) / rel)
        for i, line in enumerate(lines, start=1):
            if i == 1 or i >= len(lines):
                continue
            nxt = lines[i]
            if line.startswith("//") and not line.startswith("//*") and not line[:72].rstrip().endswith(",") \
                    and nxt.startswith("//") and not nxt.startswith("// ") and not nxt.startswith("//*"):
                out.append((rel, i, None, "//* reviewed: no functional change",
                            f"{job['job']}: JCL comment inserted", "insert_after"))
    return out


CANDIDATES = {
    "copybook_field": _copybook_candidates,
    "program_logic": _logic_candidates,
    "jcl_step": _jcl_candidates,
    "noop": _noop_candidates,
}


def candidates(cls, root, runset):
    if cls not in CANDIDATES:
        raise ValueError(f"unknown change class {cls!r}; one of {CLASSES}")
    return CANDIDATES[cls](Path(root), runset)


def compile_break(change, root, runset):
    """True when a run-set program fails `cobc -fsyntax-only` after the change."""
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "root"
        shutil.copytree(root, dst, ignore=shutil.ignore_patterns(".git"))
        gtchanges.apply(change, dst)
        for name, _ in _programs(dst, runset):
            ok, _ = cobol.syntax_ok(dst, runset, name)
            if not ok:
                return True
    return False


def generate(cls, seed, root, runset):
    """One change of class `cls`, the same for the same arguments."""
    root = Path(root)
    pool = candidates(cls, root, runset)
    if not pool:
        raise ValueError(f"no {cls} candidates in the run set")
    rng = random.Random(seed)
    files = sorted({c[0] for c in pool})
    f = files[rng.randrange(len(files))]
    in_file = [c for c in pool if c[0] == f]
    rel, line, before, after, summary, op = in_file[rng.randrange(len(in_file))]
    change = {
        "id": f"G-{cls}-{seed}",
        "class": cls,
        "seed": seed,
        "summary": summary,
        "edits": [{"file": rel, "line": line, "op": op, "before": before, "after": after}],
        "compile_break": None,
    }
    change["compile_break"] = compile_break(change, root, runset)
    return change
