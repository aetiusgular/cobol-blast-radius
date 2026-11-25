"""Parse a CardDemo-shaped tree into the dependency graph (contracts/graph.md)."""
from dataclasses import dataclass, field

from radius import cobol, jcl
from radius.source import PROGRAM_EXTS, Tree, member_of

DEFAULT_COPY_DIRS = ["app/cpy"]
DEFAULT_PROGRAM_DIRS = ["app/cbl"]
SKIP_DDS = {"STEPLIB", "JOBLIB", "SYSABEND", "SYSUDUMP", "CEEDUMP"}


@dataclass
class Graph:
    nodes: set = field(default_factory=set)
    edges: set = field(default_factory=set)
    errors: list = field(default_factory=list)

    def node(self, n):
        self.nodes.add(n)
        return n

    def edge(self, a, kind, b):
        self.nodes.add(a)
        self.nodes.add(b)
        self.edges.add((a, kind, b))


class World:
    """Programs and jobs of one tree, parsed once. The predictor builds one per side of a change."""

    def __init__(self, tree, runset=None):
        runset = runset or {}
        self.tree = tree
        self.copy_dirs = list(runset.get("copy_dirs") or DEFAULT_COPY_DIRS)
        self.program_dirs = list(runset.get("program_dirs") or DEFAULT_PROGRAM_DIRS)
        self.reader = jcl.JclReader(tree, runset.get("libraries"))
        self.errors = []
        self._programs = {}
        self.program_files = {}
        for d in self.program_dirs:
            for rel in tree.listdir(d):
                if rel.lower().endswith(PROGRAM_EXTS):
                    self.program_files.setdefault(member_of(rel), rel)
        self._jobs = {}
        self.aliases = None

    # -------------------------------------------------- programs
    def program(self, name):
        """The parsed program for a member name, or None when there is no source for it."""
        name = name.upper()
        if name not in self._programs:
            rel = self.program_files.get(name)
            prog = None
            if rel:
                try:
                    prog = cobol.Program(self.tree, rel, self.copy_dirs)
                    self.errors.extend(prog.errors)
                except Exception as exc:  # reported in graph.errors, never hidden
                    self.errors.append(f"{rel}: {exc!r}")
            self._programs[name] = prog
        return self._programs[name]

    def programs(self):
        return {m: self.program(m) for m in sorted(self.program_files)}

    # -------------------------------------------------- jobs
    def job(self, rel):
        if rel not in self._jobs:
            try:
                self._jobs[rel] = self.reader.read_job(rel)
            except Exception as exc:
                self.errors.append(f"{rel}: {exc!r}")
                self._jobs[rel] = None
        return self._jobs[rel]

    def all_job_files(self):
        return [r for r in self.tree.listdir("app/jcl") if r.lower().endswith((".jcl", ".jcl"))]

    def _alias_map(self, job_files):
        if self.aliases is None:
            self.aliases = {}
            for rel in job_files:
                j = self.job(rel)
                for st in (j.steps if j else []):
                    if st.pgm == "IDCAMS":
                        _, _, al = jcl.idcams_io(self.tree, st)
                        self.aliases.update(al)
        return self.aliases

    def canon(self, name):
        """Fold VSAM .DATA, .INDEX and .PATH component names into their cluster or AIX."""
        if name is None:
            return None
        al = self.aliases or {}
        seen = 0
        while name in al and seen < 4:
            name = al[name]
            seen += 1
        for suf in (".DATA", ".INDEX", ".PATH"):
            if name.endswith(suf) and name[: -len(suf)] in self._defined():
                return name[: -len(suf)]
        return name

    def _defined(self):
        if not hasattr(self, "_defined_set"):
            self._defined_set = set((self.aliases or {}).values())
            for rel in list(self._jobs):
                j = self._jobs[rel]
                for st in (j.steps if j else []):
                    if st.pgm == "IDCAMS":
                        _, w, _ = jcl.idcams_io(self.tree, st)
                        self._defined_set |= set(w)
        return self._defined_set

    def prepare(self, job_files):
        for rel in job_files:
            self.job(rel)
        self._alias_map(job_files)
        if hasattr(self, "_defined_set"):
            del self._defined_set

    # -------------------------------------------------- step I/O
    def step_io(self, st):
        """(reads, writes): lists of (dataset, dd name) for a step, names canonical."""
        reads, writes = [], []
        c = self.canon
        p = st.pgm
        if p == "IDCAMS":
            r, w, _ = jcl.idcams_io(self.tree, st)
            dd_of = {}
            for dn, d in st.dds.items():
                for x in d.dsns:
                    dd_of.setdefault(x, dn)
            reads = [(c(x), dd_of.get(x, "SYSIN")) for x in r]
            writes = [(c(x), dd_of.get(x, "")) for x in w]
        elif p in ("SORT", "ICEMAN", "SYNCSORT"):
            for dn, d in st.dds.items():
                if dn == "SORTIN" or dn.startswith("SORTIN"):
                    reads += [(c(x), dn) for x in d.dsns]
                elif dn == "SORTOUT" or dn.startswith("SORTOF") or dn.startswith("OUT"):
                    writes += [(c(x), dn) for x in d.dsns]
        elif p in ("IEBGENER", "ICEGENER"):
            for dn, d in st.dds.items():
                if dn == "SYSUT1":
                    reads += [(c(x), dn) for x in d.dsns]
                elif dn == "SYSUT2":
                    writes += [(c(x), dn) for x in d.dsns]
        elif p in jcl.UTILITIES:
            for dn, d in st.dds.items():
                if _disp_writes(d.disp) or "DELETE" in d.disp:
                    writes += [(c(x), dn) for x in d.dsns]
        else:
            prog = self.program(p)
            for dn in st.order:
                d = st.dds[dn]
                if dn in SKIP_DDS:
                    continue
                modes = None
                if prog is not None:
                    files = [f for f, se in prog.selects.items() if se.dd == dn]
                    if files:
                        modes = set()
                        for f in files:
                            modes |= prog.open_modes.get(f, set())
                    elif dn == "SYSOUT" and d.sysout:
                        if prog.has_display:
                            writes.append(("SYSOUT:" + st.id + "." + dn, dn))
                        continue
                    else:
                        continue
                if d.sysout:
                    if modes is None or modes & {"OUTPUT", "EXTEND", "I-O"}:
                        writes.append(("SYSOUT:" + st.id + "." + dn, dn))
                    continue
                for x in d.dsns:
                    if modes:
                        if modes & {"INPUT", "I-O"}:
                            reads.append((c(x), dn))
                        if modes & {"OUTPUT", "EXTEND", "I-O"}:
                            writes.append((c(x), dn))
                    else:
                        if _disp_reads(d.disp):
                            reads.append((c(x), dn))
                        if _disp_writes(d.disp):
                            writes.append((c(x), dn))
        return _uniq(reads), _uniq(writes)


def _disp_status(disp):
    d = disp.strip("()").split(",")[0].strip().upper() if disp else ""
    return d or "NEW"


def _disp_writes(disp):
    return _disp_status(disp) in ("NEW", "MOD", "OLD")


def _disp_reads(disp):
    return _disp_status(disp) in ("SHR", "OLD", "MOD")


def _uniq(xs):
    seen, out = set(), []
    for x in xs:
        if x[0] and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def copybook_items(tree, rel):
    """Data items a copybook declares, parsed on its own (names as written)."""
    text = tree.read(rel) or ""
    toks = cobol.tokenize(text, rel)
    items, _ = cobol.parse_data(toks)
    return items, toks


def build(root, runset=None, world=None):
    tree = world.tree if world else Tree(root)
    w = world or World(tree, runset)
    g = Graph()
    job_files = w.all_job_files()
    w.prepare(job_files)
    # copybooks: nodes, fields, nested COPY
    copy_files = {}
    for d in w.copy_dirs:
        for rel in tree.listdir(d):
            copy_files.setdefault(member_of(rel), rel)
    for m, rel in sorted(copy_files.items()):
        cb = g.node(f"copybook:{m}")
        items, toks = copybook_items(tree, rel)
        for it in items:
            if it.name != "FILLER":
                g.edge(cb, "DECLARES", f"field:{m}.{it.name}")
        for i, t in enumerate(toks):
            if t.kind == "word" and t.text == "COPY" and i + 1 < len(toks):
                g.edge(cb, "COPY", "copybook:" + toks[i + 1].text.strip("'\"").upper())
    # programs
    for m, prog in w.programs().items():
        pn = g.node(f"program:{m}")
        if prog is None:
            continue
        for c in prog.copies:
            src = pn if c.where[0] == prog.rel else "copybook:" + member_of(c.where[0])
            g.edge(src, "COPY", f"copybook:{c.member}")
        for callee in prog.calls:
            if callee:
                g.edge(pn, "CALL", f"program:{callee}")
    # jobs
    for rel in job_files:
        j = w.job(rel)
        if j is None:
            continue
        jn = g.node(f"job:{j.name}")
        for st in j.steps:
            sn = f"step:{st.id}"
            g.edge(jn, "RUNS", sn)
            g.edge(sn, "EXEC_PGM", f"program:{st.pgm}")
            for dn, d in st.dds.items():
                ddn = f"dd:{st.id}.{dn}"
                g.edge(sn, "HAS_DD", ddn)
                for x in d.dsns:
                    g.edge(ddn, "DSN", f"dataset:{w.canon(x)}")
            reads, writes = w.step_io(st)
            for x, _ in reads:
                g.edge(sn, "READS", f"dataset:{x}")
            for x, _ in writes:
                g.edge(sn, "WRITES", f"dataset:{x}")
    g.errors = list(w.errors)
    return g
