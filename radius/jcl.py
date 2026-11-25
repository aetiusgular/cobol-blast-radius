"""JCL: statements with provenance, PROC expansion, and what each step reads and writes.

Covers the JCL CardDemo's batch jobs use: JOB, JCLLIB, SET, EXEC PGM= and
EXEC PROC (in-stream or from a library) with symbolic parameters, DD with
procstep overrides and concatenation, in-stream data, GDG relative
generations. Every statement keeps the file and lines it came from.
"""
import re
from dataclasses import dataclass, field

UTILITIES = {"IDCAMS", "SORT", "ICEMAN", "SYNCSORT", "IEBGENER", "ICEGENER", "IEFBR14", "SDSF", "IKJEFT01", "IKJEFT1B", "FTP", "IEBCOPY"}
EXEC_KEYWORDS = {"PGM", "PROC", "PARM", "COND", "REGION", "TIME", "ACCT", "ADDRSPC", "DPRTY", "PERFORM", "RD", "DYNAMNBR", "CCSID", "MEMLIMIT", "TVSMSG", "TVSAMCOM", "PARMDD"}


@dataclass
class Stmt:
    name: str
    op: str
    operands: str
    file: str
    lines: set            # {(file, line)}
    instream: list = field(default_factory=list)  # [(file, line, text)]

    @property
    def where(self):
        return set(self.lines) | {(f, n) for f, n, _ in self.instream}


def split_params(s):
    """Top-level comma split that respects quotes and parentheses."""
    out, buf, depth, q = [], [], 0, False
    for c in s:
        if c == "'":
            q = not q
        if not q:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            elif c == "," and depth == 0:
                out.append("".join(buf))
                buf = []
                continue
        buf.append(c)
    if buf:
        out.append("".join(buf))
    return [p for p in out if p != ""]


def params(operands):
    pos, kw = [], {}
    for p in split_params(operands):
        if "=" in p and not p.startswith("'"):
            k, v = p.split("=", 1)
            kw[k.upper()] = v
        else:
            pos.append(p)
    return pos, kw


def _operand_end(s):
    """Index where the operand field ends: the first space outside quotes."""
    q = False
    for i, c in enumerate(s):
        if c == "'":
            q = not q
        elif c == " " and not q:
            return i
    return len(s)


def statements(text, rel):
    """JCL statements of a file, with continuations joined and in-stream data attached."""
    out = []
    cur = None
    cont = False
    instream_dd = None
    for n, raw in enumerate(text.split("\n"), 1):
        line = raw.rstrip("\r")[:72]
        if instream_dd is not None:
            if line.startswith("/*") or line.startswith("//"):
                instream_dd = None
                if line.startswith("/*"):
                    continue
            else:
                instream_dd.instream.append((rel, n, line))
                continue
        if line.startswith("//*") or line.startswith("/*"):
            continue
        if not line.startswith("//"):
            continue
        body = line[2:]
        if cont and cur is not None:
            s = body.lstrip()
            e = _operand_end(s)
            cur.operands += s[:e]
            cur.lines.add((rel, n))
            cont = cur.operands.endswith(",")
            if not cont:
                instream_dd = _instream_start(cur)
            continue
        if not body.strip():
            cur = None
            continue
        if body[0] != " ":
            sp = body.find(" ")
            name = body[:sp] if sp >= 0 else body
            rest = body[sp:].lstrip() if sp >= 0 else ""
        else:
            name, rest = "", body.lstrip()
        sp = rest.find(" ")
        op = (rest[:sp] if sp >= 0 else rest).upper()
        rest = rest[sp:].lstrip() if sp >= 0 else ""
        e = _operand_end(rest)
        cur = Stmt(name.upper(), op, rest[:e], rel, {(rel, n)})
        out.append(cur)
        cont = cur.operands.endswith(",")
        if not cont:
            instream_dd = _instream_start(cur)
    return out


def _instream_start(st):
    if st.op != "DD":
        return None
    pos, kw = params(st.operands)
    if pos and pos[0] in ("*", "DATA"):
        return st
    return None


# ------------------------------------------------------------------ datasets

_GEN = re.compile(r"^\([+-]?\d+\)$")


def dsn_name(raw):
    """A dataset name as runset.md names it: upper case, GDG generation stripped.

    Returns None for NULLFILE and DUMMY. A library member keeps its member,
    `LIB(MEMBER)`.
    """
    if raw is None:
        return None
    s = raw.strip().strip("'").upper()
    if not s or s in ("NULLFILE", "DUMMY"):
        return None
    m = re.match(r"^(.*?)(\([^()]*\))$", s)
    if m and _GEN.match(m.group(2)):
        s = m.group(1)
    return s


def subst(s, values):
    """Replace &NAME and &NAME. with symbolic values; unknown ones stay."""
    def f(m):
        k = m.group(1).upper()
        return values[k] if k in values else m.group(0)
    out = re.sub(r"&([A-Za-z@#$][A-Za-z0-9@#$]*)\.?", f, s)
    return out


# ------------------------------------------------------------------ steps

@dataclass
class DD:
    name: str
    dsns: list                # dataset names after substitution, concatenation included
    raw: list                 # the DSN values as written after substitution
    disp: str
    sysout: bool
    instream: list            # [(file, line, text)]
    lines: set
    member_file: str = None   # the source file of a library member DSN (SYSIN)

    @property
    def where(self):
        return set(self.lines) | {(f, n) for f, n, _ in self.instream}


@dataclass
class Step:
    id: str                   # JOB.STEP or JOB.STEP.PROCSTEP
    job: str
    pgm: str
    parm: str
    exec_lines: set           # EXEC statement lines, the calling EXEC's too
    dds: dict                 # name -> DD
    order: list               # DD names in order
    proc_file: str = None

    @property
    def where(self):
        out = set(self.exec_lines)
        for d in self.dds.values():
            out |= d.where
        return out

    @property
    def utility(self):
        return self.pgm in UTILITIES


@dataclass
class Job:
    name: str
    file: str
    steps: list
    card_lines: set           # JOB, JCLLIB and SET statement lines


def _mk_dd(st, values, resolve_member):
    pos, kw = params(subst(st.operands, values))
    raw = kw.get("DSN") or kw.get("DSNAME")
    disp = kw.get("DISP", "")
    sysout = "SYSOUT" in kw
    member_file = None
    if raw:
        m = re.match(r"^(.*?)\(([A-Za-z@#$][A-Za-z0-9@#$]*)\)$", raw.strip().strip("'"))
        if m and resolve_member:
            member_file = resolve_member(m.group(1).upper(), m.group(2).upper())
    d = DD(st.name.split(".")[-1], [], [], disp.upper(), sysout, list(st.instream), set(st.lines), member_file)
    if raw:
        nm = dsn_name(raw)
        if nm:
            d.dsns.append(nm)
            d.raw.append(raw.upper())
    return d


def _proc_body(stmts, start):
    """Statements of an in-stream or catalogued PROC from its PROC statement to PEND."""
    out = []
    for st in stmts[start + 1:]:
        if st.op == "PEND":
            break
        out.append(st)
    return out


class JclReader:
    """Parses jobs from a Tree. `libraries` maps a library DSN to {dir, ext} (runset.json)."""

    def __init__(self, tree, libraries=None):
        self.tree = tree
        self.libraries = {k.upper(): v for k, v in (libraries or {}).items()}

    def resolve_member(self, lib, member, order=()):
        if lib in self.libraries:
            spec = self.libraries[lib]
            hit = self.tree.find_member([spec["dir"]], member, [e.lower() for e in spec.get("ext", [])] + [""])
            if hit:
                return hit
        if self.libraries and lib in self.libraries:
            return None
        return self.tree.find_member(["app/ctl", "app/proc", "app/jcl"], member, [".ctl", ".prc", ".proc", ".jcl", ""])

    def find_proc(self, name, order):
        for lib in order:
            hit = self.resolve_member(lib, name)
            if hit:
                return hit
        return self.tree.find_member(["app/proc"], name, [".prc", ".proc", ".jcl", ""])

    def read_job(self, rel):
        text = self.tree.read(rel)
        if text is None:
            return None
        stmts = statements(text, rel)
        job = Job("", rel, [], set())
        order, values = [], {}
        instream_procs = {}
        k = 0
        while k < len(stmts):
            st = stmts[k]
            if st.op == "PROC":
                body = _proc_body(stmts, k)
                instream_procs[st.name] = (st, body)
                k += len(body) + 2
                continue
            k += 1
        cur_exec, cur_dds = None, []
        groups = []
        k = 0
        while k < len(stmts):
            st = stmts[k]
            if st.op == "PROC":
                k += len(instream_procs.get(st.name, (None, []))[1]) + 2
                continue
            if st.op == "JOB":
                job.name = st.name
                job.card_lines |= st.lines
            elif st.op == "JCLLIB":
                job.card_lines |= st.lines
                _, kw = params(st.operands)
                o = kw.get("ORDER", "")
                order = [x.strip().strip("'").upper() for x in split_params(o.strip("()"))]
            elif st.op == "SET":
                job.card_lines |= st.lines
                _, kw = params(st.operands)
                values.update({kk: v.strip("'") for kk, v in kw.items()})
            elif st.op == "EXEC":
                if cur_exec is not None:
                    groups.append((cur_exec, cur_dds))
                cur_exec, cur_dds = st, []
            elif st.op == "DD" and cur_exec is not None:
                cur_dds.append(st)
            k += 1
        if cur_exec is not None:
            groups.append((cur_exec, cur_dds))
        if not job.name:
            job.name = rel.rsplit("/", 1)[-1].split(".")[0].upper()
        for ex, dds in groups:
            job.steps.extend(self._expand(job, ex, dds, values, order, instream_procs, ()))
        return job

    def _expand(self, job, ex, dds, values, order, instream_procs, stack, prefix=None, outer_lines=()):
        pos, kw = params(subst(ex.operands, values))
        pgm = kw.get("PGM")
        sid = f"{prefix}.{ex.name}" if prefix else f"{job.name}.{ex.name}"
        exec_lines = set(ex.lines) | set(outer_lines)
        if pgm:
            st = Step(sid, job.name, pgm.strip("'").upper(), kw.get("PARM", ""), exec_lines, {}, [])
            self._add_dds(st, dds, values)
            return [st]
        pname = (kw.get("PROC") or (pos[0] if pos else "")).strip("'").upper()
        if not pname or pname in stack or len(stack) > 3:
            return [Step(sid, job.name, pname or "?", "", exec_lines, {}, [])]
        if pname in instream_procs:
            pst, body = instream_procs[pname]
            pfile = ex.file
        else:
            pfile = self.find_proc(pname, order)
            if not pfile:
                return [Step(sid, job.name, pname, "", exec_lines, {}, [])]
            pstmts = statements(self.tree.read(pfile), pfile)
            idx = next((i for i, s in enumerate(pstmts) if s.op == "PROC"), None)
            if idx is None:
                pst, body = Stmt(pname, "PROC", "", pfile, set()), pstmts
            else:
                pst, body = pstmts[idx], _proc_body(pstmts, idx)
        _, defaults = params(pst.operands)
        sym = dict(values)
        sym.update({k: v.strip("'") for k, v in defaults.items()})
        step_parms = {}
        for k, v in kw.items():
            if "." in k:
                key, ps = k.split(".", 1)
                step_parms.setdefault(ps, {})[key] = v
            elif k not in EXEC_KEYWORDS:
                sym[k] = v.strip("'")
        overrides = {}
        for d in dds:
            if "." in d.name:
                ps, ddn = d.name.split(".", 1)
                overrides.setdefault(ps, []).append((ddn, d))
        pgroups, cur, cur_dds = [], None, []
        for s in body:
            if s.op == "EXEC":
                if cur is not None:
                    pgroups.append((cur, cur_dds))
                cur, cur_dds = s, []
            elif s.op == "DD" and cur is not None:
                cur_dds.append(s)
        if cur is not None:
            pgroups.append((cur, cur_dds))
        steps = []
        for pex, pdds in pgroups:
            ppos, pkw = params(subst(pex.operands, sym))
            ppgm = pkw.get("PGM")
            lines = exec_lines | set(pst.lines)
            if not ppgm:
                steps.extend(self._expand(job, pex, pdds, sym, order, instream_procs, stack + (pname,), sid, lines))
                continue
            st = Step(f"{sid}.{pex.name}", job.name, ppgm.strip("'").upper(), step_parms.get(pex.name, {}).get("PARM", pkw.get("PARM", "")),
                      lines | set(pex.lines), {}, [], pfile)
            self._add_dds(st, pdds, sym)
            for ddn, d in overrides.get(pex.name, []):
                nd = _mk_dd(Stmt(ddn, "DD", d.operands, d.file, set(d.lines), list(d.instream)), values, self.resolve_member)
                if ddn in st.dds:
                    st.dds[ddn] = nd
                else:
                    st.dds[ddn] = nd
                    st.order.append(ddn)
            steps.append(st)
        return steps

    def _add_dds(self, st, dds, values):
        last = None
        for d in dds:
            if not d.name and last is not None:
                extra = _mk_dd(d, values, self.resolve_member)
                prev = st.dds[last]
                prev.dsns.extend(extra.dsns)
                prev.raw.extend(extra.raw)
                prev.lines |= extra.lines
                prev.instream.extend(extra.instream)
                continue
            if "." in d.name:
                continue
            nd = _mk_dd(d, values, self.resolve_member)
            st.dds[nd.name] = nd
            st.order.append(nd.name)
            last = nd.name


# ------------------------------------------------------------------ utility control statements

def control_text(tree, dd):
    """The control statements a DD supplies: in-stream lines or a library member's lines."""
    rows = [(f, n, t) for f, n, t in dd.instream]
    if dd.member_file:
        text = tree.read(dd.member_file) or ""
        for n, line in enumerate(text.split("\n"), 1):
            rows.append((dd.member_file, n, line.rstrip("\r")[:72]))
    return rows


def idcams_commands(rows):
    """IDCAMS commands as (verb, {keyword: [values]}, names) from control lines."""
    text = []
    for _, _, t in rows:
        s = t
        while "/*" in s:
            a = s.index("/*")
            b = s.find("*/", a + 2)
            s = s[:a] + (s[b + 2:] if b >= 0 else "")
        text.append(s)
    joined = ""
    for s in text:
        s = s.rstrip()
        if s.endswith("-"):
            joined += s[:-1] + " "
        else:
            joined += s + "\n"
    cmds = []
    for line in joined.split("\n"):
        words = line.split()
        if not words:
            continue
        verb = words[0].upper()
        if verb in ("IF", "SET", "ELSE", "END", "DO"):
            continue
        cmds.append((verb, line.upper()))
    out = []
    for verb, line in cmds:
        kv = {}
        for m in re.finditer(r"([A-Z]+)\s*\(\s*([^()]*?)\s*\)", line):
            kv.setdefault(m.group(1), []).append(m.group(2).split()[0] if m.group(2).split() else "")
        sub = ""
        m = re.match(r"\s*DEFINE\s+([A-Z]+)", line)
        if m:
            sub = m.group(1)
        first = line.split()[1] if len(line.split()) > 1 else ""
        out.append((verb, sub, kv, first))
    return out


def sort_has_filter(rows):
    return any(re.search(r"\b(INCLUDE|OMIT)\b", t.upper()) for _, _, t in rows)


def idcams_io(tree, step):
    """(reads, writes, aliases) of an IDCAMS step: dataset names, and component name -> cluster/AIX."""
    reads, writes, aliases = [], [], {}
    sysin = step.dds.get("SYSIN")
    rows = control_text(tree, sysin) if sysin else []
    if sysin and sysin.dsns:
        reads.extend(sysin.dsns)

    def ddsns(ddn):
        d = step.dds.get(ddn.upper())
        return list(d.dsns) if d else []

    for verb, sub, kv, first in idcams_commands(rows):
        if verb == "REPRO":
            for k in ("INFILE", "IFILE"):
                for v in kv.get(k, []):
                    reads.extend(ddsns(v))
            for k in ("INDATASET", "IDS"):
                reads.extend(dsn_name(v) for v in kv.get(k, []))
            for k in ("OUTFILE", "OFILE"):
                for v in kv.get(k, []):
                    writes.extend(ddsns(v))
            for k in ("OUTDATASET", "ODS"):
                writes.extend(dsn_name(v) for v in kv.get(k, []))
        elif verb == "BLDINDEX":
            for k in ("INFILE", "IFILE"):
                for v in kv.get(k, []):
                    reads.extend(ddsns(v))
            for k in ("INDATASET", "IDS"):
                reads.extend(dsn_name(v) for v in kv.get(k, []))
            for k in ("OUTFILE", "OFILE"):
                for v in kv.get(k, []):
                    writes.extend(ddsns(v))
            for k in ("OUTDATASET", "ODS"):
                writes.extend(dsn_name(v) for v in kv.get(k, []))
        elif verb == "DEFINE":
            names = kv.get("NAME", [])
            if not names:
                continue
            main = dsn_name(names[0])
            if sub in ("CLUSTER", "AIX", "ALTERNATEINDEX", "GENERATIONDATAGROUP", "GDG"):
                writes.append(main)
                for comp in names[1:]:
                    aliases[dsn_name(comp)] = main
                for v in kv.get("RELATE", []):
                    reads.append(dsn_name(v))
            elif sub == "PATH":
                for v in kv.get("PATHENTRY", []):
                    aliases[main] = dsn_name(v)
        elif verb == "DELETE":
            if first:
                writes.append(dsn_name(first))
    return [r for r in reads if r], [w for w in writes if w], aliases
