"""Append-only, hash-chained approval ledger with revert (contracts/ledger.md).

A ledger is a folder: `ledger.jsonl` (one canonical-JSON entry per line) and
`objects/<sha256>` (file contents by hash). No existing line is ever
rewritten. Writes take an exclusive lock on `ledger.lock`, and refuse to
append to a chain that does not verify, so a tampered ledger stays visibly
tampered instead of being extended.
"""
import datetime
import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path

from groundtruth import changes as gtchanges

ZERO = "0" * 64
KINDS = ("approve", "deny", "revert")
FIELDS = ("seq", "ts", "kind", "record", "reverts", "files", "prev_sha256", "entry_sha256")


class LedgerError(Exception):
    pass


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def entry_hash(entry):
    return hashlib.sha256(canonical({k: v for k, v in entry.items() if k != "entry_sha256"})).hexdigest()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _inside(root, rel):
    """The path of `rel` under `root`, refusing anything that resolves outside it."""
    root = Path(root).resolve()
    p = (root / rel).resolve()
    if root not in p.parents:
        raise LedgerError(f"{rel} is outside the tree")
    return p


def _write_restoring(writes):
    """Write {path: bytes}; on an OSError put back what was there and re-raise as LedgerError."""
    old = {p: p.read_bytes() for p in writes}
    done = []
    try:
        for p, data in writes.items():
            p.write_bytes(data)
            done.append(p)
    except OSError as exc:
        for p in done:
            p.write_bytes(old[p])
        raise LedgerError(f"write failed, rolled back: {exc}") from exc


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.file = self.path / "ledger.jsonl"
        self.objects = self.path / "objects"

    # ------------------------------------------------------------ reading
    def _lines(self):
        if not self.file.exists():
            return []
        text = self.file.read_bytes().decode("utf-8")
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        return lines

    def entries(self):
        """Every entry, in file order. Raises LedgerError on a line that is not JSON."""
        out = []
        for n, ln in enumerate(self._lines(), start=1):
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError as exc:
                raise LedgerError(f"line {n} is not JSON: {exc}") from exc
        return out

    def head(self):
        """`entry_sha256` of the last entry, or 64 zeros for an empty ledger."""
        e = self.entries()
        return e[-1]["entry_sha256"] if e else ZERO

    def get(self, seq):
        for e in self.entries():
            if e.get("seq") == seq:
                return e
        raise LedgerError(f"no entry {seq}")

    def object(self, sha):
        data = (self.objects / sha).read_bytes()
        if _sha(data) != sha:
            raise LedgerError(f"object {sha} does not hash to its name")
        return data

    # ------------------------------------------------------------ verify
    def verify(self):
        problems = []

        def bad(seq, msg):
            problems.append({"seq": seq, "problem": msg})

        prev = ZERO
        seen_approve, reverted = set(), set()
        lines = self._lines()
        for n, ln in enumerate(lines, start=1):
            try:
                e = json.loads(ln)
            except json.JSONDecodeError:
                bad(None, f"line {n} is not JSON")
                prev = None
                continue
            if not isinstance(e, dict):
                bad(None, f"line {n} is not an object")
                prev = None
                continue
            seq = e.get("seq") if isinstance(e.get("seq"), int) else None
            if set(e) != set(FIELDS):
                bad(seq, f"line {n}: fields are {sorted(e)}, want {sorted(FIELDS)}")
            if seq != n:
                bad(seq, f"line {n} has seq {e.get('seq')!r}, want {n}")
            if e.get("entry_sha256") != entry_hash(e):
                bad(seq, f"line {n}: entry_sha256 does not match the entry")
            if prev is not None and e.get("prev_sha256") != prev:
                bad(seq, f"line {n}: prev_sha256 does not link to the entry before it")
            if canonical(e).decode("utf-8") != ln:
                bad(seq, f"line {n} is not canonical JSON")
            kind = e.get("kind")
            if kind not in KINDS:
                bad(seq, f"line {n}: unknown kind {kind!r}")
            files = e.get("files") if isinstance(e.get("files"), list) else []
            if kind == "deny" and files:
                bad(seq, f"line {n}: a deny entry wrote files")
            if kind == "approve":
                if (e.get("record") or {}).get("decision", {}).get("decision") == "deny":
                    bad(seq, f"line {n}: an approve entry carries a deny decision")
                seen_approve.add(seq)
            if kind == "revert":
                t = e.get("reverts")
                if t not in seen_approve:
                    bad(seq, f"line {n}: reverts {t!r}, which is not an earlier approve")
                elif t in reverted:
                    bad(seq, f"line {n}: entry {t} was already reverted")
                reverted.add(t)
            for f in files:
                for key in ("before_sha256", "after_sha256"):
                    sha = f.get(key) if isinstance(f, dict) else None
                    p = self.objects / str(sha)
                    if not sha or not p.is_file():
                        bad(seq, f"line {n}: object {sha} is missing")
                    elif _sha(p.read_bytes()) != sha:
                        bad(seq, f"line {n}: object {sha} does not hash to its name")
            prev = e.get("entry_sha256")
        return {"ok": not problems, "problems": problems, "entries": len(lines),
                "head_sha256": prev if lines and prev else ZERO}

    # ------------------------------------------------------------ writing
    @contextmanager
    def _locked(self):
        with open(self.path / "ledger.lock", "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                v = self.verify()
                if not v["ok"]:
                    raise LedgerError(f"ledger does not verify, refusing to append: {v['problems'][:3]}")
                yield self.entries()
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)

    def _store(self, data):
        sha = _sha(data)
        self.objects.mkdir(exist_ok=True)
        p = self.objects / sha
        if not p.exists():
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, p)
        return sha

    def _append(self, entries, kind, record, reverts, files):
        last = entries[-1] if entries else None
        e = {"seq": (last["seq"] + 1) if last else 1, "ts": _now(), "kind": kind, "record": record,
             "reverts": reverts, "files": files, "prev_sha256": last["entry_sha256"] if last else ZERO}
        e["entry_sha256"] = entry_hash(e)
        with open(self.file, "ab") as fh:
            fh.write(canonical(e) + b"\n")
            fh.flush()
            os.fsync(fh.fileno())
        return e

    def approve(self, record, root):
        """Apply `record["change"]` under `root` and append an approve entry. Refuses a deny decision."""
        if (record.get("decision") or {}).get("decision") == "deny":
            raise LedgerError("a deny decision is recorded with deny(), never applied")
        root = Path(root)
        change = record["change"]
        with self._locked() as entries:
            rels = sorted({e["file"] for e in change.get("edits") or []})
            before = {}
            for rel in rels:
                p = _inside(root, rel)
                if not p.is_file():
                    raise LedgerError(f"{rel} does not exist")
                before[rel] = p.read_bytes()
            for data in before.values():
                self._store(data)
            try:
                gtchanges.apply(change, root)
            except gtchanges.ApplyError as exc:
                raise LedgerError(f"change does not apply: {exc}") from exc
            try:
                files = []
                for rel in rels:
                    after = _inside(root, rel).read_bytes()
                    files.append({"path": rel, "before_sha256": self._store(before[rel]),
                                  "after_sha256": self._store(after)})
                return self._append(entries, "approve", record, None, files)
            except BaseException:
                _write_restoring({_inside(root, rel): data for rel, data in before.items()})
                raise

    def deny(self, record):
        """Append a deny entry. No file is touched."""
        with self._locked() as entries:
            return self._append(entries, "deny", record, None, [])

    def revert(self, seq, root):
        """Restore every file entry `seq` wrote, byte for byte, and append a revert entry."""
        root = Path(root)
        with self._locked() as entries:
            target = next((e for e in entries if e["seq"] == seq), None)
            if target is None:
                raise LedgerError(f"no entry {seq}")
            if target["kind"] != "approve":
                raise LedgerError(f"entry {seq} is a {target['kind']}, only an approve can be reverted")
            if any(e["kind"] == "revert" and e["reverts"] == seq for e in entries):
                raise LedgerError(f"entry {seq} was already reverted")
            writes, files = {}, []
            for f in target["files"]:
                p = _inside(root, f["path"])
                cur = p.read_bytes() if p.is_file() else None
                if cur is None or _sha(cur) != f["after_sha256"]:
                    raise LedgerError(f"{f['path']} changed since entry {seq}; nothing was written")
                writes[p] = self.object(f["before_sha256"])
                files.append({"path": f["path"], "before_sha256": f["after_sha256"],
                              "after_sha256": f["before_sha256"]})
            _write_restoring(writes)
            try:
                return self._append(entries, "revert", None, seq, files)
            except BaseException:
                _write_restoring({_inside(root, f["path"]): self.object(f["after_sha256"])
                                  for f in target["files"]})
                raise
