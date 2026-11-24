"""The dataset catalog the step runner keeps for one harness run.

Kinds: `ps` (sequential file), `gdg` (a generation data group base; each
generation is a `ps` entry named <base>.GnnnnV00), `ksds` (an indexed file,
GnuCOBOL with Berkeley DB, standing in for a VSAM KSDS), `aix` (an alternate
index over a ksds), `path` (a name for an aix).

Output names and canonical bytes follow contracts/runset.md.
"""
import hashlib
import re
from pathlib import Path

GDG_REF = re.compile(r"^(.+)\(([+-]?\d+)\)$")
MEMBER_REF = re.compile(r"^(.+)\(([A-Z0-9@#$]{1,8})\)$")
GEN_NAME = re.compile(r"^(.+)\.G(\d{4})V00$")


class Unsupported(Exception):
    """A statement outside the step-runner subset."""


class Catalog:
    def __init__(self, dsdir, toolchain):
        self.dir = Path(dsdir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.tc = toolchain
        self.e = {}

    # ---------------------------------------------------------- names
    def file_for(self, name):
        return self.dir / name

    def gen_name(self, base, n):
        return f"{base}.G{n:04d}V00"

    def output_name(self, name):
        """Fold a dataset name into the name it is scored under."""
        m = GEN_NAME.match(name)
        if m and self.e.get(m.group(1), {}).get("kind") == "gdg":
            return m.group(1)
        ent = self.e.get(name)
        if ent and ent["kind"] == "path":
            return ent["entry"]
        for suffix in (".DATA", ".INDEX"):
            if name.endswith(suffix):
                parent = name[: -len(suffix)]
                if parent in self.e and self.e[parent]["kind"] in ("ksds", "aix"):
                    return parent
                if parent.endswith(".PATH"):
                    continue
        if name.endswith(".PATH") and self.e.get(name, {}).get("kind") == "path":
            return self.e[name]["entry"]
        return name

    def exists(self, name):
        return name in self.e

    # ---------------------------------------------------------- ps
    def new_ps(self, name, lrecl=None, recfm=None):
        p = self.file_for(name)
        p.write_bytes(b"")
        self.e[name] = {"kind": "ps", "path": p, "lrecl": lrecl, "recfm": recfm}
        return self.e[name]

    def delete(self, name):
        ent = self.e.pop(name, None)
        if ent is None:
            return False
        kind = ent["kind"]
        if kind == "ps":
            ent["path"].unlink(missing_ok=True)
        elif kind == "ksds":
            for p in self.dir.glob(ent["path"].name + "*"):
                p.unlink()
            for n, x in list(self.e.items()):
                if x["kind"] == "aix" and x["relate"] == name:
                    self.delete(n)
        elif kind == "aix":
            for n, x in list(self.e.items()):
                if x["kind"] == "path" and x["entry"] == name:
                    self.e.pop(n)
            base = self.e.get(ent["relate"])
            if base and ent.get("built"):
                ent["built"] = False
                self.e[name] = ent
                recs = self.ksds_records(ent["relate"])
                self.e.pop(name)
                self._reshape(ent["relate"], recs)
        elif kind == "gdg":
            for g in ent["gens"]:
                self.delete(self.gen_name(name, g))
        return True

    # ---------------------------------------------------------- gdg
    def define_gdg(self, name, limit, scratch):
        self.e[name] = {"kind": "gdg", "limit": limit, "scratch": scratch, "gens": []}

    def gdg_roll_in(self, base, n):
        g = self.e[base]
        if n not in g["gens"]:
            g["gens"].append(n)
            g["gens"].sort()
        while len(g["gens"]) > g["limit"]:
            old = g["gens"].pop(0)
            gname = self.gen_name(base, old)
            if g["scratch"]:
                self.delete(gname)
            else:
                self.e.pop(gname, None)

    # ---------------------------------------------------------- ksds / aix
    def alts_of(self, name):
        out = []
        for n in sorted(self.e):
            x = self.e[n]
            if x["kind"] == "aix" and x["relate"] == name and x.get("built"):
                out.append((x["key"][0], x["key"][1], x["dups"]))
        return out

    def define_ksds(self, name, recsize, key):
        p = self.file_for(name)
        for old in self.dir.glob(p.name + "*"):
            old.unlink()
        rc, _, _, out = self.tc.run_loader(recsize, key, [], "CREATE", p)
        if rc != 0:
            raise RuntimeError(f"could not create {name}: {out}")
        self.e[name] = {"kind": "ksds", "path": p, "recsize": recsize, "key": tuple(key)}

    def define_aix(self, name, relate, key, dups):
        self.e[name] = {"kind": "aix", "relate": relate, "key": tuple(key), "dups": dups, "built": False}

    def define_path(self, name, entry):
        self.e[name] = {"kind": "path", "entry": entry}

    def build_aix(self, name):
        ent = self.e[name]
        recs = self.ksds_records(ent["relate"])
        ent["built"] = True
        self._reshape(ent["relate"], recs)

    def _reshape(self, cluster, recs):
        """Rebuild a cluster's indexed file (holding `recs`) so its alternate keys match its built AIXs."""
        ent = self.e[cluster]
        p = ent["path"]
        for old in self.dir.glob(p.name + "*"):
            old.unlink()
        alts = self.alts_of(cluster)
        rc, _, _, out = self.tc.run_loader(ent["recsize"], ent["key"], alts, "CREATE", p)
        if rc != 0:
            raise RuntimeError(f"could not rebuild {cluster}: {out}")
        if recs:
            self.ksds_load(cluster, recs)

    def ksds_records(self, name):
        ent = self.e[name]
        tmp = self.dir.parent / "tmp-unload"
        rc, n, _, out = self.tc.run_loader(ent["recsize"], ent["key"], self.alts_of(name), "UNLOAD",
                                           ent["path"], tmp)
        if rc != 0:
            raise RuntimeError(f"could not unload {name}: {out}")
        data = tmp.read_bytes() if tmp.exists() else b""
        tmp.unlink(missing_ok=True)
        size = ent["recsize"]
        return [data[i:i + size] for i in range(0, len(data), size)]

    def ksds_load(self, name, recs):
        """Write records into a ksds by key. Returns (written, refused)."""
        ent = self.e[name]
        size = ent["recsize"]
        tmp = self.dir.parent / "tmp-load"
        tmp.write_bytes(b"".join(r[:size].ljust(size, b" ") for r in recs))
        rc, n, bad, out = self.tc.run_loader(size, ent["key"], self.alts_of(name), "LOAD", ent["path"], tmp)
        tmp.unlink(missing_ok=True)
        if rc not in (0, 8):
            raise RuntimeError(f"could not load {name}: {out}")
        return n, bad

    # ---------------------------------------------------------- records
    def records(self, name):
        """The records of a dataset, in order (key order for indexed files)."""
        ent = self.e[name]
        if ent["kind"] == "ps":
            data = ent["path"].read_bytes()
            lrecl = ent.get("lrecl")
            recfm = (ent.get("recfm") or "F").upper()
            if not lrecl or not recfm.startswith("F"):
                raise Unsupported(f"{name}: records need a fixed LRECL (have {recfm} {lrecl})")
            return [data[i:i + lrecl] for i in range(0, len(data), lrecl)]
        if ent["kind"] == "ksds":
            return self.ksds_records(name)
        if ent["kind"] == "path":
            return self.records(ent["entry"])
        if ent["kind"] == "aix":
            return self.aix_records(name)
        raise Unsupported(f"{name}: cannot read records of a {ent['kind']}")

    def lrecl(self, name):
        ent = self.e.get(name) or {}
        if ent.get("kind") == "ps":
            return ent.get("lrecl")
        if ent.get("kind") == "ksds":
            return ent["recsize"]
        if ent.get("kind") == "path":
            return self.lrecl(ent["entry"])
        return None

    def aix_records(self, name):
        ent = self.e[name]
        base = self.e[ent["relate"]]
        off, ln = ent["key"]
        po, pl = base["key"]
        recs = self.ksds_records(ent["relate"])
        return sorted(recs, key=lambda r: (r[off:off + ln], r[po:po + pl]))

    # ---------------------------------------------------------- canonical bytes
    def canonical(self, name):
        """(sha256, bytes, generations) of an output name, or None when absent."""
        ent = self.e.get(name)
        if ent is None:
            return None
        if ent["kind"] == "ps":
            data = ent["path"].read_bytes()
            return hashlib.sha256(data).hexdigest(), len(data), 1
        if ent["kind"] == "gdg":
            h = hashlib.sha256()
            total = 0
            for g in ent["gens"]:
                gdata = self.e[self.gen_name(name, g)]["path"].read_bytes()
                total += len(gdata)
                h.update(f"G{g:04d}V00\0{hashlib.sha256(gdata).hexdigest()}\n".encode())
            return h.hexdigest(), total, len(ent["gens"])
        if ent["kind"] in ("ksds", "aix"):
            data = b"".join(self.records(name))
            return hashlib.sha256(data).hexdigest(), len(data), 1
        if ent["kind"] == "path":
            return self.canonical(ent["entry"])
        return None

    def signature(self, name):
        """A cheap fingerprint of a dataset's files, to see whether a step wrote it."""
        ent = self.e.get(name)
        if ent is None:
            return None
        if ent["kind"] == "ps":
            p = ent["path"]
            return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
        if ent["kind"] == "ksds":
            h = hashlib.sha256()
            for p in sorted(self.dir.glob(ent["path"].name + "*")):
                h.update(p.name.encode() + b"\0" + p.read_bytes())
            return h.hexdigest()
        if ent["kind"] == "path":
            return self.signature(self.e[ent["entry"]]["relate"])
        return repr(sorted(ent.items()))
