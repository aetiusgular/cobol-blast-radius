"""A CardDemo-shaped source tree, optionally with a change applied in memory.

The predictor reads the tree twice: as it stands ("before") and with the
change's edits applied ("after"). Nothing here writes to disk.
"""
from pathlib import Path

PROGRAM_EXTS = (".cbl", ".cob")
COPY_EXTS = (".cpy", ".cbl", ".cob", "")


def file_kind(rel):
    """cobol, jcl or ctl, from the folder a member lives in."""
    rel = rel.replace("\\", "/")
    if rel.startswith("app/jcl/") or rel.startswith("app/proc/"):
        return "jcl"
    if rel.startswith("app/ctl/"):
        return "ctl"
    return "cobol"


def member_of(rel):
    """app/cpy/CVACT01Y.cpy -> CVACT01Y."""
    name = rel.replace("\\", "/").rsplit("/", 1)[-1]
    return (name.rsplit(".", 1)[0] if "." in name else name).upper()


def norm_line(kind, line):
    """The part of a line that has meaning, or None for a comment or blank line.

    COBOL: columns 8-72 of a line whose indicator (column 7) is not * or /.
    JCL: columns 1-72 of a line that is not a //* comment.
    Control members: the line without /* ... */ comments.
    """
    line = line.rstrip("\r")
    if kind == "cobol":
        if len(line) >= 7 and line[6] in "*/":
            return None
        ind = line[6] if len(line) >= 7 else " "
        code = line[7:72].rstrip()
        if not code.strip():
            return None
        return ind + code
    if kind == "jcl":
        if line.startswith("//*"):
            return None
        code = line[:72].rstrip()
        return code if code else None
    code = line[:72]
    while "/*" in code:
        a = code.index("/*")
        b = code.find("*/", a + 2)
        code = code[:a] + (code[b + 2:] if b >= 0 else "")
    code = code.strip()
    return code or None


def apply_edits(text, edits, kind):
    """Apply line edits (contracts/change.md) to a text.

    Returns (new_text, before_lines, after_lines, mismatches): the 1-based
    line numbers whose meaning the edits change, in the original text and in
    the edited text. A comment-only or sequence-area-only edit changes no line.
    `mismatches` counts edits whose `before` did not match; they are applied
    anyway, so that a prediction is still made.
    """
    lines = text.split("\n")
    origin = list(range(1, len(lines) + 1))
    touched = [False] * len(lines)
    before = set()
    mismatches = 0
    for e in edits:
        n = e["line"]
        if e["op"] == "replace":
            i = n - 1
            if i < 0 or i >= len(lines):
                mismatches += 1
                continue
            old = lines[i]
            if e.get("before") is not None and old != e["before"]:
                mismatches += 1
            lines[i] = e["after"]
            if norm_line(kind, old) != norm_line(kind, e["after"]):
                touched[i] = True
                if origin[i] is not None:
                    before.add(origin[i])
        else:
            i = max(0, min(n, len(lines)))
            lines.insert(i, e["after"])
            origin.insert(i, None)
            touched.insert(i, norm_line(kind, e["after"]) is not None)
    after = {i + 1 for i, t in enumerate(touched) if t}
    return "\n".join(lines), before, after, mismatches


class Tree:
    """Read-only view of a source tree, with an in-memory overlay of edited files."""

    def __init__(self, root, overlay=None):
        self.root = Path(root)
        self.overlay = dict(overlay or {})
        self._cache = {}

    def read(self, rel):
        rel = rel.replace("\\", "/")
        if rel in self.overlay:
            return self.overlay[rel]
        if rel not in self._cache:
            p = self.root / rel
            inside = p.resolve().is_relative_to(self.root.resolve())
            self._cache[rel] = p.read_text(encoding="utf-8", errors="replace") if inside and p.is_file() else None
        return self._cache[rel]

    def exists(self, rel):
        return self.read(rel) is not None

    def listdir(self, rel_dir):
        """Relative paths of the files in a folder, sorted."""
        d = self.root / rel_dir
        out = set()
        if d.is_dir():
            out |= {f"{rel_dir}/{p.name}" for p in d.iterdir() if p.is_file()}
        out |= {k for k in self.overlay if k.rsplit("/", 1)[0] == rel_dir}
        return sorted(out)

    def find_member(self, dirs, member, exts):
        """The file for a member in the first folder that has it, matching case-insensitively."""
        want = member.upper()
        for d in dirs:
            files = self.listdir(d)
            by_name = {}
            for f in files:
                name = f.rsplit("/", 1)[-1]
                stem, _, ext = name.rpartition(".")
                if not stem:
                    stem, ext = name, ""
                by_name.setdefault((stem.upper(), ("." + ext.lower()) if ext else ""), f)
            for ext in exts:
                hit = by_name.get((want, ext))
                if hit:
                    return hit
        return None
