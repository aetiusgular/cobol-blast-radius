"""Stand-ins for the utilities the run set uses (contracts/runset.json `utilities`).

Each takes the step context and returns a return code, or raises
catalog.Unsupported for a statement outside the subset. Their messages are
not outputs (contracts/runset.md): only the datasets they write are.

SORT compares bytes in the data's own code (the run set's data is ASCII), not
in EBCDIC collating order. DECISIONS.md records that call.
"""
import functools
import re

from .catalog import Unsupported

# ====================================================================== IDCAMS


def _idcams_commands(lines):
    """Control statements -> commands, with '-' and '+' continuations joined and /* */ comments removed."""
    text = "\n".join(ln[:72] for ln in lines)
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    cmds, cur = [], ""
    for ln in text.split("\n"):
        s = ln.rstrip()
        if s.endswith("-"):
            cur += s[:-1] + " "
            continue
        if s.endswith("+"):
            cur += s[:-1]
            continue
        cur += s
        if cur.strip():
            cmds.append(" ".join(cur.split()))
        cur = ""
    if cur.strip():
        cmds.append(" ".join(cur.split()))
    return cmds


def _kw(cmd, name):
    """The text inside NAME( ... ) with balanced parentheses, or None."""
    m = re.search(r"(?<![A-Z0-9-])" + name + r"\s*\(", cmd)
    if not m:
        return None
    i = m.end()
    depth = 1
    j = i
    while j < len(cmd) and depth:
        if cmd[j] == "(":
            depth += 1
        elif cmd[j] == ")":
            depth -= 1
        j += 1
    return cmd[i:j - 1].strip()


def _nums(text):
    return [int(x) for x in re.split(r"[ ,]+", text.strip()) if x]


def _has(cmd, *words):
    return any(re.search(r"(?<![A-Z0-9-])" + w + r"(?![A-Z0-9-])", cmd) for w in words)


_CMP = {"=": "EQ", "EQ": "EQ", "NE": "NE", "¬=": "NE", ">": "GT", "GT": "GT", "GE": "GE",
        ">=": "GE", "<": "LT", "LT": "LT", "LE": "LE", "<=": "LE"}


def _test(a, op, b):
    return {"EQ": a == b, "NE": a != b, "GT": a > b, "GE": a >= b, "LT": a < b, "LE": a <= b}[op]


def idcams(ctx):
    lines = ctx.sysin_lines("SYSIN")
    cc = {"LASTCC": 0, "MAXCC": 0}

    def run_cmd(cmd):
        m = re.match(r"^SET\s+(MAXCC|LASTCC)\s*=\s*(\d+)$", cmd)
        if m:
            cc[m.group(1)] = int(m.group(2))
            if m.group(1) == "LASTCC":
                cc["MAXCC"] = max(cc["MAXCC"], cc["LASTCC"])
            return
        m = re.match(r"^IF\s+(LASTCC|MAXCC)\s*(¬=|>=|<=|=|>|<|EQ|NE|GT|GE|LT|LE)\s*(\d+)\s+THEN\s*(.*)$", cmd)
        if m:
            if _test(cc[m.group(1)], _CMP[m.group(2)], int(m.group(3))):
                rest = m.group(4).strip()
                if rest.startswith("DO") or not rest:
                    raise Unsupported(f"IDCAMS IF without a single THEN command: {cmd}")
                run_cmd(rest)
            return
        rc = _idcams_one(ctx, cmd)
        cc["LASTCC"] = rc
        cc["MAXCC"] = max(cc["MAXCC"], rc)

    for cmd in _idcams_commands(lines):
        if cmd.startswith("ELSE"):
            raise Unsupported("IDCAMS ELSE")
        run_cmd(cmd)
    return cc["MAXCC"]


def _idcams_one(ctx, cmd):
    cat = ctx.cat
    verb = cmd.split()[0]
    if verb == "DELETE":
        words = cmd.split()
        name = words[1].strip("()")
        ent = cat.e.get(name)
        if ent is None:
            return 8
        ctx.note_deleted(name)
        cat.delete(name)
        return 0
    if verb in ("DEFINE", "DEF"):
        what = cmd.split()[1]
        name = _kw(cmd, "NAME")
        if not name:
            raise Unsupported(f"IDCAMS DEFINE without NAME: {cmd}")
        if what in ("GENERATIONDATAGROUP", "GDG"):
            if name in cat.e:
                return 12
            cat.define_gdg(name, int(_kw(cmd, "LIMIT") or 255), _has(cmd, "SCRATCH"))
            ctx.mark_written(name)
            return 0
        if what in ("CLUSTER", "CL"):
            if not _has(cmd, "INDEXED", "IXD"):
                raise Unsupported(f"IDCAMS DEFINE CLUSTER that is not INDEXED: {name}")
            if name in cat.e:
                return 12
            keys = _nums(_kw(cmd, "KEYS") or "")
            size = _nums(_kw(cmd, "RECORDSIZE") or _kw(cmd, "RECSZ") or "")
            if len(keys) != 2 or len(size) != 2:
                raise Unsupported(f"IDCAMS DEFINE CLUSTER needs KEYS and RECORDSIZE: {name}")
            if size[0] != size[1]:
                raise Unsupported(f"variable-length KSDS {name}")
            cat.define_ksds(name, size[1], (keys[1], keys[0]))
            ctx.mark_written(name)
            return 0
        if what in ("ALTERNATEINDEX", "AIX"):
            relate = _kw(cmd, "RELATE")
            if name in cat.e:
                return 12
            if relate not in cat.e or cat.e[relate]["kind"] != "ksds":
                return 8
            keys = _nums(_kw(cmd, "KEYS") or "")
            if len(keys) != 2:
                raise Unsupported(f"IDCAMS DEFINE AIX needs KEYS: {name}")
            cat.define_aix(name, relate, (keys[1], keys[0]), not _has(cmd, "UNIQUEKEY", "UNQK"))
            ctx.mark_written(name)
            return 0
        if what == "PATH":
            entry = _kw(cmd, "PATHENTRY") or _kw(cmd, "PENT")
            if name in cat.e:
                return 12
            if entry not in cat.e:
                return 8
            cat.define_path(name, entry)
            return 0
        raise Unsupported(f"IDCAMS DEFINE {what}")
    if verb == "REPRO":
        src = ctx.idcams_target(_kw(cmd, "INFILE") or _kw(cmd, "IFILE"),
                                _kw(cmd, "INDATASET") or _kw(cmd, "IDS"))
        dst = ctx.idcams_target(_kw(cmd, "OUTFILE") or _kw(cmd, "OFILE"),
                                _kw(cmd, "OUTDATASET") or _kw(cmd, "ODS"))
        if src is None or dst is None:
            return 12
        for opt in ("SKIP", "COUNT", "FROMKEY", "TOKEY", "REPLACE", "REUSE"):
            if _has(cmd, opt):
                raise Unsupported(f"IDCAMS REPRO {opt}")
        recs = ctx.read_records(src)
        return ctx.write_records(dst, recs, replace=False)
    if verb == "BLDINDEX":
        src = ctx.idcams_target(_kw(cmd, "INFILE") or _kw(cmd, "IFILE"),
                                _kw(cmd, "INDATASET") or _kw(cmd, "IDS"))
        dst = ctx.idcams_target(_kw(cmd, "OUTFILE") or _kw(cmd, "OFILE"),
                                _kw(cmd, "OUTDATASET") or _kw(cmd, "ODS"))
        if dst is None or cat.e.get(dst, {}).get("kind") != "aix":
            return 12
        if cat.e[dst]["relate"] != src:
            return 12
        cat.build_aix(dst)
        ctx.mark_written(dst)
        return 0
    raise Unsupported(f"IDCAMS {verb}")


# ====================================================================== SORT

def _split_top(s):
    out, depth, cur, q = [], 0, "", False
    for c in s:
        if c == "'":
            q = not q
        if not q:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            elif c == "," and depth == 0:
                out.append(cur)
                cur = ""
                continue
        cur += c
    out.append(cur)
    return [x.strip() for x in out]


def _first_word_field(line):
    """Text up to the first blank outside quotes."""
    q = False
    for k, c in enumerate(line):
        if c == "'":
            q = not q
        elif c == " " and not q:
            return line[:k]
    return line


def parse_symnames(lines):
    syms = {}
    for ln in lines:
        s = ln[:80]
        if not s.strip() or s.lstrip().startswith("*"):
            continue
        s = _first_word_field(s.strip())
        parts = _split_top(s)
        name = parts[0]
        rest = parts[1:]
        if len(rest) == 1:
            syms[name] = ("const", rest[0])
        elif len(rest) >= 2:
            pos, ln_ = int(rest[0]), int(rest[1])
            fmt = rest[2] if len(rest) > 2 else None
            syms[name] = ("field", (pos, ln_, fmt))
        else:
            raise Unsupported(f"SYMNAMES line {ln!r}")
    return syms


def _sort_statements(lines):
    stmts, cur = [], ""
    for ln in lines:
        s = ln[:71]
        if not s.strip() or s.startswith("*"):
            continue
        if s[0] != " " and not cur:
            raise Unsupported(f"SORT control statement with a label: {s!r}")
        body = _first_word_field(s.strip()) if cur else s.strip()
        if not cur:
            op, _, operands = body.partition(" ")
            operands = _first_word_field(operands.strip())
            cur = op + " " + operands
        else:
            cur += body
        if not cur.endswith(","):
            stmts.append(cur)
            cur = ""
    if cur:
        stmts.append(cur)
    return stmts


def _const(tok):
    if tok.startswith("C'") and tok.endswith("'"):
        return tok[2:-1].replace("''", "'").encode("latin-1")
    if tok.startswith("X'") and tok.endswith("'"):
        return bytes.fromhex(tok[2:-1])
    if re.fullmatch(r"[+-]?\d+", tok):
        return int(tok)
    raise Unsupported(f"SORT constant {tok}")


_ZD_NEG = {chr(0x70 + d): d for d in range(10)}
_ZD_NEG.update({"}": 0, **{chr(ord("J") + d - 1): d for d in range(1, 10)}})
_ZD_POS = {"{": 0, **{chr(ord("A") + d - 1): d for d in range(1, 10)}}


def _value(rec, pos, ln, fmt):
    b = rec[pos - 1:pos - 1 + ln].ljust(ln, b" ")
    fmt = (fmt or "CH").upper()
    if fmt in ("CH", "AQ"):
        return b
    if fmt == "BI":
        return int.from_bytes(b, "big")
    if fmt == "ZD":
        s = b.decode("latin-1")
        last = s[-1]
        neg = False
        if last in _ZD_NEG:
            neg, last = True, str(_ZD_NEG[last])
        elif last in _ZD_POS:
            last = str(_ZD_POS[last])
        digits = "".join(c for c in s[:-1] + last if c.isdigit())
        v = int(digits or "0")
        return -v if neg else v
    if fmt == "PD":
        nib = b.hex()
        sign = nib[-1]
        v = int("".join(c for c in nib[:-1] if c.isdigit()) or "0")
        return -v if sign in "bd" else v
    raise Unsupported(f"SORT format {fmt}")


def _field(tokens, i, syms, default_fmt=None):
    """Read a field at tokens[i]: a symbol or pos,len[,fmt]. Returns ((pos,len,fmt), next i)."""
    t = tokens[i]
    if t in syms and syms[t][0] == "field":
        return syms[t][1], i + 1
    if re.fullmatch(r"\d+", t):
        pos, ln = int(t), int(tokens[i + 1])
        i += 2
        fmt = default_fmt
        if i < len(tokens) and tokens[i] in ("CH", "ZD", "PD", "BI", "AQ", "FI", "FS"):
            fmt = tokens[i]
            i += 1
        return (pos, ln, fmt), i
    raise Unsupported(f"SORT field {t}")


def parse_sort_fields(spec, syms):
    inner = spec
    tokens = _split_top(inner)
    keys, i = [], 0
    fmt_all = None
    while i < len(tokens):
        if tokens[i].startswith("FORMAT="):
            fmt_all = tokens[i].split("=", 1)[1]
            tokens.pop(i)
            continue
        i += 1
    i = 0
    while i < len(tokens):
        f, i = _field(tokens, i, syms, fmt_all)
        if i >= len(tokens) or tokens[i] not in ("A", "D"):
            raise Unsupported(f"SORT FIELDS order missing near {tokens[i:i + 1]}")
        keys.append((f, tokens[i]))
        i += 1
    return keys


def parse_cond(spec, syms):
    """INCLUDE/OMIT COND=(...) -> a predicate over a record. AND binds tighter than OR."""
    tokens = _split_top(spec)
    terms, connectors, i = [], [], 0
    while i < len(tokens):
        if tokens[i].startswith("("):
            raise Unsupported("SORT COND with nested parentheses")
        lhs, i = _field(tokens, i, syms)
        op = tokens[i]
        i += 1
        t = tokens[i]
        if t in syms and syms[t][0] == "const":
            rhs, i = ("const", _const(syms[t][1])), i + 1
        elif t in syms and syms[t][0] == "field":
            rhs, i = ("field", syms[t][1]), i + 1
        elif t.startswith(("C'", "X'")) or re.fullmatch(r"[+-]?\d+", t) and (
                i + 1 >= len(tokens) or tokens[i + 1] in ("AND", "OR", "&", "|")):
            rhs, i = ("const", _const(t)), i + 1
        else:
            f, i = _field(tokens, i, syms)
            rhs = ("field", f)
        terms.append((lhs, op, rhs))
        if i < len(tokens):
            c = {"&": "AND", "|": "OR"}.get(tokens[i], tokens[i])
            if c not in ("AND", "OR"):
                raise Unsupported(f"SORT COND connector {tokens[i]}")
            connectors.append(c)
            i += 1
    for t in terms:
        if t[1] not in ("EQ", "NE", "GT", "GE", "LT", "LE"):
            raise Unsupported(f"SORT COND operator {t[1]}")

    def term_true(rec, term):
        (pos, ln, fmt), op, (kind, r) = term
        a = _value(rec, pos, ln, fmt)
        if kind == "field":
            b = _value(rec, r[0], r[1], r[2] or fmt)
        else:
            b = r
            if isinstance(a, bytes):
                if isinstance(b, int):
                    raise Unsupported("SORT COND compares a CH field with a number")
                b = b[:ln].ljust(ln, b" ")
            elif isinstance(b, bytes):
                raise Unsupported("SORT COND compares a numeric field with a string")
        return _test(a, op, b)

    def pred(rec):
        groups, cur = [], [terms[0]]
        for c, t in zip(connectors, terms[1:]):
            if c == "AND":
                cur.append(t)
            else:
                groups.append(cur)
                cur = [t]
        groups.append(cur)
        return any(all(term_true(rec, t) for t in g) for g in groups)
    return pred


def sort(ctx):
    syms = parse_symnames(ctx.sysin_lines("SYMNAMES")) if ctx.has_dd("SYMNAMES") else {}
    keys, include, omit, copy = None, None, None, False
    for st in _sort_statements(ctx.sysin_lines("SYSIN")):
        op, _, operands = st.partition(" ")
        if op == "SORT":
            m = re.match(r"^FIELDS=\((.*)\)(?:,(EQUALS|NOEQUALS))?$", operands)
            if operands == "FIELDS=COPY":
                copy = True
                continue
            if not m:
                raise Unsupported(f"SORT {operands}")
            keys = parse_sort_fields(m.group(1), syms)
        elif op in ("INCLUDE", "OMIT"):
            m = re.match(r"^COND=\((.*)\)(?:,FORMAT=(\w+))?$", operands)
            if not m:
                raise Unsupported(f"{op} {operands}")
            p = parse_cond(m.group(1), syms)
            if op == "INCLUDE":
                include = p
            else:
                omit = p
        elif op == "OPTION" and operands in ("EQUALS", "COPY"):
            copy = copy or operands == "COPY"
        else:
            raise Unsupported(f"SORT statement {op}")
    if keys is None and not copy:
        raise Unsupported("SORT without SORT FIELDS")
    recs = []
    for name in ctx.dd_datasets("SORTIN"):
        recs += ctx.read_records(name)
    if include:
        recs = [r for r in recs if include(r)]
    if omit:
        recs = [r for r in recs if not omit(r)]
    if keys:
        def cmp(a, b):
            for (pos, ln, fmt), order in keys:
                va, vb = _value(a, pos, ln, fmt), _value(b, pos, ln, fmt)
                if va != vb:
                    r = -1 if va < vb else 1
                    return r if order == "A" else -r
            return 0
        recs = sorted(recs, key=functools.cmp_to_key(cmp))  # stable: EQUALS
    out = ctx.dd_datasets("SORTOUT")
    if len(out) != 1:
        raise Unsupported("SORT needs one SORTOUT dataset")
    return ctx.write_records(out[0], recs, replace=True)


# ====================================================================== others

def iebgener(ctx):
    if ctx.has_dd("SYSIN") and any(ln[:71].strip() for ln in ctx.sysin_lines("SYSIN")):
        raise Unsupported("IEBGENER control statements")
    recs = []
    for name in ctx.dd_datasets("SYSUT1"):
        recs += ctx.read_records(name)
    out = ctx.dd_datasets("SYSUT2")
    if len(out) != 1:
        raise Unsupported("IEBGENER needs one SYSUT2 dataset")
    return ctx.write_records(out[0], recs, replace=True)


def iefbr14(ctx):
    return 0


RUNNERS = {"IDCAMS": idcams, "SORT": sort, "IEBGENER": iebgener, "IEFBR14": iefbr14}
