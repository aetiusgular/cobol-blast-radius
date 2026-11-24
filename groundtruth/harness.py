"""Run the run set under GnuCOBOL and record every output (contracts/ground-truth.md).

    run(root, runset, workdir, change=None) -> run result

The harness copies `root` into `workdir`, applies `change` to the copy, builds
every run-set program with the run set's `cobc_flags`, runs the jobs in order
with its own JCL step runner, and hashes the canonical bytes of every output.
It never writes under `root`. It never imports the predictor (radius/).
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import changes as gtchanges
from . import cobol, jcl, utilities
from .catalog import GDG_REF, MEMBER_REF, Catalog, Unsupported

REPO = Path(__file__).resolve().parent.parent
STEP_TIMEOUT = 300
SYSOUT_DD_STDOUT = "SYSOUT"   # DISPLAY goes to the SYSOUT DD, as under Language Environment


def pinned_clock(clock):
    """The COB_CURRENT_DATE value the harness uses for the run set's `clock`.

    libcob fills any part the value leaves out from the system clock, so a
    clock without a fraction of a second still moves FUNCTION CURRENT-DATE's
    hundredths. The harness pins the fraction to .00 (and runs with TZ=UTC,
    so the offset is the same on every machine). DECISIONS.md, P3a.
    """
    if not clock:
        return clock
    if re.search(r"\d\d:\d\d:\d\d$", clock):
        return clock + ".00"
    return clock


class JobEnd(Exception):
    """An allocation failure: the job stops here, like a JCL error."""


# ---------------------------------------------------------------------- helpers
def _disp(params):
    d = params.get("DISP")
    if d is None:
        vals = []
    elif isinstance(d, str):
        vals = [d]
    else:
        vals = [x if isinstance(x, str) else "" for x in d]
    vals = [v.upper() for v in vals] + [""] * 3
    status = vals[0] or "NEW"
    normal = vals[1] or ("DELETE" if status == "NEW" else "KEEP")
    abnormal = vals[2] or normal
    return status, normal, abnormal


def _dsn(params):
    v = params.get("DSN", params.get("DSNAME"))
    return v.upper() if isinstance(v, str) else None


def _cond_tests(v):
    """COND=... -> ([(code, op, stepname|None)], even, only)."""
    if v is None:
        return [], False, False
    vals = v if isinstance(v, list) else [v]
    if vals and all(isinstance(x, str) for x in vals) and len(vals) in (2, 3) and vals[0].isdigit():
        vals = [vals]
    tests, even, only = [], False, False
    for t in vals:
        if isinstance(t, str):
            if t.upper() == "EVEN":
                even = True
            elif t.upper() == "ONLY":
                only = True
            continue
        parts = [x for x in t if isinstance(x, str)]
        if len(parts) >= 2 and parts[0].isdigit():
            tests.append((int(parts[0]), parts[1].upper(), parts[2].upper() if len(parts) > 2 else None))
    return tests, even, only


def _cond_true(code, op, rc):
    return {"GT": code > rc, "GE": code >= rc, "EQ": code == rc, "LT": code < rc,
            "LE": code <= rc, "NE": code != rc}.get(op, False)


def _cics_only(src, runset, edited):
    """True when every edited file is reached only by CICS programs (contracts/ground-truth.md)."""
    if not edited:
        return False
    progs = {}
    for d in runset.get("program_dirs", []):
        for p in sorted((src / d).glob("*")):
            if p.suffix.lower() in (".cbl", ".cob"):
                progs[p.stem.upper()] = p
    copy_files = {}
    for d in runset.get("copy_dirs", []):
        for p in sorted((src / d).glob("*")):
            if p.is_file():
                copy_files.setdefault(p.stem.upper(), p)

    def copies(path, seen):
        text = path.read_bytes().decode("latin-1")
        for line in text.split("\n"):
            if len(line) > 6 and line[6] in "*/":
                continue
            for m in re.finditer(r"\bCOPY\s+['\"]?([A-Z0-9@#$-]+)", line[7:72].upper()):
                name = m.group(1)
                if name in copy_files and name not in seen:
                    seen.add(name)
                    copies(copy_files[name], seen)
        return seen

    batch = {p.upper() for p in runset.get("programs", [])}
    batch_reach, cics_reach = set(), set()
    for name, path in progs.items():
        reach = copies(path, set()) | {name}
        if name in batch:
            batch_reach |= reach
        elif "EXEC CICS" in path.read_bytes().decode("latin-1").upper():
            cics_reach |= reach
    job_files = {j["file"] for j in runset.get("jobs", [])}
    lib_dirs = {spec["dir"] for spec in runset.get("libraries", {}).values()}
    for rel in edited:
        if rel in job_files or any(rel.startswith(d.rstrip("/") + "/") for d in lib_dirs):
            return False
        stem = Path(rel).stem.upper()
        if stem in batch_reach or stem not in cics_reach:
            return False
    return True


# ---------------------------------------------------------------------- step context
class StepContext:
    """What a utility sees: the step's DD allocations and the catalog."""

    def __init__(self, run, job, step, allocs):
        self.run = run
        self.cat = run.cat
        self.job = job
        self.step = step
        self.allocs = allocs   # ddname -> [alloc]

    def has_dd(self, name):
        return name in self.allocs

    def sysin_lines(self, ddname):
        out = []
        for a in self.allocs.get(ddname, []):
            if a["kind"] == "instream":
                out += a["data"]
            elif a["kind"] == "member":
                out += a["path"].read_bytes().decode("latin-1").replace("\r", "").split("\n")
            elif a["kind"] == "dataset":
                ent = self.cat.e[a["name"]]
                if ent["kind"] == "ps":
                    try:
                        out += [r.decode("latin-1") for r in self.cat.records(a["name"])]
                    except Unsupported:
                        out += ent["path"].read_bytes().decode("latin-1").split("\n")
            elif a["kind"] == "dummy":
                pass
        return out

    def dd_datasets(self, ddname):
        out = []
        for a in self.allocs.get(ddname, []):
            if a["kind"] == "dataset":
                out.append(a["name"])
            elif a["kind"] == "dummy":
                out.append(None)
            else:
                raise Unsupported(f"DD {ddname} is not a dataset")
        return out

    def idcams_target(self, ddname, dsn):
        if ddname:
            names = self.dd_datasets(ddname.strip()) if ddname.strip() in self.allocs else []
            return names[0] if names else None
        if dsn:
            name = dsn.strip().upper()
            return name if name in self.cat.e else None
        return None

    def read_records(self, name):
        if name is None:
            return []
        return self.cat.records(name)

    def write_records(self, name, recs, replace):
        """Write records to a dataset; returns a return code (8 if a KSDS refused some)."""
        if name is None:
            return 0
        ent = self.cat.e[name]
        self.run.mark_written(name)
        if ent["kind"] in ("ksds", "path"):
            target = name if ent["kind"] == "ksds" else self.cat.e[ent["entry"]]["relate"]
            _, bad = self.cat.ksds_load(target, recs)
            return 8 if bad else 0
        if ent["kind"] != "ps":
            raise Unsupported(f"cannot write records to a {ent['kind']}")
        lrecl = ent.get("lrecl")
        if lrecl is None and recs:
            lrecl = len(recs[0])
            ent["lrecl"] = lrecl
        data = b"".join(r[:lrecl].ljust(lrecl, b" ") for r in recs)
        ent["path"].write_bytes(data)
        return 0

    def note_deleted(self, name):
        pass

    def mark_written(self, name):
        self.run.mark_written(name)


# ---------------------------------------------------------------------- the run
class Run:
    def __init__(self, src, runset, work):
        self.src = Path(src)
        self.runset = runset
        self.work = Path(work)
        self.tc = cobol.Toolchain(self.work, runset.get("cobc_flags", []))
        self.cat = Catalog(self.work / "ds", self.tc)
        self.sysout_dir = self.work / "sysout"
        self.sysout_dir.mkdir(parents=True, exist_ok=True)
        self.written = set()
        self.sysouts = {}
        self.input_notes = {}
        self.compile = {}
        self.steps = []
        self.notes = []

    def note(self, job, step, text):
        key = f"{job.name}.{step.name}" + (f".{step.procstep}" if step and step.procstep else "")
        self.notes.append(f"{key}: {text}".replace(str(self.work), "<work>"))

    def mark_written(self, name):
        self.written.add(self.cat.output_name(name))

    # ------------------------------------------------------------ setup
    def load_inputs(self):
        for inp in self.runset.get("inputs", []):
            base = REPO if inp.get("from") == "repo" else self.src
            path = base / inp["path"]
            dsn = inp["dsn"].upper()
            lrecl = int(inp["lrecl"])
            note = {"records": 0, "padded": 0, "truncated": 0, "converted": 0}
            raw = path.read_bytes() if path.is_file() else None
            if raw is None:
                note["missing"] = True
                self.input_notes[dsn] = note
                continue
            enc = inp.get("encoding", "ascii")
            recs = []
            if enc == "ascii":
                lines = raw.split(b"\n")
                if lines and lines[-1] == b"":
                    lines.pop()
                for ln in lines:
                    if ln.endswith(b"\r"):
                        ln = ln[:-1]
                    if len(ln) < lrecl:
                        note["padded"] += 1
                        ln = ln.ljust(lrecl, b" ")
                    elif len(ln) > lrecl:
                        note["truncated"] += 1
                        ln = ln[:lrecl]
                    recs.append(ln)
            elif enc == "ebcdic-cp037":
                if len(raw) % lrecl:
                    note["partial_record_bytes"] = len(raw) % lrecl
                for i in range(0, len(raw) - len(raw) % lrecl, lrecl):
                    recs.append(raw[i:i + lrecl].decode("cp037").encode("latin-1"))
                    note["converted"] += 1
            else:
                raise ValueError(f"input {dsn}: unknown encoding {enc}")
            note["records"] = len(recs)
            ent = self.cat.new_ps(dsn, lrecl=lrecl, recfm=inp.get("recfm", "F"))
            ent["path"].write_bytes(b"".join(recs))
            self.input_notes[dsn] = note

    def build(self):
        flags = self.runset.get("cobc_flags", [])
        for prog in self.runset.get("programs", []):
            self.compile[prog] = cobol.compile_program(self.src, self.runset, prog, self.tc.mod)
        for name in sorted(self.runset.get("stubs", {})):
            s = cobol.stub_source(name)
            if s is not None:
                cobol.build_module(s, flags, self.tc.mod)

    # ------------------------------------------------------------ allocation
    def _resolve(self, dsn, jobstate):
        """DSN -> (kind, catalog name or path)."""
        if dsn in ("NULLFILE",):
            return "dummy", None
        if dsn.startswith("&&"):
            return "dataset", f"{jobstate['job']}.TEMP.{dsn[2:]}"
        m = GDG_REF.match(dsn)
        if m and self.cat.e.get(m.group(1), {}).get("kind") == "gdg":
            base, rel = m.group(1), int(m.group(2))
            gens0 = jobstate["gdg0"].setdefault(base, list(self.cat.e[base]["gens"]))
            top = gens0[-1] if gens0 else 0
            if rel > 0:
                n = top + rel
            else:
                idx = len(gens0) - 1 + rel
                if idx < 0:
                    return "missing", dsn
                n = gens0[idx]
            return "gen", (base, n)
        if m:
            return "missing", dsn
        m = MEMBER_REF.match(dsn)
        if m:
            lib = self.runset.get("libraries", {}).get(m.group(1))
            if lib:
                folder = self.src / lib["dir"]
                for ext in lib.get("ext", []):
                    p = folder / f"{m.group(2)}{ext}"
                    if p.is_file():
                        return "member", p
            return "missing", dsn
        return "dataset", dsn

    def _dcb_lrecl(self, params, allocs):
        dcb = params.get("DCB")
        lrecl = params.get("LRECL")
        recfm = params.get("RECFM")
        if isinstance(dcb, list):
            lrecl = jcl.sub(dcb, "LRECL") or lrecl
            recfm = jcl.sub(dcb, "RECFM") or recfm
            for x in dcb:
                if isinstance(x, str) and x.startswith("*."):
                    ref = x[2:].split(".")[-1]
                    for a in allocs.get(ref, []):
                        if a["kind"] == "dataset":
                            lrecl = lrecl or self.cat.lrecl(a["name"])
                            recfm = recfm or (self.cat.e.get(a["name"], {}).get("recfm"))
        return (int(lrecl) if lrecl else None), (recfm.upper() if isinstance(recfm, str) else None)

    def allocate(self, job, step, jobstate, sysout_prefix, stepdir):
        allocs, pending = {}, []
        for dd in step.dds:
            entries = []
            for part in [dd] + dd.concat:
                entries.append(self._alloc_one(dd.name, part, allocs, jobstate, sysout_prefix, stepdir, pending))
            allocs[dd.name] = entries
        return allocs, pending

    def _alloc_one(self, ddname, dd, allocs, jobstate, sysout_prefix, stepdir, pending):
        p = dd.params
        pos = [x for x in p.get("_pos", []) if isinstance(x, str)]
        if dd.data is not None:
            return {"kind": "instream", "data": dd.data}
        if "DUMMY" in [x.upper() for x in pos]:
            return {"kind": "dummy"}
        if "SYSOUT" in p:
            path = stepdir / f"sysout-{ddname}"
            return {"kind": "sysout", "path": path, "out": f"{sysout_prefix}.{ddname}"}
        dsn = _dsn(p)
        status, normal, abnormal = _disp(p)
        if dsn is None:
            if ddname in ("STEPLIB", "JOBLIB"):
                return {"kind": "ignore"}
            dsn = f"&&{jobstate['job']}{len(jobstate['temps'])}"
        if ddname in ("STEPLIB", "JOBLIB"):
            return {"kind": "ignore"}
        kind, ref = self._resolve(dsn, jobstate)
        if kind == "dummy":
            return {"kind": "dummy"}
        if kind == "member":
            return {"kind": "member", "path": ref}
        if kind == "missing":
            raise JobEnd(f"DD {ddname}: {dsn} not found")
        if kind == "gen":
            base, n = ref
            name = self.cat.gen_name(base, n)
            if status in ("NEW", "MOD") and name not in self.cat.e:
                lrecl, recfm = self._dcb_lrecl(p, allocs)
                self.cat.new_ps(name, lrecl, recfm)
                pending.append({"name": name, "normal": normal, "abnormal": abnormal, "new": True, "gdg": (base, n)})
            elif name not in self.cat.e:
                raise JobEnd(f"DD {ddname}: {dsn} not found")
            else:
                pending.append({"name": name, "normal": normal, "abnormal": abnormal, "new": False, "gdg": None})
            return {"kind": "dataset", "name": name}
        name = ref
        if name.startswith(f"{jobstate['job']}.TEMP."):
            jobstate["temps"].add(name)
        if status == "NEW" or (status == "MOD" and name not in self.cat.e):
            lrecl, recfm = self._dcb_lrecl(p, allocs)
            if name in self.cat.e:
                self.cat.delete(name)
            self.cat.new_ps(name, lrecl, recfm)
            pending.append({"name": name, "normal": normal, "abnormal": abnormal, "new": True, "gdg": None})
        elif name not in self.cat.e:
            raise JobEnd(f"DD {ddname}: {dsn} not found")
        else:
            pending.append({"name": name, "normal": normal, "abnormal": abnormal, "new": False, "gdg": None})
        return {"kind": "dataset", "name": name}

    def dispose(self, pending, abended):
        for d in pending:
            name = d["name"]
            disp = d["abnormal"] if abended else d["normal"]
            if name not in self.cat.e:
                continue
            if disp == "DELETE":
                self.cat.delete(name)
                continue
            if d["gdg"] and d["new"]:
                self.cat.gdg_roll_in(*d["gdg"])

    # ------------------------------------------------------------ execution
    def run_jobs(self):
        for spec in self.runset.get("jobs", []):
            try:
                job = jcl.parse_job(self.src / spec["file"], self.runset.get("libraries", {}), self.src, spec["job"])
            except (OSError, ValueError, IndexError, jcl.JCLError) as exc:
                self.notes.append(f"{spec['job']}: JCL not read: {type(exc).__name__}: {exc}")
                self.steps.append({"job": spec["job"], "step": "*", "procstep": None, "program": None,
                                   "status": "unsupported", "rc": None})
                continue
            for n in job.notes:
                self.notes.append(f"{job.name}: {n}")
            self.run_job(job)

    def _record(self, job, step, status, rc):
        self.steps.append({"job": job.name, "step": step.name, "procstep": step.procstep,
                           "program": step.pgm, "status": status, "rc": rc})

    def run_job(self, job):
        jobstate = {"job": job.name, "gdg0": {}, "temps": set()}
        done = []       # (stepname, procstep, rc) of steps that ran
        ended = False   # an abend or allocation failure ended the job
        utilities_ok = set(self.runset.get("utilities", {}))
        programs = {p.upper() for p in self.runset.get("programs", [])}
        for n, step in enumerate(job.steps):
            tests, even, only = _cond_tests(step.params.get("COND"))
            if ended and not (even or only):
                self._record(job, step, "not_run", None)
                continue
            if only and not ended:
                self._record(job, step, "skipped", None)
                continue
            skip = False
            for code, op, ref in tests:
                for sname, pstep, rc in done:
                    if rc is None:
                        continue
                    if ref is None or ref in (sname, pstep, f"{sname}.{pstep}"):
                        if _cond_true(code, op, rc):
                            skip = True
            if skip:
                self._record(job, step, "skipped", None)
                continue
            if step.params.get("_unsupported"):
                self._record(job, step, "unsupported", None)
                continue
            pgm = step.pgm
            if pgm == "SDSF" and "SDSF" in utilities_ok:
                self._record(job, step, "skipped", None)
                continue
            if pgm in programs:
                if not self.compile.get(pgm, {}).get("ok"):
                    # no load module: the step cannot start (S806), and the job ends
                    self._record(job, step, "not_run", None)
                    ended = True
                    continue
                status, rc = self.run_program(job, step, jobstate, n)
            elif pgm in utilities_ok and pgm in utilities.RUNNERS:
                status, rc = self.run_utility(job, step, jobstate, n)
            else:
                status, rc = "unsupported", None
            self._record(job, step, status, rc)
            if status == "abend":
                ended = True
            elif status == "ok":
                done.append((step.name, step.procstep, rc))
        for t in jobstate["temps"]:
            self.cat.delete(t)

    def _stepdir(self, job, n):
        d = self.work / "steps" / f"{job.name}.{n:02d}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _prefix(self, job, step):
        return f"SYSOUT:{job.name}.{step.name}" + (f".{step.procstep}" if step.procstep else "")

    def _sigs(self, pending):
        return {d["name"]: self.cat.signature(d["name"]) for d in pending}

    def _mark_changed(self, pending, before):
        for d in pending:
            if d["name"] not in self.cat.e:
                continue
            if d["new"] or self.cat.signature(d["name"]) != before.get(d["name"]):
                self.mark_written(d["name"])

    def run_utility(self, job, step, jobstate, n):
        stepdir = self._stepdir(job, n)
        try:
            allocs, pending = self.allocate(job, step, jobstate, self._prefix(job, step), stepdir)
        except JobEnd as exc:
            self.note(job, step, f"JCL error: {exc}")
            return "abend", None
        before = self._sigs(pending)
        ctx = StepContext(self, job, step, allocs)
        try:
            rc = utilities.RUNNERS[step.pgm](ctx)
        except Unsupported as exc:
            self.note(job, step, f"unsupported: {exc}")
            self.dispose(pending, abended=True)
            return "unsupported", None
        except (RuntimeError, ValueError, KeyError, IndexError, OSError) as exc:
            # a harness limit, not program behaviour: reported, never guessed
            self.note(job, step, f"harness error: {type(exc).__name__}: {exc}")
            self.dispose(pending, abended=True)
            return "unsupported", None
        self._mark_changed(pending, before)
        self.dispose(pending, abended=False)
        return "ok", rc

    def run_program(self, job, step, jobstate, n):
        stepdir = self._stepdir(job, n)
        prefix = self._prefix(job, step)
        try:
            allocs, pending = self.allocate(job, step, jobstate, prefix, stepdir)
        except JobEnd as exc:
            self.note(job, step, f"JCL error: {exc}")
            return "abend", None
        before = self._sigs(pending)
        env = cobol._build_env()
        env.update({
            "COB_LIBRARY_PATH": str(self.tc.mod),
            "COB_CURRENT_DATE": pinned_clock(self.runset.get("clock", "")),
            "TZ": "UTC",
            "GT_PROGRAM": step.pgm,
        })
        parm = step.params.get("PARM", "")
        parm = parm if isinstance(parm, str) else ",".join(jcl.flat(parm))
        env["GT_PARM"] = parm
        env["GT_PARM_LEN"] = str(len(parm))
        stdin_path = None
        sysouts = []
        for ddname, entries in allocs.items():
            if not ddname:
                continue
            paths = []
            for k, a in enumerate(entries):
                if a["kind"] == "dataset":
                    ent = self.cat.e[a["name"]]
                    if ent["kind"] == "path":
                        ent = self.cat.e[self.cat.e[ent["entry"]]["relate"]]
                    elif ent["kind"] == "aix":
                        ent = self.cat.e[ent["relate"]]
                    paths.append(ent["path"])
                elif a["kind"] == "member":
                    paths.append(a["path"])
                elif a["kind"] == "instream":
                    p = stepdir / f"instream-{ddname}-{k}"
                    p.write_bytes(b"".join(ln[:80].ljust(80).encode("latin-1") for ln in a["data"]))
                    paths.append(p)
                elif a["kind"] == "dummy":
                    p = stepdir / f"dummy-{ddname}-{k}"
                    p.write_bytes(b"")
                    paths.append(p)
                elif a["kind"] == "sysout":
                    sysouts.append((ddname, a))
                    paths.append(a["path"])
            if not paths:
                continue
            if len(paths) == 1:
                env[f"DD_{ddname}"] = str(paths[0])
            else:
                cat_path = stepdir / f"concat-{ddname}"
                cat_path.write_bytes(b"".join(Path(x).read_bytes() for x in paths))
                env[f"DD_{ddname}"] = str(cat_path)
            if ddname == "SYSIN":
                stdin_path = env[f"DD_{ddname}"]
        stdin = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
        try:
            r = subprocess.run([str(self.tc.driver())], cwd=stepdir, env=env, stdin=stdin,
                               capture_output=True, timeout=STEP_TIMEOUT)
            rc, out, err, timed_out = r.returncode, r.stdout, r.stderr, False
        except subprocess.TimeoutExpired as exc:
            rc, out, err, timed_out = None, exc.stdout or b"", exc.stderr or b"", True
        finally:
            if stdin_path:
                stdin.close()
        (stepdir / "stderr").write_bytes(err)
        errtext = err.decode("latin-1")
        abended = (timed_out or rc is None or rc < 0 or "GT-ABEND" in errtext
                   or re.search(r"libcob: .*error", errtext) is not None)
        for ddname, a in sysouts:
            data = a["path"].read_bytes() if a["path"].exists() else b""
            if ddname == SYSOUT_DD_STDOUT:
                data += out
            if a["path"].exists() or data:
                self.sysouts[a["out"]] = data
        self._mark_changed(pending, before)
        self.dispose(pending, abended=abended)
        if abended:
            first = next((ln for ln in errtext.splitlines() if "GT-ABEND" in ln or "libcob" in ln), "")
            self.note(job, step, "abend" + (" (timeout)" if timed_out else "") + (f": {first.strip()}" if first else ""))
            return "abend", None
        return "ok", rc

    # ------------------------------------------------------------ outputs
    def outputs(self):
        import hashlib
        out = {}
        for name in sorted(self.written):
            c = self.cat.canonical(name)
            if c is None:
                continue
            out[name] = {"sha256": c[0], "bytes": c[1], "generations": c[2]}
        for name, data in sorted(self.sysouts.items()):
            out[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "generations": 1}
        return out


def run(root, runset, workdir, change=None):
    """One full run of the run set, with `change` applied to a copy of `root` first."""
    root = Path(root)
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    src = work / "src"
    if src.exists():
        shutil.rmtree(src)
    shutil.copytree(root, src, ignore=shutil.ignore_patterns(".git"), symlinks=True)
    result = {
        "change_id": change.get("id") if change else None,
        "carddemo_commit": runset.get("carddemo_commit", ""),
        "cobc_version": cobol.cobc_version(),
        "clock": pinned_clock(runset.get("clock", "")),
        "compile": {},
        "steps": [],
        "outputs": {},
        "input_notes": {},
        "apply_error": None,
        "cics_only": False,
        "notes": [],
    }
    if change:
        try:
            edited = gtchanges.apply(change, src)
        except gtchanges.ApplyError as exc:
            result["apply_error"] = str(exc)
            return result
        result["cics_only"] = _cics_only(src, runset, edited)
    r = Run(src, runset, work)
    r.build()
    result["compile"] = r.compile
    r.load_inputs()
    result["input_notes"] = r.input_notes
    r.run_jobs()
    result["steps"] = r.steps
    result["outputs"] = r.outputs()
    result["notes"] = r.notes
    return result
