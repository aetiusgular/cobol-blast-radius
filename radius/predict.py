"""Blast radius of a change (contracts/radius.md).

`predict` is the full predictor: it parses the tree before and after the
change, finds the data items and statements the edited lines belong to, runs
a taint analysis through each run-set program (data flow, control flow,
reachability), and carries changed datasets from step to step in run-set
order. `predict_e0` is the one-hop baseline in SPEC.md.

Both read the change's `edits` and the source tree only: never `summary`,
never a harness result.
"""
from collections import OrderedDict

from radius import cobol, jcl
from radius.graph import World, copybook_items
from radius.source import Tree, apply_edits, file_kind, member_of

PREDICTOR = {"name": "graph-dataflow", "version": "1"}
E0 = {"name": "e0-one-hop", "version": "1"}
RANK = {None: 0, "content": 1, "shape": 2}


# ------------------------------------------------------------------ the two sides of a change

class Sides:
    def __init__(self, change, root, runset):
        self.runset = runset or {}
        base = Tree(root)
        by_file = OrderedDict()
        for e in change.get("edits", []):
            by_file.setdefault(e["file"].replace("\\", "/"), []).append(e)
        overlay, self.before_lines, self.after_lines = {}, {}, {}
        self.mismatches = 0
        for rel, edits in by_file.items():
            text = base.read(rel)
            if text is None:
                text = ""
            new, b, a, mm = apply_edits(text, edits, file_kind(rel))
            overlay[rel] = new
            self.before_lines[rel] = b
            self.after_lines[rel] = a
            self.mismatches += mm
        self.files = list(by_file)
        self.before = World(base, self.runset)
        self.after = World(Tree(root, overlay), self.runset)
        self.bpairs = {(r, n) for r, ls in self.before_lines.items() for n in ls}
        self.apairs = {(r, n) for r, ls in self.after_lines.items() for n in ls}
        self.job_files = [j["file"] for j in self.runset.get("jobs", [])]
        if not self.job_files:
            self.job_files = self.after.all_job_files()
        self.before.prepare(self.job_files)
        self.after.prepare(self.job_files)

    @property
    def members(self):
        return sorted({member_of(f) for f in self.files})

    def effective(self, rel):
        return bool(self.before_lines.get(rel) or self.after_lines.get(rel))


def _fields(sides):
    out = set()
    for rel in sides.files:
        if not any(rel.startswith(d.rstrip("/") + "/") for d in sides.after.copy_dirs):
            continue
        m = member_of(rel)
        for world, lines in ((sides.before, sides.before_lines.get(rel, set())), (sides.after, sides.after_lines.get(rel, set()))):
            if not lines:
                continue
            items, _ = copybook_items(world.tree, rel)
            for it in items:
                if it.name != "FILLER" and any(f == rel and n in lines for f, n in it.lines):
                    out.add(f"{m}.{it.name}")
    return sorted(out)


# ------------------------------------------------------------------ program seeds

def _path_names(it):
    return tuple([it.name] + [a.name for a in it.ancestors()])


def _storage_end(prog, storage):
    return max((i.offset + max(i.span, 1) for i in prog.items if i.storage == storage), default=1)


class ProgramSeed:
    """What a change does to one program, before any step's inputs are added."""

    def __init__(self, sides, member):
        self.member = member
        self.A = sides.after.program(member)
        self.B = sides.before.program(member)
        self.taint = cobol.Taint()
        self.seeded = set()
        self.ctx = set()
        self.all_out = False
        self.sinks = {}
        self.flags = {"terminates": False, "abend": False}
        self.fields = []
        self.touched = False
        if self.A is None:
            return
        A, B = self.A, self.B
        ap, bp = sides.apairs, sides.bpairs
        explained = set()
        b_index = {}
        if B is not None:
            for it in B.items:
                b_index.setdefault(_path_names(it), it)
        a_index = {_path_names(it): it for it in A.items}

        def seed_item(it, other):
            explained.update(it.lines & ap)
            self.touched = True
            if it.level == 88:
                self.taint.conds88.add(it)
                if other is None or other.sig != it.sig:
                    if it.parent is not None:
                        self.taint.add([it.parent])
                return
            if other is not None and other.sig == it.sig:
                self.taint.add([it])
                return
            # a layout change: this item and every byte after it in its storage
            self.taint.add([it])
            self.taint.add_range(it.storage, it.offset, _storage_end(A, it.storage))
            for a in [it, *it.ancestors()]:
                if a.fd:
                    self.taint.mark("shape:" + a.fd)
                    self.taint.mark("content:" + a.fd)

        for it in A.items:
            if it.lines & ap:
                seed_item(it, b_index.get(_path_names(it)))
        if B is not None:
            for it in B.items:
                if it.lines & bp:
                    self.touched = True
                    twin = a_index.get(_path_names(it))
                    if twin is None:
                        self.all_out = True
                    elif not (twin.lines & ap):
                        seed_item(twin, it)
        for p in A.paras:
            for s in p.stmts:
                if s.lines & ap:
                    self.seeded.add(s)
                    explained.update(s.lines & ap)
                    self.touched = True
        if B is not None:
            breach, _ = cobol.reachable(B)
            for p in B.paras:
                for s in p.stmts:
                    if not (s.lines & bp):
                        continue
                    self.touched = True
                    if s.para not in breach:
                        continue
                    for tgts, _, _ in s.assigns:
                        self.taint.add([a_index[_path_names(t)] for t in tgts if _path_names(t) in a_index])
                    for tgts, _ in s.moves:
                        self.taint.add([a_index[_path_names(t)] for t in tgts if _path_names(t) in a_index])
                    for sink, _, _ in s.sinks:
                        self.sinks[sink] = "shape"
                    for a, b, _ in s.performs:
                        for k in range(a, b + 1):
                            nm = B.paras[k].name
                            if nm in A.para_index:
                                self.ctx.add(A.para_index[nm])
                    if s.terminates:
                        self.flags["terminates"] = True
                    if s.abend:
                        self.flags["abend"] = True
                    # A removed jump changes what runs after it (CB-P3b-r2-C1). NEXT SENTENCE:
                    # the rest of its sentence, an enclosing inline PERFORM included, as on the
                    # after side. GO TO: the rest of its paragraph and the paragraphs it reached.
                    nm = B.paras[s.para].name
                    if (s.next_sentence or s.goto) and nm in A.para_index:
                        ak = A.para_index[nm]
                        if s.goto:
                            self.ctx.add(ak)
                        else:
                            self.seeded.update(o for o in A.paras[ak].stmts if o.sentence == s.sentence)
                    for g in s.goto:
                        if B.paras[g].name in A.para_index:
                            self.ctx.add(A.para_index[B.paras[g].name])
                    if s.goto:
                        self.flags["terminates"] = True
        # changes outside data items and statements: SELECT, headers, PROGRAM-ID
        for t in A.toks:
            if t.where in ap and t.where not in explained:
                self.all_out = True
                self.touched = True
        if B is not None:
            b_explained = set()
            for it in B.items:
                b_explained |= it.lines & bp
            for p in B.paras:
                for s in p.stmts:
                    b_explained |= s.lines & bp
            for t in B.toks:
                if t.where in bp and t.where not in b_explained:
                    self.all_out = True
                    self.touched = True

    def run(self, inputs=(), dd_changed=(), parm_changed=False, exec_changed=False):
        """Sinks for one step. `inputs` is [(file, level)], `dd_changed` files whose DD changed."""
        A = self.A
        if A is None:
            return {}, {"terminates": False, "abend": False}, False
        taint = cobol.Taint()
        taint.mem = dict(self.taint.mem)
        taint.marks = set(self.taint.marks)
        taint.conds88 = set(self.taint.conds88)
        hot = self.touched
        for f, level in inputs:
            hot = True
            taint.add(A.record_items(f))
            taint.mark("content:" + f)
            if level == "shape":
                taint.mark("shape:" + f)
        for f in dd_changed:
            hot = True
            taint.mark("shape:" + f)
            taint.mark("content:" + f)
            taint.add(A.record_items(f))
        if parm_changed:
            hot = True
            taint.add(A.using)
        if not hot and not exec_changed:
            return {}, {"terminates": False, "abend": False}, False
        sinks, flags = cobol.analyse(A, taint, self.seeded, self.ctx, all_out=self.all_out or exec_changed)
        for k, v in self.sinks.items():
            if RANK[v] > RANK[sinks.get(k)]:
                sinks[k] = v
        flags = {k: flags[k] or self.flags[k] for k in flags}
        if flags["terminates"] or flags["abend"]:
            for f in A.selects:
                if A.open_modes.get(f, set()) & {"OUTPUT", "EXTEND", "I-O"}:
                    sinks[f] = "shape"
            if A.has_display:
                sinks["SYSOUT"] = "shape"
        return sinks, flags, True


# ------------------------------------------------------------------ steps

def _step_changes(sides, a_step, b_step, a_job, b_job):
    """(exec_changed, changed DD names) for a step, from the edited lines on both sides."""
    ap, bp = sides.apairs, sides.bpairs
    exec_changed = False
    dds = set()

    def look(step, job, pairs):
        nonlocal exec_changed
        if step is None:
            return
        if step.exec_lines & pairs or (job is not None and job.card_lines & pairs):
            exec_changed = True
        for dn, d in step.dds.items():
            hit = bool(d.where & pairs)
            if d.member_file and any(f == d.member_file for f, _ in pairs):
                hit = True
            if hit:
                dds.add(dn)
    look(a_step, a_job, ap)
    look(b_step, b_job, bp)
    return exec_changed, dds


def _better(level, old):
    return RANK[level] > RANK[old]


def _seed_path(sides, step, prog_member, fields):
    path = []
    for rel in sides.files:
        m = member_of(rel)
        k = file_kind(rel)
        if k == "jcl" and rel.startswith("app/jcl/"):
            path = [f"job:{step.job}"]
        elif k == "jcl":
            path = []
        elif k == "ctl":
            sysin = step.dds.get("SYSIN")
            path = [f"dataset:{sysin.dsns[0]}"] if sysin and sysin.dsns else []
        elif rel.startswith("app/cpy/") or "/cpy/" in rel:
            path = [f"copybook:{m}"] + ([f"field:{fields[0]}"] if fields and fields[0].startswith(m + ".") else [])
            if prog_member:
                path.append(f"program:{prog_member}")
        else:
            path = [f"program:{m}"]
        if path:
            break
    return path + [f"step:{step.id}"]


def predict(change, root, runset):
    sides = Sides(change, root, runset)
    fields = _fields(sides)
    A, B = sides.after, sides.before
    seeds = {}

    def seed(member):
        if member not in seeds:
            seeds[member] = ProgramSeed(sides, member)
        return seeds[member]

    state = {}         # dataset -> level
    why = {}           # dataset -> path
    steps_hit, jobs_hit, programs_hit = set(), set(), set()
    universe = set()
    run_programs = set()
    for jf in sides.job_files:
        aj, bj = A.job(jf), B.job(jf)
        if aj is None and bj is None:
            continue
        a_steps = OrderedDict((s.id, s) for s in (aj.steps if aj else []))
        b_steps = OrderedDict((s.id, s) for s in (bj.steps if bj else []))
        ids = list(a_steps) + [i for i in b_steps if i not in a_steps]
        job_abend = None
        for sid in ids:
            ast, bst = a_steps.get(sid), b_steps.get(sid)
            st = ast or bst
            world = A if ast else B
            a_io = A.step_io(ast) if ast else ([], [])
            b_io = B.step_io(bst) if bst else ([], [])
            writes = _merge(a_io[1], b_io[1])
            reads = _merge(a_io[0], b_io[0])
            universe |= {x for x, _ in writes}
            if not st.utility:
                run_programs.add(st.pgm)
            exec_changed, dd_changed = _step_changes(sides, ast, bst, aj, bj)
            if ast is None or bst is None or (ast.pgm != bst.pgm):
                exec_changed = True
            out = {}   # dataset -> (level, path)
            in_hit = [(x, dn) for x, dn in reads if state.get(x)]
            in_path = (why[in_hit[0][0]] + [f"step:{sid}"]) if in_hit else None
            if job_abend is not None:
                for x, _ in writes:
                    out[x] = ("shape", job_abend + [f"step:{sid}"])
            elif st.utility:
                if exec_changed or dd_changed:
                    p = _seed_path(sides, st, None, fields)
                    for x, _ in writes:
                        out[x] = ("shape", p)
                elif in_hit:
                    level = max((state[x] for x, _ in in_hit), key=lambda v: RANK[v])
                    if st.pgm in ("SORT", "ICEMAN", "SYNCSORT"):
                        rows = jcl.control_text(world.tree, st.dds["SYSIN"]) if "SYSIN" in st.dds else []
                        if level == "content" and jcl.sort_has_filter(rows):
                            level = "shape"
                    for x, _ in writes:
                        out[x] = (level, in_path)
            else:
                prog = A.program(st.pgm) or B.program(st.pgm)
                ps = seed(st.pgm)
                if prog is None or ps.A is None:
                    if exec_changed or dd_changed or in_hit:
                        p = in_path or _seed_path(sides, st, None, fields)
                        for x, _ in writes:
                            out[x] = ("shape", p)
                else:
                    P = ps.A
                    inputs = []
                    for x, dn in in_hit:
                        for f, se in P.selects.items():
                            if se.dd == dn:
                                inputs.append((f, state[x]))
                    ddf = [f for f, se in P.selects.items() if se.dd in dd_changed]
                    parm_changed = exec_changed
                    sinks, flags, ran = ps.run(inputs, ddf, parm_changed, exec_changed)
                    seed_p = _seed_path(sides, st, st.pgm, fields)
                    own = ps.run((), ddf, parm_changed, exec_changed)[0] if (in_hit and ran) else sinks
                    for sink, level in sinks.items():
                        path = seed_p if (sink in own or not in_hit) else in_path
                        dn = "SYSOUT" if sink == "SYSOUT" else P.selects[sink].dd if sink in P.selects else None
                        if dn is None or dn not in st.dds:
                            continue
                        d = st.dds[dn]
                        if d.sysout:
                            names = ["SYSOUT:" + sid + "." + dn]
                        else:
                            names = [A.canon(x) for x in d.dsns]
                        for x in names:
                            if x in {w for w, _ in writes} and _better(level, out.get(x, (None,))[0]):
                                out[x] = (level, path)
                    for dn in dd_changed:
                        for x, wdn in writes:
                            if wdn == dn:
                                out[x] = ("shape", seed_p)
                    if flags.get("abend"):
                        job_abend = in_path if in_hit else seed_p
            for x, (level, path) in sorted(out.items()):
                if level is None:
                    continue
                if _better(level, state.get(x)):
                    state[x] = level
                if x not in why:
                    why[x] = path + [f"dataset:{x}"]
                steps_hit.add(sid)
                jobs_hit.add(st.job)
                programs_hit.add(st.pgm)
    datasets = sorted(x for x in state if x in universe)
    unverifiable = _unverifiable(sides, run_programs)
    return {
        "change_id": change["id"],
        "members": sides.members,
        "fields": fields,
        "programs": sorted(programs_hit),
        "jobs": sorted(jobs_hit),
        "steps": sorted(steps_hit),
        "datasets": datasets,
        "unverifiable": unverifiable,
        "why": {x: why[x] for x in datasets},
        "predictor": dict(PREDICTOR),
    }


def _merge(a, b):
    seen, out = set(), []
    for x in list(a) + list(b):
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _unverifiable(sides, run_programs):
    """Programs no run-set step runs that the change still reaches (CICS programs among them)."""
    out = set()
    for m in sorted(sides.after.program_files):
        if m in run_programs:
            continue
        p = sides.after.program(m)
        q = sides.before.program(m)
        hit = False
        if p is not None and any(t.where in sides.apairs for t in p.toks):
            hit = True
        if q is not None and any(t.where in sides.bpairs for t in q.toks):
            hit = True
        if hit:
            out.add(f"program:{m}")
    return sorted(out)


# ------------------------------------------------------------------ E0

def predict_e0(change, root, runset):
    """E0: every output of every job that runs a program which COPYs a changed member,
    or runs a changed program, or is (or expands) a changed JCL member. One hop, no data flow,
    and no check of whether the edited lines mean anything."""
    sides = Sides(change, root, runset)
    A, B = sides.after, sides.before
    members = set(sides.members)
    edited = set(sides.files)
    progs = set()
    for m in sorted(B.program_files):
        p = B.program(m)
        if m in members:
            progs.add(m)
        elif p is not None and any(c.member in members for c in p.copies):
            progs.add(m)
    datasets, steps, jobs, programs, why = set(), set(), set(), set(), {}
    for jf in sides.job_files:
        hit_jobs = []
        for world in (B, A):
            j = world.job(jf)
            if j is None:
                continue
            cause = None
            if jf in edited:
                cause = [f"job:{j.name}"]
            for st in j.steps:
                if cause:
                    break
                if st.pgm in progs:
                    cause = [f"program:{st.pgm}", f"job:{j.name}"]
                elif st.proc_file in edited or any(d.member_file in edited for d in st.dds.values() if d.member_file):
                    cause = [f"job:{j.name}"]
            if cause:
                hit_jobs.append((world, j, cause))
        for world, j, cause in hit_jobs:
            jobs.add(j.name)
            for st in j.steps:
                steps.add(st.id)
                programs.add(st.pgm)
                _, writes = world.step_io(st)
                for x, _ in writes:
                    datasets.add(x)
                    why.setdefault(x, cause + [f"step:{st.id}", f"dataset:{x}"])
    ds = sorted(datasets)
    return {
        "change_id": change["id"],
        "members": sides.members,
        "fields": _fields(sides),
        "programs": sorted(programs),
        "jobs": sorted(jobs),
        "steps": sorted(steps),
        "datasets": ds,
        "unverifiable": _unverifiable(sides, {s.pgm for jf in sides.job_files for s in ((B.job(jf).steps) if B.job(jf) else [])}),
        "why": {x: why[x] for x in ds},
        "predictor": dict(E0),
    }
