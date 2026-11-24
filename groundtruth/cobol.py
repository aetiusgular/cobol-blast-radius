"""GnuCOBOL builds for the harness: run-set programs, the step driver, stubs,
and the indexed-file (KSDS) loader that stands in for VSAM.

Every cobc call that decides ground truth uses the run set's `cobc_flags`
(contracts/runset.md) plus -I for each copy dir and the output flags.
"""
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

STUB_DIR = Path(__file__).resolve().parent / "stubs"

DRIVER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GTDRIVER.
      * Harness step driver: CALLs the step's program with an IBM-style
      * PARM area (halfword length, then the text), as z/OS passes it.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PROG                PIC X(30).
       01  WS-LEN-TXT             PIC X(4).
       01  WS-PARM-AREA.
           05  WS-PARM-LEN        PIC S9(4) COMP.
           05  WS-PARM-TEXT       PIC X(100).
       PROCEDURE DIVISION.
           ACCEPT WS-PROG FROM ENVIRONMENT 'GT_PROGRAM'
           ACCEPT WS-PARM-TEXT FROM ENVIRONMENT 'GT_PARM'
           ACCEPT WS-LEN-TXT FROM ENVIRONMENT 'GT_PARM_LEN'
           MOVE FUNCTION NUMVAL(WS-LEN-TXT) TO WS-PARM-LEN
           CALL WS-PROG USING WS-PARM-AREA
           STOP RUN.
"""


def cobc():
    path = shutil.which("cobc")
    if not path:
        raise RuntimeError("cobc not found: run scripts/setup.sh")
    return path


def cobc_version():
    out = subprocess.run([cobc(), "--version"], capture_output=True, text=True).stdout
    return out.splitlines()[0].strip() if out else ""


def find_source(src_root, program_dirs, name):
    for d in program_dirs:
        folder = Path(src_root) / d
        if not folder.is_dir():
            continue
        for p in sorted(folder.iterdir()):
            if p.is_file() and p.stem.upper() == name.upper() and p.suffix.lower() in (".cbl", ".cob"):
                return p
    return None


def _trim(text):
    return "\n".join(ln.rstrip() for ln in text.strip().splitlines())


def compile_program(src_root, runset, name, out_dir):
    """Build `name` as a module in out_dir. Returns {"ok", "diagnostics"}.

    cobc runs inside src_root with relative paths, so the diagnostics name
    files the same way in every run and the result repeats byte for byte.
    """
    src = find_source(src_root, runset.get("program_dirs", []), name)
    if src is None:
        return {"ok": False, "diagnostics": f"no source for {name} in {runset.get('program_dirs')}"}
    rel = src.relative_to(src_root)
    incs = []
    for d in runset.get("copy_dirs", []):
        incs += ["-I", d]
    out = Path(out_dir) / f"{name.upper()}.so"
    cmd = [cobc(), "-m", *runset.get("cobc_flags", []), *incs, "-o", str(out), str(rel)]
    r = subprocess.run(cmd, cwd=src_root, capture_output=True, text=True,
                       env=_build_env())
    ok = r.returncode == 0 and out.is_file()
    return {"ok": ok, "diagnostics": _trim(r.stderr + r.stdout).replace(str(out_dir), "<mod>")}


def syntax_ok(src_root, runset, name):
    """`cobc -fsyntax-only` with the run set's flags, as the generator checks a change."""
    src = find_source(src_root, runset.get("program_dirs", []), name)
    if src is None:
        return False, f"no source for {name}"
    incs = []
    for d in runset.get("copy_dirs", []):
        incs += ["-I", d]
    r = subprocess.run([cobc(), "-fsyntax-only", *runset.get("cobc_flags", []), *incs,
                        str(src.relative_to(src_root))],
                       cwd=src_root, capture_output=True, text=True, env=_build_env())
    return r.returncode == 0, _trim(r.stderr + r.stdout)


def _build_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith(("COB_", "DD_", "dd_"))}
    env["LC_ALL"] = "C"
    return env


def build_exe(source_text, name, flags, out_dir):
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    src = d / f"{name}.cbl"
    src.write_text(source_text)
    exe = d / name
    r = subprocess.run([cobc(), "-x", *flags, "-o", str(exe), str(src)],
                       capture_output=True, text=True, env=_build_env())
    if r.returncode != 0:
        raise RuntimeError(f"harness build of {name} failed:\n{r.stderr}")
    return exe


def build_module(source_path, flags, out_dir):
    name = Path(source_path).stem.upper()
    out = Path(out_dir) / f"{name}.so"
    r = subprocess.run([cobc(), "-m", *flags, "-o", str(out), str(source_path)],
                       capture_output=True, text=True, env=_build_env())
    if r.returncode != 0:
        raise RuntimeError(f"harness build of stub {name} failed:\n{r.stderr}")
    return out


def stub_source(name):
    p = STUB_DIR / f"{name.upper()}.cbl"
    return p if p.is_file() else None


# ------------------------------------------------------------------ KSDS loader
def _rec(prefix, recsize, off, length):
    lines = [f"       01  {prefix}."]
    if off:
        lines.append(f"           05  FILLER             PIC X({off}).")
    lines.append(f"           05  {prefix}-K          PIC X({length}).")
    rest = recsize - off - length
    if rest:
        lines.append(f"           05  FILLER             PIC X({rest}).")
    return lines


def loader_source(recsize, key, alts):
    """A COBOL program that creates, loads or unloads one indexed file shape.

    GT_MODE: CREATE (empty file), LOAD (GTSEQ fixed records -> GTKSDS, random
    WRITE), UNLOAD (GTKSDS in primary key order -> GTSEQ). Prints
    "GTKS <mode> <records> <bad>" and sets RETURN-CODE 8 when a record was
    refused (duplicate key), 12 when a file did not open.
    """
    sel = [
        "           SELECT SEQ-F ASSIGN TO GTSEQ",
        "               ORGANIZATION IS SEQUENTIAL",
        "               FILE STATUS IS WS-SS.",
        "           SELECT KS-F ASSIGN TO GTKSDS",
        "               ORGANIZATION IS INDEXED",
        "               ACCESS MODE IS DYNAMIC",
        "               RECORD KEY IS KR0-K",
    ]
    for n, (off, length, dups) in enumerate(alts, start=1):
        sel.append(f"               ALTERNATE RECORD KEY IS KR{n}-K"
                   + (" WITH DUPLICATES" if dups else ""))
    sel.append("               FILE STATUS IS WS-KS.")
    recs = _rec("KR0", recsize, key[0], key[1])
    for n, (off, length, _) in enumerate(alts, start=1):
        recs += _rec(f"KR{n}", recsize, off, length)
    src = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. GTKSDS.",
        "       ENVIRONMENT DIVISION.",
        "       INPUT-OUTPUT SECTION.",
        "       FILE-CONTROL.",
        *sel,
        "       DATA DIVISION.",
        "       FILE SECTION.",
        "       FD  SEQ-F.",
        f"       01  SEQ-REC                PIC X({recsize}).",
        "       FD  KS-F.",
        *recs,
        "       WORKING-STORAGE SECTION.",
        "       01  WS-SS                  PIC XX.",
        "       01  WS-KS                  PIC XX.",
        "       01  WS-MODE                PIC X(8).",
        "       01  WS-N                   PIC 9(9) VALUE 0.",
        "       01  WS-BAD                 PIC 9(9) VALUE 0.",
        "       PROCEDURE DIVISION.",
        "           ACCEPT WS-MODE FROM ENVIRONMENT 'GT_MODE'",
        "           EVALUATE WS-MODE",
        "           WHEN 'CREATE'",
        "               OPEN OUTPUT KS-F",
        "               IF WS-KS NOT = '00'",
        "                   DISPLAY 'GTKS OPEN ' WS-KS",
        "                   MOVE 12 TO RETURN-CODE",
        "                   STOP RUN",
        "               END-IF",
        "               CLOSE KS-F",
        "           WHEN 'LOAD'",
        "               OPEN INPUT SEQ-F",
        "               OPEN I-O KS-F",
        "               IF WS-SS NOT = '00' OR WS-KS NOT = '00'",
        "                   DISPLAY 'GTKS OPEN ' WS-SS ' ' WS-KS",
        "                   MOVE 12 TO RETURN-CODE",
        "                   STOP RUN",
        "               END-IF",
        "               PERFORM UNTIL WS-SS NOT = '00'",
        "                   READ SEQ-F",
        "                   IF WS-SS = '00'",
        "                       MOVE SEQ-REC TO KR0",
        "                       WRITE KR0",
        "                       IF WS-KS = '00' OR WS-KS = '02'",
        "                           ADD 1 TO WS-N",
        "                       ELSE",
        "                           ADD 1 TO WS-BAD",
        "                       END-IF",
        "                   END-IF",
        "               END-PERFORM",
        "               CLOSE SEQ-F KS-F",
        "           WHEN 'UNLOAD'",
        "               OPEN INPUT KS-F",
        "               OPEN OUTPUT SEQ-F",
        "               IF WS-SS NOT = '00' OR WS-KS NOT = '00'",
        "                   DISPLAY 'GTKS OPEN ' WS-SS ' ' WS-KS",
        "                   MOVE 12 TO RETURN-CODE",
        "                   STOP RUN",
        "               END-IF",
        "               PERFORM UNTIL WS-KS NOT = '00' AND WS-KS NOT = '02'",
        "                   READ KS-F NEXT RECORD",
        "                   IF WS-KS = '00' OR WS-KS = '02'",
        "                       MOVE KR0 TO SEQ-REC",
        "                       WRITE SEQ-REC",
        "                       ADD 1 TO WS-N",
        "                   END-IF",
        "               END-PERFORM",
        "               CLOSE SEQ-F KS-F",
        "           END-EVALUATE",
        "           DISPLAY 'GTKS ' WS-MODE ' ' WS-N ' ' WS-BAD",
        "           IF WS-BAD > 0",
        "               MOVE 8 TO RETURN-CODE",
        "           END-IF",
        "           STOP RUN.",
    ]
    return "\n".join(src) + "\n"


class Toolchain:
    """Per-run build cache: the driver, stubs and one loader per indexed-file shape."""

    def __init__(self, work, flags):
        self.dir = Path(work) / "bin"
        self.mod = Path(work) / "mod"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.mod.mkdir(parents=True, exist_ok=True)
        self.flags = list(flags)
        self._loaders = {}
        self._driver = None

    def driver(self):
        if self._driver is None:
            self._driver = build_exe(DRIVER, "GTDRIVER", self.flags, self.dir)
        return self._driver

    def loader(self, recsize, key, alts):
        shape = (recsize, tuple(key), tuple(tuple(a) for a in alts))
        if shape not in self._loaders:
            tag = hashlib.sha256(repr(shape).encode()).hexdigest()[:12]
            self._loaders[shape] = build_exe(loader_source(recsize, key, alts), f"GTKS{tag}",
                                             self.flags, self.dir)
        return self._loaders[shape]

    def run_loader(self, recsize, key, alts, mode, ksds_path, seq_path=None):
        exe = self.loader(recsize, key, alts)
        env = _build_env()
        env.update({"GT_MODE": mode, "DD_GTKSDS": str(ksds_path),
                    "DD_GTSEQ": str(seq_path or os.devnull)})
        r = subprocess.run([str(exe)], capture_output=True, text=True, env=env, timeout=600)
        words = r.stdout.split()
        n = bad = 0
        if len(words) >= 4 and words[0] == "GTKS":
            n, bad = int(words[2]), int(words[3])
        return r.returncode, n, bad, r.stdout + r.stderr
