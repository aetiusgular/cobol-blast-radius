"""COBOL sources: tokens with provenance, COPY expansion, data layout, statements.

Fixed-format sources only (CardDemo is fixed format). Every token keeps the
file and line it came from, so an edited line can be traced to the data item
or statement it belongs to after COPY expansion.
"""
import re
from dataclasses import dataclass, field

from radius.source import COPY_EXTS, member_of

# ------------------------------------------------------------------ tokens


@dataclass
class Tok:
    text: str          # upper case, except literals keep their case
    kind: str          # word, lit, num, punct, period, pseudo, pic
    file: str
    line: int
    col: int           # 1-based column of the first character

    @property
    def where(self):
        return (self.file, self.line)


_WORD = re.compile(r"[A-Za-z0-9$#@_:][A-Za-z0-9$#@_:-]*")
_DEC = re.compile(r"\d+\.\d+")


def tokenize(text, rel):
    """Tokens of a fixed-format COBOL source. Comment lines give none."""
    toks = []
    expect_pic = False
    open_lit = None  # an unterminated literal waiting for a continuation line
    for n, raw in enumerate(text.split("\n"), 1):
        raw = raw.rstrip("\r")
        if len(raw) < 7:
            continue
        ind = raw[6]
        if ind in "*/dD":
            continue
        code = raw[7:72]
        base = 8
        i = 0
        if ind == "-" and open_lit is not None:
            q = code.find(open_lit.text[0]) if open_lit.text else -1
            if q >= 0:
                j = q + 1
                while j < len(code):
                    if code[j] == open_lit.text[0]:
                        if j + 1 < len(code) and code[j + 1] == open_lit.text[0]:
                            j += 2
                            continue
                        break
                    j += 1
                open_lit.text += code[q + 1:j + 1]
                i = j + 1
            open_lit = None
        while i < len(code):
            c = code[i]
            if c in " \t":
                i += 1
                continue
            col = base + i
            if expect_pic:
                j = i
                while j < len(code) and code[j] not in " \t":
                    j += 1
                pic = code[i:j]
                expect_pic = False
                if pic.upper() == "IS":
                    expect_pic = True
                    toks.append(Tok("IS", "word", rel, n, col))
                    i = j
                    continue
                period = pic.endswith(".") and (j >= len(code) or code[j] in " \t")
                if period:
                    pic = pic[:-1]
                toks.append(Tok(pic.upper(), "pic", rel, n, col))
                if period:
                    toks.append(Tok(".", "period", rel, n, col + len(pic)))
                i = j
                continue
            if c in "'\"":
                j = i + 1
                closed = False
                while j < len(code):
                    if code[j] == c:
                        if j + 1 < len(code) and code[j + 1] == c:
                            j += 2
                            continue
                        closed = True
                        break
                    j += 1
                t = Tok(code[i:j + 1], "lit", rel, n, col)
                toks.append(t)
                open_lit = None if closed else t
                i = j + 1
                continue
            if code.startswith("==", i):
                toks.append(Tok("==", "pseudo", rel, n, col))
                i += 2
                continue
            if c == ".":
                if i + 1 >= len(code) or code[i + 1] in " \t":
                    toks.append(Tok(".", "period", rel, n, col))
                    i += 1
                    continue
            if c in ",;":
                i += 1
                continue
            m = _WORD.match(code, i)
            if m:
                w = m.group(0)
                # X'..', N'..' style literals
                if len(w) == 1 and w.upper() in "XNZGB" and m.end() < len(code) and code[m.end()] in "'\"":
                    q = code[m.end()]
                    j = code.find(q, m.end() + 1)
                    j = len(code) - 1 if j < 0 else j
                    toks.append(Tok(code[i:j + 1], "lit", rel, n, col))
                    i = j + 1
                    continue
                d = _DEC.match(code, i)
                if d and d.end() > m.end() - 0 and w.isdigit():
                    toks.append(Tok(d.group(0), "num", rel, n, col))
                    i = d.end()
                    continue
                if w.startswith(":") and w.count(":") < 2:
                    toks.append(Tok(":", "punct", rel, n, col))
                    i += 1
                    continue
                if ":" in w and not w.startswith(":"):
                    w = w[:w.index(":")]
                while w.endswith("-") and len(w) > 1:
                    w = w[:-1]
                kind = "num" if w.isdigit() else "word"
                toks.append(Tok(w.upper(), kind, rel, n, col))
                i += len(w)
                if w.upper() in ("PIC", "PICTURE"):
                    expect_pic = True
                continue
            if code.startswith(">=", i) or code.startswith("<=", i) or code.startswith("**", i):
                toks.append(Tok(code[i:i + 2], "punct", rel, n, col))
                i += 2
                continue
            toks.append(Tok(c, "punct", rel, n, col))
            i += 1
    return toks


# ------------------------------------------------------------------ COPY

@dataclass
class CopyRef:
    member: str
    file: str | None       # resolved copybook path, or None if not found
    where: tuple           # (file, line) of the COPY statement
    replacing: list        # [(from_texts, to_texts)]


def _pseudo(toks, i):
    """Read ==...== or a single token starting at i; returns (texts, next index)."""
    if toks[i].kind == "pseudo":
        j = i + 1
        out = []
        while j < len(toks) and toks[j].kind != "pseudo":
            out.append(toks[j].text)
            j += 1
        return out, j + 1
    return [toks[i].text], i + 1


def _parse_copy(toks, i):
    """At a COPY token; returns (member, replacing, index after the period)."""
    j = i + 1
    if j >= len(toks):
        return None, [], j
    name = toks[j].text.strip("'\"").upper()
    j += 1
    replacing = []
    while j < len(toks) and toks[j].kind != "period":
        t = toks[j].text
        if t in ("OF", "IN"):
            j += 2
            continue
        if t in ("SUPPRESS", "PRINTING"):
            j += 1
            continue
        if t == "REPLACING":
            j += 1
            while j < len(toks) and toks[j].kind != "period":
                if toks[j].text in ("LEADING", "TRAILING"):
                    j += 1
                frm, j = _pseudo(toks, j)
                if j < len(toks) and toks[j].text == "BY":
                    j += 1
                if j >= len(toks):
                    break
                to, j = _pseudo(toks, j)
                replacing.append((frm, to))
            continue
        j += 1
    return name, replacing, j + 1


def _replace(toks, replacing):
    if not replacing:
        return toks
    out = []
    i = 0
    while i < len(toks):
        done = False
        for frm, to in replacing:
            if not frm:
                continue
            if len(frm) == 1 and toks[i].text == frm[0]:
                for k, text in enumerate(to):
                    t = toks[i]
                    out.append(Tok(text, "word" if _WORD.fullmatch(text) else "lit", t.file, t.line, t.col + k))
                i += 1
                done = True
                break
            if len(frm) > 1 and [t.text for t in toks[i:i + len(frm)]] == frm:
                t = toks[i]
                for k, text in enumerate(to):
                    out.append(Tok(text, "word", t.file, t.line, t.col + k))
                i += len(frm)
                done = True
                break
        if done:
            continue
        t = toks[i]
        text = t.text
        if t.kind == "word":
            for frm, to in replacing:
                if len(frm) == 1 and len(to) <= 1 and frm[0] != text and (":" in frm[0]) and frm[0] in text:
                    text = text.replace(frm[0], to[0] if to else "")
        out.append(Tok(text, t.kind, t.file, t.line, t.col) if text != t.text else t)
        i += 1
    return out


def expand(tree, rel, copy_dirs, _stack=()):
    """Tokens of a source with every COPY replaced by its copybook.

    Returns (tokens, copies): `copies` lists every COPY statement met, nested
    ones included, as CopyRef.
    """
    text = tree.read(rel)
    if text is None:
        return [], []
    toks = tokenize(text, rel)
    out, copies = [], []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.kind == "word" and t.text == "COPY":
            name, replacing, j = _parse_copy(toks, i)
            if name is None:
                break
            path = tree.find_member(copy_dirs, name, COPY_EXTS)
            copies.append(CopyRef(name, path, t.where, replacing))
            if path and path not in _stack and len(_stack) < 12:
                inner, inner_copies = expand(tree, path, copy_dirs, _stack + (rel,))
                for c in inner_copies:
                    copies.append(c)
                out.extend(_replace(inner, replacing))
            i = j
            continue
        out.append(t)
        i += 1
    return out, copies


# ------------------------------------------------------------------ data division

LEVELS = {f"{n:02d}" for n in range(1, 50)} | {str(n) for n in range(1, 50)} | {"66", "77", "88"}
CLAUSE_WORDS = {
    "PIC", "PICTURE", "REDEFINES", "VALUE", "VALUES", "OCCURS", "USAGE", "COMP", "COMP-1", "COMP-2",
    "COMP-3", "COMP-4", "COMP-5", "COMPUTATIONAL", "COMPUTATIONAL-3", "BINARY", "PACKED-DECIMAL",
    "DISPLAY", "INDEX", "POINTER", "SIGN", "JUSTIFIED", "JUST", "BLANK", "SYNC", "SYNCHRONIZED",
    "EXTERNAL", "GLOBAL", "RENAMES",
}
USAGES = {
    "COMP": "bin", "COMPUTATIONAL": "bin", "BINARY": "bin", "COMP-4": "bin", "COMP-5": "bin",
    "COMPUTATIONAL-4": "bin", "COMPUTATIONAL-5": "bin", "COMP-3": "packed", "COMPUTATIONAL-3": "packed",
    "PACKED-DECIMAL": "packed", "COMP-1": "f4", "COMPUTATIONAL-1": "f4", "COMP-2": "f8",
    "COMPUTATIONAL-2": "f8", "INDEX": "index", "POINTER": "ptr", "DISPLAY": "display",
}


@dataclass(eq=False)
class Item:
    level: int
    name: str              # upper case; "FILLER" for unnamed items
    lines: set             # {(file, line)} of the entry's tokens
    section: str
    fd: str | None = None  # file name when the item is a record of an FD
    parent: "Item" = None
    children: list = field(default_factory=list)
    pic: str = ""
    usage: str = ""
    occurs: int = 1
    redefines: str = ""
    sign_separate: bool = False
    value: tuple = ()
    sig: tuple = ()        # the entry's tokens without its VALUE clause
    storage: str = ""
    offset: int = 0
    size: int = 0
    span: int = 0          # bytes covered, all occurrences included

    def ancestors(self):
        p = self.parent
        while p is not None:
            yield p
            p = p.parent

    @property
    def mask(self):
        return ((1 << max(self.span, 1)) - 1) << self.offset


def _pic_size(pic, usage, sign_separate):
    s = pic.upper()
    chars = []
    i = 0
    while i < len(s):
        c = s[i]
        if i + 1 < len(s) and s[i + 1] == "(":
            j = s.find(")", i)
            try:
                rep = int(s[i + 2:j])
            except ValueError:
                rep = 1
            chars.extend([c] * rep)
            i = j + 1
            continue
        chars.append(c)
        i += 1
    digits = sum(1 for c in chars if c in "9P")
    if usage == "packed":
        return digits // 2 + 1
    if usage == "bin":
        return 2 if digits <= 4 else 4 if digits <= 9 else 8
    if usage == "f4":
        return 4
    if usage in ("f8", "ptr"):
        return 8
    if usage == "index":
        return 4
    n = sum(1 for c in chars if c not in "SVP")
    if "S" in chars and sign_separate:
        n += 1
    return n


def _sentences(toks):
    cur = []
    for t in toks:
        if t.kind == "period":
            if cur:
                yield cur
            cur = []
        else:
            cur.append(t)
    if cur:
        yield cur


def parse_data(toks):
    """Items of a DATA DIVISION token list, with sizes and offsets.

    Returns (items, fds): `fds` maps an FD name to its record items.
    """
    items, fds = [], {}
    section = "WORKING-STORAGE"
    fd = None
    stack = []
    for sent in _sentences(toks):
        w0 = sent[0].text
        if len(sent) >= 2 and sent[1].text == "SECTION":
            section = w0
            fd = None
            stack = []
            continue
        if w0 in ("FD", "SD") and len(sent) >= 2:
            fd = sent[1].text
            fds.setdefault(fd, [])
            stack = []
            continue
        if sent[0].kind != "num" or w0 not in LEVELS:
            continue
        level = int(w0)
        k = 1
        name = "FILLER"
        if k < len(sent) and sent[k].kind == "word" and sent[k].text not in CLAUSE_WORDS:
            name = sent[k].text
            k += 1
        it = Item(level, name, {t.where for t in sent}, section, fd if section == "FILE" else None)
        sig = [str(level), name]
        j = k
        while j < len(sent):
            t = sent[j].text
            if t in ("PIC", "PICTURE"):
                j += 1
                if j < len(sent) and sent[j].text == "IS":
                    j += 1
                if j < len(sent):
                    it.pic = sent[j].text
                    sig += ["PIC", it.pic]
            elif t in ("VALUE", "VALUES"):
                j += 1
                vals = []
                while j < len(sent) and sent[j].text not in CLAUSE_WORDS - {"DISPLAY"}:
                    vals.append(sent[j].text)
                    j += 1
                it.value = tuple(vals)
                continue
            elif t == "REDEFINES" and j + 1 < len(sent):
                it.redefines = sent[j + 1].text
                sig += ["REDEFINES", it.redefines]
                j += 1
            elif t == "OCCURS" and j + 1 < len(sent):
                nums = []
                jj = j + 1
                while jj < len(sent) and sent[jj].kind == "num":
                    nums.append(int(sent[jj].text))
                    jj += 1
                    if jj < len(sent) and sent[jj].text == "TO":
                        jj += 1
                if nums:
                    it.occurs = max(nums)
                sig += ["OCCURS", str(it.occurs)]
            elif t in USAGES:
                it.usage = USAGES[t]
                sig += ["USAGE", it.usage]
            elif t == "SEPARATE":
                it.sign_separate = True
                sig += ["SEPARATE"]
            elif t in ("SYNC", "SYNCHRONIZED", "JUSTIFIED", "JUST", "BLANK"):
                sig += [t]
            j += 1
        it.sig = tuple(sig)
        if level == 88:
            parent = stack[-1] if stack else None
            it.parent = parent
            if parent is not None:
                parent.children.append(it)
            items.append(it)
            continue
        if level in (1, 77) or level == 66:
            stack = []
        while stack and stack[-1].level >= level:
            stack.pop()
        if stack:
            it.parent = stack[-1]
            stack[-1].children.append(it)
        elif fd is not None and section == "FILE":
            fds[fd].append(it)
        stack.append(it)
        items.append(it)
    _layout(items, fds)
    return items, fds


def _layout(items, fds):
    by_name = {}
    for it in items:
        by_name.setdefault(it.name, []).append(it)

    def usage_of(it):
        if it.usage:
            return it.usage
        for a in it.ancestors():
            if a.usage:
                return a.usage
        return "display"

    def size(it):
        kids = [c for c in it.children if c.level != 88]
        if kids:
            total = 0
            for c in kids:
                s = size(c)
                if not c.redefines:
                    total += s * c.occurs
            it.size = total
        else:
            it.size = _pic_size(it.pic, usage_of(it), it.sign_separate) if (it.pic or usage_of(it) in ("index", "ptr", "f4", "f8")) else 0
        return it.size

    def place(it, off, storage):
        it.offset = off
        it.storage = storage
        it.span = it.size * it.occurs
        o = off
        for c in it.children:
            if c.level == 88:
                c.storage, c.offset, c.size, c.span = storage, off, it.size, it.span
                continue
            if c.redefines:
                tgt = next((s for s in it.children if s.name == c.redefines and s is not c), None)
                place(c, tgt.offset if tgt else o, storage)
                continue
            place(c, o, storage)
            o += c.size * c.occurs
        if it.occurs > 1:
            # one range for every occurrence: a subscripted reference may be any of them
            for d in _descendants(it):
                if d.level != 88:
                    d.span = max(d.span, it.span - (d.offset - it.offset))

    tops = [it for it in items if it.parent is None and it.level != 88]
    for it in tops:
        size(it)
    for n, it in enumerate(tops):
        if it.fd:
            storage = "FD:" + it.fd
        elif it.redefines and it.level == 1:
            tgt = next((s for s in by_name.get(it.redefines, []) if s.parent is None), None)
            storage = tgt.storage if tgt and tgt.storage else "WS:" + it.redefines
        else:
            storage = f"WS:{n}:{it.name}"
        place(it, 0, storage)


def _descendants(it):
    for c in it.children:
        yield c
        yield from _descendants(c)


# ------------------------------------------------------------------ procedure division

VERBS = {
    "ACCEPT", "ADD", "CALL", "CANCEL", "CLOSE", "COMPUTE", "CONTINUE", "DELETE", "DISPLAY", "DIVIDE",
    "EVALUATE", "EXIT", "GO", "GOBACK", "IF", "INITIALIZE", "INSPECT", "MERGE", "MOVE", "MULTIPLY",
    "OPEN", "PERFORM", "READ", "RELEASE", "RETURN", "REWRITE", "SEARCH", "SET", "SORT", "START",
    "STOP", "STRING", "SUBTRACT", "UNSTRING", "WRITE", "NEXT", "EXEC", "ALTER", "INITIATE",
    "GENERATE", "TERMINATE", "ENTRY",
}
IO_VERBS = {"READ", "WRITE", "REWRITE", "DELETE", "START", "RETURN"}
PHRASE_VERBS = IO_VERBS | {"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE", "CALL", "STRING", "UNSTRING", "SEARCH"}
FIGURATIVE = {
    "ZERO", "ZEROS", "ZEROES", "SPACE", "SPACES", "HIGH-VALUE", "HIGH-VALUES", "LOW-VALUE", "LOW-VALUES",
    "QUOTE", "QUOTES", "ALL", "NULL", "NULLS", "TRUE", "FALSE",
}


@dataclass(eq=False)
class Cond:
    refs: list = field(default_factory=list)    # item refs read by the condition
    marks: set = field(default_factory=set)     # file markers ("shape:F", "content:F")


@dataclass(eq=False)
class Stmt:
    verb: str
    toks: list
    para: int
    controls: list                             # enclosing Cond objects
    assigns: list = field(default_factory=list)  # [(targets, sources, marks)]
    moves: list = field(default_factory=list)    # [(targets, sources)] copied byte for byte (group moves)
    sinks: list = field(default_factory=list)    # [(sink, sources, marks)]; sink is a file name or "SYSOUT"
    own: Cond = None                           # condition this statement opens (IF, EVALUATE, UNTIL, AT END)
    performs: list = field(default_factory=list)  # [(first para, last para, extra Cond or None)]
    goto: list = field(default_factory=list)
    terminates: bool = False
    abend: bool = False
    calls: list = field(default_factory=list)

    @property
    def lines(self):
        return {t.where for t in self.toks}


@dataclass(eq=False)
class Para:
    name: str
    section: str
    index: int
    stmts: list = field(default_factory=list)
    lines: set = field(default_factory=set)


@dataclass
class SelectEntry:
    file: str
    dd: str
    organization: str = "SEQUENTIAL"
    access: str = "SEQUENTIAL"
    keys: list = field(default_factory=list)
    status: str = ""
    lines: set = field(default_factory=set)


class Program:
    """A parsed COBOL program (after COPY expansion)."""

    def __init__(self, tree, rel, copy_dirs):
        self.rel = rel
        self.member = member_of(rel)
        toks, self.copies = expand(tree, rel, copy_dirs)
        self.toks = toks
        self.cics = any(t.text == "EXEC" and i + 1 < len(toks) and toks[i + 1].text == "CICS" for i, t in enumerate(toks))
        self.name = self.member
        for i, t in enumerate(toks):
            if t.text == "PROGRAM-ID" and i + 1 < len(toks):
                j = i + 1
                if toks[j].kind == "period":
                    j += 1
                if j < len(toks):
                    self.name = toks[j].text.strip("'\"").upper()
                break
        div = {}
        for i in range(len(toks) - 1):
            if toks[i + 1].text == "DIVISION" and toks[i].text in ("IDENTIFICATION", "ID", "ENVIRONMENT", "DATA", "PROCEDURE"):
                div.setdefault(toks[i].text, i)
        n = len(toks)
        bounds = sorted(div.values()) + [n]

        def part(name):
            if name not in div:
                return []
            s = div[name]
            e = min(b for b in bounds if b > s)
            return toks[s:e]

        self.id_toks = part("IDENTIFICATION") or part("ID")
        self.env_toks = part("ENVIRONMENT")
        self.data_toks = part("DATA")
        self.proc_toks = part("PROCEDURE")
        self.items, self.fds = parse_data(self.data_toks[2:] if self.data_toks else [])
        self.by_name = {}
        for it in self.items:
            self.by_name.setdefault(it.name, []).append(it)
        self.selects = self._parse_selects()
        self.record_file = {}
        for f, recs in self.fds.items():
            for r in recs:
                self.record_file[r.name] = f
        self.using = []
        self.paras = []
        self.calls = []
        self.errors = []
        self.open_modes = {}
        mode = None
        for t in self.proc_toks:
            if t.kind == "word" and t.text == "OPEN":
                mode = "?"
            elif mode is None:
                continue
            elif t.kind == "period" or (t.kind == "word" and t.text in VERBS):
                mode = None
            elif t.text in ("INPUT", "OUTPUT", "I-O", "EXTEND"):
                mode = t.text
            elif mode != "?" and t.kind == "word" and t.text in self.selects:
                self.open_modes.setdefault(t.text, set()).add(mode)
        try:
            self._parse_procedure()
        except Exception as exc:  # recorded, never hidden: graph.errors carries it
            self.errors.append(f"{rel}: procedure division: {exc!r}")
        self.has_display = any(s.verb == "DISPLAY" for p in self.paras for s in p.stmts)

    # -------------------------------------------------- environment
    def _parse_selects(self):
        out = {}
        for sent in _sentences(self.env_toks):
            words = [t.text for t in sent]
            if "SELECT" not in words:
                continue
            k = words.index("SELECT") + 1
            if k < len(words) and words[k] == "OPTIONAL":
                k += 1
            if k >= len(words):
                continue
            se = SelectEntry(words[k], "", lines={t.where for t in sent})
            for j, w in enumerate(words):
                if w == "ASSIGN":
                    jj = j + 1
                    while jj < len(words) and words[jj] in ("TO", "USING", "EXTERNAL", "DYNAMIC"):
                        jj += 1
                    if jj < len(words):
                        dd = words[jj].strip("'\"").upper()
                        dd = dd.rsplit("-", 1)[-1] if dd.startswith(("UT-S-", "S-")) else dd
                        se.dd = dd
                elif w == "ORGANIZATION":
                    jj = j + 1 + (words[j + 1:j + 2] == ["IS"])
                    if jj < len(words):
                        se.organization = words[jj]
                elif w == "INDEXED" and (j == 0 or words[j - 1] != "ORGANIZATION"):
                    se.organization = "INDEXED"
                elif w == "ACCESS":
                    jj = j + 1
                    while jj < len(words) and words[jj] in ("MODE", "IS"):
                        jj += 1
                    if jj < len(words):
                        se.access = words[jj]
                elif w == "KEY" and j > 0 and words[j - 1] == "RECORD" and (j < 2 or words[j - 2] != "RELATIVE"):
                    jj = j + 1 + (words[j + 1:j + 2] == ["IS"])
                    if jj < len(words):
                        se.keys.append(words[jj])
                elif w == "STATUS" and j > 0 and words[j - 1] == "FILE":
                    jj = j + 1 + (words[j + 1:j + 2] == ["IS"])
                    if jj < len(words):
                        se.status = words[jj]
            out[se.file] = se
        return out

    # -------------------------------------------------- references
    def resolve(self, toks):
        """Item refs named in a token list (qualifiers and FUNCTION names handled)."""
        refs = []
        i = 0
        while i < len(toks):
            t = toks[i]
            if t.kind != "word" or t.text in FIGURATIVE:
                i += 1
                continue
            if t.text == "FUNCTION":
                i += 2
                continue
            cands = self.by_name.get(t.text)
            if not cands:
                i += 1
                continue
            j = i + 1
            while j + 1 < len(toks) and toks[j].text in ("OF", "IN"):
                q = toks[j + 1].text
                narrowed = [c for c in cands if any(a.name == q for a in c.ancestors())]
                if q in self.fds:
                    narrowed = [c for c in cands if any(a.fd == q for a in [c, *c.ancestors()])] or narrowed
                cands = narrowed or cands
                j += 2
            refs.extend(cands)
            i = j
        return refs

    def file_of(self, name):
        """The FD file for a file name or a record name."""
        if name in self.selects or name in self.fds:
            return name
        if name in self.record_file:
            return self.record_file[name]
        for it in self.by_name.get(name, []):
            for a in [it, *it.ancestors()]:
                if a.fd:
                    return a.fd
        return None

    def record_items(self, f):
        return list(self.fds.get(f, []))

    def key_items(self, f):
        se = self.selects.get(f)
        if not se:
            return []
        out = []
        for k in se.keys:
            out.extend(self.by_name.get(k, []))
        return out

    def status_items(self, f):
        se = self.selects.get(f)
        return list(self.by_name.get(se.status, [])) if se and se.status else []

    # -------------------------------------------------- procedure division
    def _parse_procedure(self):
        toks = self.proc_toks
        if not toks:
            return
        i = 2
        while i < len(toks) and toks[i].kind != "period":
            if toks[i].kind == "word" and toks[i].text not in ("USING", "BY", "REFERENCE", "VALUE", "CONTENT"):
                self.using.extend(self.by_name.get(toks[i].text, []))
            i += 1
        body = toks[i + 1:]
        # paragraphs and sections
        heads = []
        for k, t in enumerate(body):
            if t.kind in ("word", "num") and t.col <= 11 and (k == 0 or body[k - 1].kind == "period"):
                if k + 1 < len(body) and body[k + 1].kind == "period":
                    heads.append((k, t.text, False))
                elif k + 2 < len(body) and body[k + 1].text == "SECTION" and body[k + 2].kind == "period":
                    heads.append((k, t.text, True))
        self.sections = {}
        segs = []
        start = 0
        cur_name, cur_section = "(MAIN)", ""
        for k, name, is_section in heads:
            segs.append((cur_name, cur_section, body[start:k]))
            if is_section:
                cur_section = name
                cur_name = name
                start = k + 3
            else:
                cur_name = name
                start = k + 2
        segs.append((cur_name, cur_section, body[start:]))
        for name, section, seg in segs:
            if name == "(MAIN)" and not seg:
                continue
            p = Para(name, section, len(self.paras))
            p.lines = {t.where for t in seg}
            self.paras.append(p)
            if section:
                self.sections.setdefault(section, []).append(p.index)
        self.para_index = {}
        for p in self.paras:
            self.para_index.setdefault(p.name, p.index)
        for p in self.paras:
            seg = next(s for (n, sec, s) in segs if n == p.name and sec == p.section)
            self._parse_stmts(p, seg)

    def _targets_of(self, name):
        if name in self.sections and name not in self.para_index:
            idx = self.sections[name]
            return (idx[0], idx[-1])
        if name in self.sections:
            idx = self.sections[name]
            return (idx[0], idx[-1])
        if name in self.para_index:
            i = self.para_index[name]
            return (i, i)
        return None

    def _is_para(self, t):
        return t.kind in ("word", "num") and (t.text in self.para_index or t.text in self.sections)

    def _parse_stmts(self, para, toks):
        frames = []  # [kind, cond, owner, in_else]
        n = len(toks)
        i = 0

        def controls():
            return [f[1] for f in frames if f[1] is not None]

        def stop_at(j, phrase_ok=True):
            t = toks[j]
            if t.kind == "period":
                return True
            if t.kind != "word":
                return False
            w = t.text
            if w in VERBS or w.startswith("END-") or w in ("ELSE", "WHEN", "THEN"):
                if w == "NEXT" and not (j + 1 < n and toks[j + 1].text == "SENTENCE"):
                    return False
                return True
            if phrase_ok and _phrase_at(toks, j):
                return True
            return False

        while i < n:
            t = toks[i]
            w = t.text
            if t.kind == "period":
                frames.clear()
                i += 1
                continue
            if w == "ELSE":
                while frames and not (frames[-1][0] == "IF" and not frames[-1][3]):
                    frames.pop()
                if frames:
                    frames[-1][3] = True
                i += 1
                continue
            if w.startswith("END-") and t.kind == "word":
                owner = w[4:]
                if any(f[2] == owner for f in frames):
                    while frames:
                        f = frames.pop()
                        if f[2] == owner:
                            break
                i += 1
                continue
            if w == "WHEN":
                while frames and frames[-1][0] != "EVAL":
                    frames.pop()
                j = i + 1
                while j < n and not stop_at(j, phrase_ok=False):
                    j += 1
                if frames:
                    frames[-1][1].refs.extend(self.resolve(toks[i + 1:j]))
                i = j
                continue
            if w == "THEN":
                i += 1
                continue
            ph = _phrase_at(toks, i)
            if ph:
                owner_frame = None
                while frames and frames[-1][0] == "PHRASE":
                    owner_frame = frames.pop()
                cond = owner_frame[1] if owner_frame else (self._last_phrase_cond if hasattr(self, "_last_phrase_cond") else None)
                frames.append(["PHRASE", cond, owner_frame[2] if owner_frame else getattr(self, "_last_phrase_owner", ""), False])
                i += ph
                continue
            if t.kind != "word" or w not in VERBS:
                i += 1
                continue
            # a statement
            if w == "IF":
                j = i + 1
                while j < n and not stop_at(j, phrase_ok=False):
                    j += 1
                cond = Cond(self.resolve(toks[i + 1:j]))
                st = Stmt("IF", toks[i:j], para.index, controls(), own=cond)
                para.stmts.append(st)
                frames.append(["IF", cond, "IF", False])
                i = j
                continue
            if w == "EVALUATE":
                j = i + 1
                while j < n and toks[j].text != "WHEN" and toks[j].kind != "period":
                    j += 1
                cond = Cond(self.resolve(toks[i + 1:j]))
                st = Stmt("EVALUATE", toks[i:j], para.index, controls(), own=cond)
                para.stmts.append(st)
                frames.append(["EVAL", cond, "EVALUATE", False])
                i = j
                continue
            if w == "PERFORM":
                j = i + 1
                if j < n and self._is_para(toks[j]):
                    first = self._targets_of(toks[j].text)
                    last = first
                    j += 1
                    if j + 1 < n and toks[j].text in ("THRU", "THROUGH") and self._is_para(toks[j + 1]):
                        last = self._targets_of(toks[j + 1].text)
                        j += 2
                    k = j
                    while k < n and not stop_at(k):
                        k += 1
                    extra = toks[j:k]
                    cond = Cond(self.resolve(extra)) if extra else None
                    st = Stmt("PERFORM", toks[i:k], para.index, controls())
                    if extra:
                        st.assigns.append((self._varying_targets(extra), self.resolve(extra), set()))
                    st.performs.append((first[0], last[1], cond))
                    para.stmts.append(st)
                    i = k
                    continue
                k = j
                while k < n and not stop_at(k):
                    k += 1
                extra = toks[j:k]
                cond = Cond(self.resolve(extra))
                st = Stmt("PERFORM", toks[i:k], para.index, controls(), own=cond)
                if extra:
                    st.assigns.append((self._varying_targets(extra), self.resolve(extra), set()))
                para.stmts.append(st)
                frames.append(["PERFORM", cond, "PERFORM", False])
                i = k
                continue
            j = i + 1
            if w == "EXEC":
                while j < n and toks[j].text != "END-EXEC":
                    j += 1
                j = min(j + 1, n)
                st = Stmt("EXEC", toks[i:j], para.index, controls())
                refs = self.resolve(toks[i:j])
                st.assigns.append((refs, refs, set()))
                para.stmts.append(st)
                i = j
                continue
            while j < n and not stop_at(j):
                j += 1
            st = Stmt(w, toks[i:j], para.index, controls())
            self._semantics(st, toks[i + 1:j])
            para.stmts.append(st)
            if w in PHRASE_VERBS and j < n and _phrase_at(toks, j):
                cond = Cond(list(st.own.refs) if st.own else [], set(st.own.marks) if st.own else set())
                st.own = cond
                self._last_phrase_cond = cond
                self._last_phrase_owner = w
            i = j

    def _varying_targets(self, extra):
        out = []
        for k, t in enumerate(extra):
            if t.text == "VARYING" or t.text == "AFTER":
                out.extend(self.resolve(extra[k + 1:k + 2]))
        return out

    # -------------------------------------------------- statement semantics
    def _split(self, ops, word):
        for k, t in enumerate(ops):
            if t.text == word:
                return ops[:k], ops[k + 1:]
        return ops, None

    def _top(self, ops):
        """Refs at parenthesis depth 0 (targets) and refs inside parentheses (subscripts)."""
        top, inner = [], []
        depth = 0
        buf_top, buf_in = [], []
        for t in ops:
            if t.text == "(":
                depth += 1
                continue
            if t.text == ")":
                depth = max(0, depth - 1)
                continue
            (buf_top if depth == 0 else buf_in).append(t)
        top = self.resolve(buf_top)
        inner = self.resolve(buf_in)
        return top, inner

    def _semantics(self, st, ops):
        v = st.verb
        R = self.resolve
        if v == "MOVE":
            src, dst = self._split(ops, "TO")
            if dst is not None:
                tgt, sub = self._top(dst)
                srcs = R(src)
                if len(srcs) == 1 and "(" not in [t.text for t in src] and src and src[0].text not in ("CORR", "CORRESPONDING"):
                    st.moves.append((tgt, srcs))
                    if sub:
                        st.assigns.append((tgt, sub, set()))
                else:
                    st.assigns.append((tgt, srcs + sub, set()))
        elif v == "COMPUTE":
            k = next((k for k, t in enumerate(ops) if t.text in ("=", "EQUAL")), None)
            if k is not None:
                tgt, sub = self._top(ops[:k])
                st.assigns.append((tgt, R(ops[k + 1:]) + sub, set()))
            st.own = Cond(R(ops))
        elif v in ("ADD", "SUBTRACT", "MULTIPLY", "DIVIDE"):
            words = [t.text for t in ops]
            if "GIVING" in words:
                k = words.index("GIVING")
                tgt, sub = self._top(ops[k + 1:])
                st.assigns.append((tgt, R(ops[:k]) + sub, set()))
            else:
                sep = {"ADD": "TO", "SUBTRACT": "FROM", "MULTIPLY": "BY", "DIVIDE": "INTO"}[v]
                if v == "DIVIDE" and "INTO" not in words:
                    sep = "BY"
                src, dst = self._split(ops, sep)
                if dst is not None:
                    tgt, sub = self._top(dst)
                    st.assigns.append((tgt, R(src) + tgt + sub, set()))
            st.own = Cond(R(ops))
        elif v == "INITIALIZE":
            dst, rep = self._split(ops, "REPLACING")
            tgt, sub = self._top(dst)
            st.assigns.append((tgt, sub + (R(rep) if rep else []), set()))
        elif v == "SET":
            words = [t.text for t in ops]
            if "TO" in words:
                k = words.index("TO")
                tgt, sub = self._top(ops[:k])
                real = []
                for it in tgt:
                    real.append(it.parent if it.level == 88 and it.parent else it)
                src = R(ops[k + 1:]) + sub + [it for it in tgt if it.level == 88]
                st.assigns.append((real, src, set()))
            else:
                refs = R(ops)
                st.assigns.append((refs, refs, set()))
        elif v == "STRING":
            src, dst = self._split(ops, "INTO")
            if dst is not None:
                tgt = R(dst)
                st.assigns.append((tgt, R(src) + tgt, set()))
            st.own = Cond(R(ops))
        elif v == "UNSTRING":
            src, dst = self._split(ops, "INTO")
            if dst is not None:
                tgt = R(dst)
                st.assigns.append((tgt, R(src) + tgt, set()))
            st.own = Cond(R(ops))
        elif v == "INSPECT":
            refs = R(ops)
            st.assigns.append((refs, refs, set()))
        elif v == "ACCEPT":
            src, _ = self._split(ops, "FROM")
            st.assigns.append((R(src), [], set()))
        elif v == "DISPLAY":
            src, _ = self._split(ops, "UPON")
            st.sinks.append(("SYSOUT", R(src), set()))
        elif v in ("READ", "RETURN"):
            f = self.file_of(ops[0].text) if ops else None
            if f:
                words = [t.text for t in ops]
                into = R(ops[words.index("INTO") + 1:words.index("INTO") + 2]) if "INTO" in words else []
                se = self.selects.get(f)
                keyed = se is not None and se.organization == "INDEXED" and se.access in ("RANDOM", "DYNAMIC") and "NEXT" not in words
                keys = (R(ops[words.index("KEY") + 1:]) if "KEY" in words else self.key_items(f)) if keyed else []
                marks = {"content:" + f, "shape:" + f}
                recs = [it for r in self.record_items(f) for it in [r]]
                st.assigns.append((recs, keys, marks))
                if into:
                    st.moves.append((into, recs))
                    st.assigns.append((into, keys, marks))
                st.assigns.append((self.status_items(f), keys, {"shape:" + f}))
                st.own = Cond(keys, {"shape:" + f})
                st.calls.append(("io", f))
        elif v in ("WRITE", "REWRITE"):
            if ops:
                f = self.file_of(ops[0].text)
                if f:
                    words = [t.text for t in ops]
                    rec = R(ops[:1])
                    frm = R(ops[words.index("FROM") + 1:words.index("FROM") + 2]) if "FROM" in words else []
                    if frm:
                        st.moves.append((rec, frm))
                    se = self.selects.get(f)
                    keys = self.key_items(f) if se is not None and se.organization == "INDEXED" else []
                    adv = R(ops[words.index("ADVANCING"):]) if "ADVANCING" in words else []
                    st.sinks.append((f, rec + frm + adv, {"shape:" + f}))
                    st.assigns.append((self.status_items(f), keys + (frm if keys else []), {"shape:" + f}))
                    st.own = Cond(keys + (frm if keys else []), {"shape:" + f})
                    st.calls.append(("io", f))
        elif v in ("DELETE", "START"):
            f = self.file_of(ops[0].text) if ops else None
            if f:
                keys = self.key_items(f) + R(ops[1:])
                if v == "DELETE":
                    st.sinks.append((f, keys, {"shape:" + f}))
                st.assigns.append((self.status_items(f), keys, {"shape:" + f}))
                st.own = Cond(keys, {"shape:" + f})
                st.calls.append(("io", f))
        elif v in ("OPEN", "CLOSE"):
            for t in ops:
                f = self.file_of(t.text) if t.kind == "word" else None
                if f:
                    st.assigns.append((self.status_items(f), [], {"shape:" + f}))
                    modes = self.open_modes.get(f, set()) if v == "CLOSE" else set()
                    if v == "OPEN" or modes & {"OUTPUT", "EXTEND", "I-O"}:
                        st.sinks.append((f, [], {"shape:" + f}))
                    st.calls.append(("io", f))
        elif v == "CALL":
            target = ops[0].text.strip("'\"").upper() if ops else ""
            args = R(ops[1:])
            st.calls.append(("call", target))
            self.calls.append(target)
            if target == "CEE3ABD":
                st.abend = True
            else:
                st.assigns.append((args, args, set()))
        elif v in ("STOP", "GOBACK") or (v == "EXIT" and ops and ops[0].text == "PROGRAM"):
            st.terminates = True
        elif v == "GO":
            names = [t.text for t in ops if t.text != "TO"]
            for nme in names:
                tg = self._targets_of(nme)
                if tg:
                    st.goto.append(tg[0])
        elif v in ("CONTINUE", "EXIT", "NEXT"):
            pass
        else:
            refs = R(ops)
            st.assigns.append((refs, refs, set()))
            st.own = Cond(refs)


def _phrase_at(toks, j):
    """Length of an exception phrase (AT END, INVALID KEY, ...) starting at j, or 0."""
    w = [t.text for t in toks[j:j + 4]]
    pats = (
        ["NOT", "AT", "END"], ["NOT", "INVALID", "KEY"], ["NOT", "INVALID"], ["NOT", "ON", "SIZE", "ERROR"],
        ["NOT", "SIZE", "ERROR"], ["NOT", "ON", "OVERFLOW"], ["NOT", "ON", "EXCEPTION"], ["NOT", "END"],
        ["AT", "END"], ["INVALID", "KEY"], ["INVALID"], ["ON", "SIZE", "ERROR"], ["SIZE", "ERROR"],
        ["ON", "OVERFLOW"], ["OVERFLOW"], ["ON", "EXCEPTION"], ["EXCEPTION"], ["AT", "EOP"], ["AT", "END-OF-PAGE"],
    )
    for p in pats:
        if w[:len(p)] == p:
            return len(p)
    return 0


# ------------------------------------------------------------------ reachability

def reachable(prog):
    """Indexes of paragraphs that can run, and of those that can be entered by falling into them."""
    if not prog.paras:
        return set(), set()
    reach, flow = set(), set()
    todo = [(0, True)]
    while todo:
        k, by_flow = todo.pop()
        if k >= len(prog.paras):
            continue
        if k in reach and (not by_flow or k in flow):
            continue
        reach.add(k)
        if by_flow:
            flow.add(k)
        p = prog.paras[k]
        for s in p.stmts:
            for a, b, _ in s.performs:
                for m in range(a, max(a, b) + 1):
                    todo.append((m, False))
            for g in s.goto:
                todo.append((g, True))
        if by_flow and not _ends_flow(p):
            todo.append((k + 1, True))
    return reach, flow


def _ends_flow(p):
    for s in reversed(p.stmts):
        if s.controls:
            return False
        if s.terminates or s.goto or s.abend:
            return True
        return False
    return False


# ------------------------------------------------------------------ taint analysis


class Taint:
    """Byte-level taint over a program's storage, plus file markers and changed 88-levels."""

    def __init__(self):
        self.mem = {}
        self.marks = set()
        self.conds88 = set()

    def hit(self, refs, marks=()):
        for it in refs:
            if it in self.conds88:
                return True
            if it.storage and self.mem.get(it.storage, 0) & it.mask:
                return True
        return any(m in self.marks for m in marks)

    def add(self, refs):
        grew = False
        for it in refs:
            if not it.storage:
                continue
            old = self.mem.get(it.storage, 0)
            new = old | it.mask
            if new != old:
                self.mem[it.storage] = new
                grew = True
        return grew

    def move(self, tgts, srcs):
        """A MOVE: a group to a group copies the tainted bytes at the same relative offsets."""
        grew = False
        for src in srcs:
            if src in self.conds88:
                grew |= self.add(tgts)
                continue
            bits = self.mem.get(src.storage, 0) & src.mask if src.storage else 0
            if not bits:
                continue
            for t in tgts:
                if not t.storage:
                    continue
                if (src.children or t.children or src.size == t.size) and not (src.occurs > 1 or t.occurs > 1):
                    rel = bits >> src.offset
                    new = (rel << t.offset) & t.mask
                    if t.size > src.size:  # padding past the source's end changes with it
                        new |= ((1 << (t.size - src.size)) - 1) << (t.offset + src.size) if (bits >> (src.offset + src.size - 1)) & 1 else 0
                    if not new:
                        continue
                    old = self.mem.get(t.storage, 0)
                    if old | new != old:
                        self.mem[t.storage] = old | new
                        grew = True
                else:
                    grew |= self.add([t])
        return grew

    def add_range(self, storage, start, end):
        old = self.mem.get(storage, 0)
        new = old | (((1 << max(end - start, 1)) - 1) << start)
        self.mem[storage] = new
        return new != old

    def mark(self, m):
        if m in self.marks:
            return False
        self.marks.add(m)
        return True


def analyse(prog, taint, seeded, ctx_seed=(), all_out=False):
    """Run the taint to a fixed point over the reachable statements.

    `seeded` is a set of statements the change edits; `ctx_seed` paragraph
    indexes whose every statement may run differently. Returns a dict: sink
    (file name or "SYSOUT") -> "shape" or "content", and flags `terminates`
    and `abend` for a change in whether the program stops or abends.
    """
    reach, flow = reachable(prog)
    stmts = [s for k in sorted(reach) for s in prog.paras[k].stmts]
    seeded = {s for s in seeded if s.para in reach}
    ctx = set(ctx_seed) & reach
    sinks = {}
    flags = {"terminates": False, "abend": False}
    cond_hot = set()

    def chot(c):
        if c is None:
            return False
        if id(c) in cond_hot:
            return True
        if taint.hit(c.refs, c.marks):
            cond_hot.add(id(c))
            return True
        return False

    changed = True
    rounds = 0
    while changed and rounds < 200:
        changed = False
        rounds += 1
        for s in stmts:
            ctrl = s in seeded or s.para in ctx or any(chot(c) for c in s.controls)
            if s in seeded and s.own is not None and id(s.own) not in cond_hot:
                cond_hot.add(id(s.own))
                changed = True
            for tgts, srcs, marks in s.assigns:
                if ctrl or taint.hit(srcs, marks):
                    if taint.add(tgts):
                        changed = True
            for tgts, srcs in s.moves:
                if (taint.add(tgts) if ctrl else taint.move(tgts, srcs)):
                    changed = True
            for sink, srcs, marks in s.sinks:
                level = "shape" if (ctrl or any(m in taint.marks for m in marks)) else ("content" if taint.hit(srcs) else None)
                if level and _better(level, sinks.get(sink)):
                    sinks[sink] = level
                    changed = True
            for a, b, extra in s.performs:
                if ctrl or chot(extra):
                    for m in range(a, max(a, b) + 1):
                        if m in reach and m not in ctx:
                            ctx.add(m)
                            changed = True
            if ctrl and s.goto:
                for g in s.goto:
                    if g in reach and g not in ctx:
                        ctx.add(g)
                        changed = True
                if not flags["terminates"]:
                    flags["terminates"] = True
                    changed = True
            if ctrl and s.terminates and not flags["terminates"]:
                flags["terminates"] = True
                changed = True
            if ctrl and s.abend and not flags["abend"]:
                flags["abend"] = True
                changed = True
        # falling out of a paragraph whose flow is affected affects the next one
        for k in sorted(ctx):
            if k in flow and k + 1 in flow and k + 1 not in ctx and not _ends_flow(prog.paras[k]):
                ctx.add(k + 1)
                changed = True
    if all_out or flags["terminates"] or flags["abend"]:
        for f in prog.selects:
            if prog.open_modes.get(f, set()) & {"OUTPUT", "EXTEND", "I-O"}:
                sinks[f] = "shape"
        if prog.has_display:
            sinks["SYSOUT"] = "shape"
    return sinks, flags


def _better(new, old):
    rank = {None: 0, "content": 1, "shape": 2}
    return rank[new] > rank[old]
