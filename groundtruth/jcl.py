"""A JCL reader for the step-runner subset (contracts/runset.md).

Reads JOB, JCLLIB, EXEC (PGM= or a PROC), DD (with in-stream data, concatenation
and procstep overrides), in-stream and library PROCs with symbolic parameters,
and PEND. Anything else is kept as an `unsupported` note on the job, so the
harness reports it and never guesses.

This is ground truth's own reader. It shares no code with the predictor (radius/).
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

EXEC_KEYWORDS = {"PGM", "PROC", "PARM", "COND", "REGION", "TIME", "ACCT", "ADDRSPC",
                 "DPRTY", "PERFORM", "RD", "DYNAMNBR", "CCSID", "MEMLIMIT"}


class JCLError(Exception):
    pass


@dataclass
class DD:
    name: str                 # "" for a concatenated DD
    params: dict              # keyword -> value; positional operands under "_pos"
    data: list = None         # in-stream lines for DD * / DD DATA
    concat: list = field(default_factory=list)   # following unnamed DDs (each a DD)


@dataclass
class Step:
    name: str
    procstep: str
    pgm: str
    params: dict
    dds: list                 # [DD]


@dataclass
class Job:
    name: str
    steps: list
    jcllib: list
    notes: list


# ------------------------------------------------------------------ operands
def parse_operands(text):
    """Operand text -> {"_pos": [...], KEY: value}. A value is a str or a list of
    values (a parenthesised list); a keyword inside a list is a (key, value) tuple."""
    items, i = _parse_list(text, 0, top=True)
    out = {"_pos": []}
    for it in items:
        if isinstance(it, tuple):
            out[it[0]] = it[1]
        else:
            out["_pos"].append(it)
    return out


def _parse_list(s, i, top=False):
    items = []
    while i < len(s):
        if s[i] == ")" and not top:
            return items, i + 1
        if s[i] == ",":
            # an empty positional (",," or a leading ",")
            items.append("")
            i += 1
            continue
        key = None
        m = re.match(r"([A-Za-z@#$][A-Za-z0-9@#$]*(?:\.[A-Za-z@#$][A-Za-z0-9@#$]*)?)=", s[i:])
        if m:
            key = m.group(1).upper()
            i += m.end()
        val, i = _parse_value(s, i)
        items.append((key, val) if key else val)
        if i < len(s) and s[i] == ",":
            i += 1
            if i >= len(s) or s[i] == ")":
                items.append("")
    return items, i


def _parse_value(s, i):
    if i < len(s) and s[i] == "(":
        return _parse_list(s, i + 1)
    if i < len(s) and s[i] == "'":
        j = i + 1
        buf = []
        while j < len(s):
            if s[j] == "'":
                if j + 1 < len(s) and s[j + 1] == "'":
                    buf.append("'")
                    j += 2
                    continue
                j += 1
                break
            buf.append(s[j])
            j += 1
        return "".join(buf), j
    j = i
    depth = 0
    while j < len(s):
        c = s[j]
        if c == "(":
            if j == i:
                break
            depth += 1
        elif c == ")":
            if depth == 0:
                break
            depth -= 1
        elif c == "," and depth == 0:
            break
        elif c == "'":
            k = s.find("'", j + 1)
            j = len(s) if k < 0 else k
        j += 1
    return s[i:j], j


def _operand_field(text):
    """The operand field of a statement's text: up to the first blank outside quotes."""
    text = text.lstrip(" ")
    q = False
    for k, c in enumerate(text):
        if c == "'":
            q = not q
        elif c == " " and not q:
            return text[:k]
    return text


# ------------------------------------------------------------------ statements
def statements(text):
    """Yield (name, op, operand_text, data_lines) for each JCL statement.

    `data_lines` is the in-stream data that follows a DD * or DD DATA statement
    (lines as they are, without "\\n"), or None.
    """
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    out = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        i += 1
        if raw.startswith("//*") or not raw.startswith("//"):
            continue
        body = raw[2:72]
        if body.strip() == "":
            break  # null statement: end of job
        name = ""
        if not body.startswith(" "):
            name, _, body = body.partition(" ")
        body = body.lstrip(" ")
        op, _, rest = body.partition(" ")
        operands = _operand_field(rest)
        while operands.endswith(",") and i < len(lines) and lines[i].startswith("//") \
                and not lines[i].startswith("//*"):
            nxt = lines[i][2:72]
            if not nxt.startswith(" "):
                break
            operands += _operand_field(nxt)
            i += 1
        data = None
        if op == "DD":
            pos = parse_operands(operands)["_pos"]
            if pos and pos[0] in ("*", "DATA"):
                data = []
                while i < len(lines):
                    ln = lines[i]
                    if ln.startswith("/*"):
                        i += 1
                        break
                    if ln.startswith("//"):
                        break
                    data.append(ln)
                    i += 1
        out.append((name.upper(), op.upper(), operands, data))
    return out


def substitute(text, symbols):
    """Replace &NAME (and &NAME.) by its value when NAME is a known symbol."""
    def rep(m):
        name = m.group(1).upper()
        if name in symbols:
            return symbols[name]
        return m.group(0)
    return re.sub(r"(?<!&)&([A-Za-z@#$][A-Za-z0-9@#$]{0,7})\.?", rep, text)


# ------------------------------------------------------------------ jobs
def _find_proc(name, jcllib, libraries, root):
    for lib in jcllib:
        spec = libraries.get(lib)
        if not spec:
            continue
        for ext in spec.get("ext", []):
            p = Path(root) / spec["dir"] / f"{name}{ext}"
            if p.is_file():
                return p
        d = Path(root) / spec["dir"]
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.stem.upper() == name and p.suffix in spec.get("ext", [p.suffix]):
                    return p
    return None


def _read_proc(stmts):
    """(defaults, body statements) for a PROC ... PEND sequence."""
    head = stmts[0]
    defaults = {}
    for k, v in parse_operands(head[2]).items():
        if k != "_pos":
            defaults[k] = v if isinstance(v, str) else ""
    body = []
    for s in stmts[1:]:
        if s[1] == "PEND":
            break
        body.append(s)
    return defaults, body


def _build_dds(stmts, symbols):
    """DD statements -> [DD], with unnamed DDs folded into the previous one's concat."""
    dds = []
    for name, op, operands, data in stmts:
        params = parse_operands(substitute(operands, symbols))
        dd = DD(name=name, params=params, data=data)
        if name == "" and dds:
            dds[-1].concat.append(dd)
        else:
            dds.append(dd)
    return dds


def _merge_override(dds, ov):
    for i, dd in enumerate(dds):
        if dd.name == ov.name:
            merged = dict(dd.params)
            for k, v in ov.params.items():
                if k == "_pos":
                    if v:
                        merged["_pos"] = v
                else:
                    merged[k] = v
            if "DSN" in ov.params or "DSNAME" in ov.params:
                merged.pop("DSNAME", None)
            dds[i] = DD(name=dd.name, params=merged,
                        data=ov.data if ov.data is not None else (None if "DSN" in ov.params else dd.data),
                        concat=ov.concat or dd.concat)
            return
    dds.append(ov)


def parse_job(path, libraries, root, jobname=None):
    """Parse one job file into a Job with PROCs expanded."""
    text = Path(path).read_bytes().decode("utf-8", "surrogateescape")
    stmts = statements(text)
    job = Job(name=jobname or "", steps=[], jcllib=[], notes=[])
    instream = {}
    i = 0
    # collect in-stream PROCs first
    plain = []
    while i < len(stmts):
        s = stmts[i]
        if s[1] == "PROC":
            j = i
            while j < len(stmts) and stmts[j][1] != "PEND":
                j += 1
            instream[s[0]] = stmts[i:j + 1]
            i = j + 1
            continue
        plain.append(s)
        i += 1

    cur = None  # (exec stmt, [dd stmts])
    groups = []
    for s in plain:
        name, op, operands, data = s
        if op == "JOB":
            job.name = job.name or name
        elif op == "JCLLIB":
            v = parse_operands(operands).get("ORDER", [])
            job.jcllib = [x for x in (v if isinstance(v, list) else [v]) if isinstance(x, str)]
        elif op == "EXEC":
            cur = (s, [])
            groups.append(cur)
        elif op == "DD":
            if cur is None:
                if name in ("JOBLIB", "JOBCAT"):
                    continue
                job.notes.append(f"DD {name} before any EXEC ignored")
                continue
            cur[1].append(s)
        elif op in ("SET", "OUTPUT", "IF", "ELSE", "ENDIF", "INCLUDE", "JES2", "CNTL", "ENDCNTL"):
            job.notes.append(f"unsupported statement {op}")
            if cur is not None:
                cur[1].append((name, "UNSUPPORTED:" + op, operands, data))
        else:
            job.notes.append(f"unknown statement {op}")

    for (sname, _, operands, _), dds in groups:
        ops = parse_operands(operands)
        pos = ops["_pos"]
        pgm = ops.get("PGM")
        proc = ops.get("PROC") or (pos[0] if pos and pgm is None else None)
        unsupported = [d[1][len("UNSUPPORTED:"):] for d in dds if d[1].startswith("UNSUPPORTED:")]
        dds = [d for d in dds if not d[1].startswith("UNSUPPORTED:")]
        if pgm is not None:
            st = Step(name=sname, procstep=None, pgm=str(pgm).upper(), params=ops, dds=_build_dds(dds, {}))
            if unsupported:
                st.params = dict(ops, _unsupported=unsupported)
            job.steps.append(st)
            continue
        proc = str(proc).upper()
        body = instream.get(proc)
        if body is None:
            p = _find_proc(proc, job.jcllib, libraries, root)
            if p is None:
                job.steps.append(Step(name=sname, procstep=None, pgm=None,
                                      params=dict(ops, _unsupported=[f"PROC {proc} not found"]), dds=[]))
                continue
            pstmts = statements(p.read_bytes().decode("utf-8", "surrogateescape"))
            pstart = next((k for k, s in enumerate(pstmts) if s[1] == "PROC"), None)
            if pstart is None:
                job.steps.append(Step(name=sname, procstep=None, pgm=None,
                                      params=dict(ops, _unsupported=[f"{p.name} has no PROC statement"]), dds=[]))
                continue
            body = pstmts[pstart:]
        defaults, pbody = _read_proc(body)
        symbols = dict(defaults)
        for k, v in ops.items():
            if k == "_pos" or k in EXEC_KEYWORDS or "." in k:
                continue
            symbols[k] = v if isinstance(v, str) else ""
        # proc steps
        psteps = []
        pcur = None
        for ps in pbody:
            pname, pop, poper, pdata = ps
            if pop == "EXEC":
                pcur = [ps, []]
                psteps.append(pcur)
            elif pop == "DD" and pcur is not None:
                pcur[1].append(ps)
        overrides = {}
        for d in _build_dds(dds, {}):
            if "." in d.name:
                stepname, _, ddname = d.name.partition(".")
                d.name = ddname
                overrides.setdefault(stepname, []).append(d)
            elif d.name == "" or not psteps:
                continue
            else:
                # an override without a procstep name applies to the first step
                overrides.setdefault(psteps[0][0][0], []).append(d)
        for (pname, _, poper, _), pdds in psteps:
            pops = parse_operands(substitute(poper, symbols))
            for k, v in ops.items():
                if k.endswith("." + pname):
                    pops[k.split(".")[0]] = v
            for k in ("COND", "PARM"):
                if k in ops and k not in pops and not any(x.startswith(k + ".") for x in ops):
                    pops[k] = ops[k]
            built = _build_dds(pdds, symbols)
            for ov in overrides.get(pname, []):
                _merge_override(built, ov)
            ppgm = pops.get("PGM")
            st = Step(name=sname, procstep=pname, pgm=str(ppgm).upper() if ppgm else None,
                      params=pops, dds=built)
            if ppgm is None:
                st.params = dict(pops, _unsupported=["nested PROC call"])
            if unsupported:
                st.params = dict(st.params, _unsupported=st.params.get("_unsupported", []) + unsupported)
            job.steps.append(st)
    return job


# ------------------------------------------------------------------ helpers
def flat(v):
    """A parameter value as a flat list of strings."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    out = []
    for x in v:
        if isinstance(x, tuple):
            continue
        out.extend(flat(x))
    return out


def sub(v, key):
    """A keyword inside a list value, e.g. sub(DCB, "LRECL")."""
    if isinstance(v, list):
        for x in v:
            if isinstance(x, tuple) and x[0] == key:
                return x[1]
    return None
