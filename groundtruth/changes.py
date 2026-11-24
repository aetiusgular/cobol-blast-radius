"""Apply a change to a source tree, all or nothing (contracts/change.md).

A file is split on "\\n"; a line keeps any "\\r" before its "\\n", and every
other byte of the file (including a missing final newline) is kept. Files are
decoded as UTF-8 with surrogateescape, so bytes that are not UTF-8 survive.
"""
from pathlib import Path


class ApplyError(Exception):
    pass


def _lines(data):
    return data.decode("utf-8", "surrogateescape").split("\n")


def _bytes(lines):
    return "\n".join(lines).encode("utf-8", "surrogateescape")


def plan(change, root):
    """Return {relative path: new bytes} for the change, or raise ApplyError.

    Nothing is written. Edits apply in order, each against the file as it
    stands after the edits before it.
    """
    root = Path(root)
    state = {}
    for n, e in enumerate(change.get("edits") or [], start=1):
        rel = e["file"]
        path = (root / rel).resolve()
        if root.resolve() not in path.parents:
            raise ApplyError(f"edit {n}: {rel} is outside the tree")
        if rel not in state:
            if not path.is_file():
                raise ApplyError(f"edit {n}: {rel} does not exist")
            state[rel] = _lines(path.read_bytes())
        lines = state[rel]
        line, op = e["line"], e["op"]
        if op == "replace":
            if not 1 <= line <= len(lines):
                raise ApplyError(f"edit {n}: {rel} line {line} is past the end ({len(lines)} lines)")
            if lines[line - 1] != e["before"]:
                raise ApplyError(f"edit {n}: {rel} line {line} does not match: "
                                 f"want {e['before']!r}, have {lines[line - 1]!r}")
            lines[line - 1] = e["after"]
        elif op == "insert_after":
            if e.get("before") is not None:
                raise ApplyError(f"edit {n}: insert_after needs before = null")
            if not 0 <= line <= len(lines):
                raise ApplyError(f"edit {n}: {rel} line {line} is past the end ({len(lines)} lines)")
            lines.insert(line, e["after"])
        else:
            raise ApplyError(f"edit {n}: unknown op {op!r}")
    return {rel: _bytes(lines) for rel, lines in state.items()}


def apply(change, root):
    """Apply `change` in place under `root`. Raises ApplyError and writes nothing on any mismatch."""
    new = plan(change, root)
    root = Path(root)
    old = {rel: (root / rel).read_bytes() for rel in new}
    done = []
    try:
        for rel, data in new.items():
            (root / rel).write_bytes(data)
            done.append(rel)
    except OSError as exc:
        for rel in done:
            (root / rel).write_bytes(old[rel])
        raise ApplyError(f"write failed, rolled back: {exc}") from exc
    return sorted(new)
