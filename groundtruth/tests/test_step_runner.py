"""The step runner on a synthetic job set, and the CardDemo baseline. These need cobc (scripts/setup.sh)."""
import json
import tempfile
import unittest
from pathlib import Path

from groundtruth import diff, generate, harness

REPO = Path(__file__).resolve().parents[2]
CARDDEMO = REPO / "vendor" / "carddemo"
MINI = REPO / "fixtures" / "mini"

JOBS = {
    "J1": """//J1 JOB
//DEF EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//SYSIN DD *
  DEFINE GENERATIONDATAGROUP (NAME(T.G) LIMIT(2) SCRATCH)
  DEFINE CLUSTER (NAME(T.KS) KEYS(3 0) RECORDSIZE(10 10) INDEXED) -
         DATA (NAME(T.KS.DATA))
/*
//LOAD EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//IN DD DSN=T.IN,DISP=SHR
//OUT DD DSN=T.KS,DISP=OLD
//SYSIN DD *
  REPRO INFILE(IN) OUTFILE(OUT)
/*
""",
    "J5": """//J5 JOB
//S1 EXEC PGM=SORT
//SORTIN DD DSN=T.G(0),DISP=SHR
//       DD DSN=T.G(-1),DISP=SHR
//SYSIN DD *
 INCLUDE COND=(1,1,CH,EQ,C'B')
 SORT FIELDS=(1,3,CH,D)
/*
//SORTOUT DD DSN=T.S,DISP=(NEW,CATLG,DELETE),DCB=(*.SORTIN)
""",
    "J6": """//J6 JOB
//S1 EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//SYSIN DD *
  DELETE NO.SUCH.DATASET
/*
//S2 EXEC PGM=IEFBR14,COND=(4,LT)
//S3 EXEC PGM=IEFBR14,COND=(8,LT)
//S4 EXEC PGM=FOO
""",
    "J7": """//J7 JOB
//S1 EXEC PGM=IEBGENER
//SYSUT1 DD DSN=NOT.THERE,DISP=SHR
//SYSUT2 DD DSN=T.X,DISP=(NEW,CATLG,DELETE),DCB=(LRECL=10,RECFM=FB)
//S2 EXEC PGM=IEFBR14
""",
}
GEN = """//{name} JOB
//S1 EXEC PGM=IEBGENER
//SYSUT1 DD DSN=T.IN,DISP=SHR
//SYSUT2 DD DSN=T.G(+1),DISP=(NEW,CATLG,DELETE),DCB=(LRECL=10,RECFM=FB)
//SYSIN DD DUMMY
"""


def synthetic(tmp):
    root = Path(tmp) / "root"
    (root / "app/jcl").mkdir(parents=True)
    (root / "app/data").mkdir()
    (root / "app/data/in.txt").write_text("B01xxxxxxx\nA02yyy\nB03zzz\n")
    jobs = dict(JOBS)
    for n in ("J2", "J3", "J4"):
        jobs[n] = GEN.format(name=n)
    order = ["J1", "J2", "J3", "J4", "J5", "J6", "J7"]
    for n in order:
        (root / f"app/jcl/{n}.jcl").write_text(jobs[n])
    runset = {
        "carddemo_commit": "synthetic", "clock": "2022/07/18 10:00:00", "cobc_flags": ["-std=ibm"],
        "libraries": {}, "jobs": [{"job": n, "file": f"app/jcl/{n}.jcl"} for n in order],
        "programs": [], "program_dirs": ["app/cbl"], "copy_dirs": ["app/cpy"],
        "utilities": {"IDCAMS": "", "SORT": "", "IEBGENER": "", "IEFBR14": ""}, "stubs": {},
        "inputs": [{"dsn": "T.IN", "path": "app/data/in.txt", "encoding": "ascii", "recfm": "F", "lrecl": 10}],
        "excluded_jobs": [],
    }
    return root, runset


class StepRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root, runset = synthetic(cls._tmp.name)
        cls.root, cls.runset = root, runset
        (Path(cls._tmp.name) / "w").mkdir()
        cls.r = harness.run(root, runset, Path(cls._tmp.name) / "w")
        cls.steps = {(s["job"], s["step"]): s for s in cls.r["steps"]}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_gdg_limit_rolls_off_the_oldest(self):
        self.assertEqual(self.r["outputs"]["T.G"]["generations"], 2)
        self.assertEqual(self.r["outputs"]["T.G"]["bytes"], 60)

    def test_ksds_in_key_order_and_components_fold(self):
        self.assertEqual(self.r["outputs"]["T.KS"]["bytes"], 30)
        self.assertNotIn("T.KS.DATA", self.r["outputs"])
        self.assertEqual(self.r["input_notes"]["T.IN"]["padded"], 2)

    def test_sort_concatenation_include_and_descending(self):
        self.assertEqual(self.r["outputs"]["T.S"]["bytes"], 40)
        work = Path(self._tmp.name) / "w"
        self.assertEqual((work / "ds" / "T.S").read_bytes(), b"B03zzz    " * 2 + b"B01xxxxxxx" * 2)

    def test_cond_codes(self):
        self.assertEqual(self.steps[("J6", "S1")]["rc"], 8)
        self.assertEqual(self.steps[("J6", "S2")]["status"], "skipped")
        self.assertEqual(self.steps[("J6", "S3")]["status"], "ok")
        self.assertEqual(self.steps[("J6", "S4")]["status"], "unsupported")

    def test_missing_dataset_ends_the_job(self):
        self.assertEqual(self.steps[("J7", "S1")]["status"], "abend")
        self.assertEqual(self.steps[("J7", "S2")]["status"], "not_run")
        self.assertNotIn("T.X", self.r["outputs"])
        self.assertTrue(any("NOT.THERE" in n for n in self.r["notes"]))

    def test_utility_sysout_is_not_an_output(self):
        self.assertFalse([k for k in self.r["outputs"] if k.startswith("SYSOUT:")])

    def test_apply_failure_is_excluded(self):
        bad = {"id": "B", "class": "jcl_step", "seed": None, "summary": "", "compile_break": False,
               "edits": [{"file": "app/jcl/J5.jcl", "line": 1, "op": "replace", "before": "nope", "after": "x"}]}
        with tempfile.TemporaryDirectory() as w:
            after = harness.run(self.root, self.runset, w, change=bad)
        d = diff.diff(self.r, after)
        self.assertEqual(d["exclusion_reason"], "apply_failure")


class ClockTest(unittest.TestCase):
    def test_fraction_pinned(self):
        self.assertEqual(harness.pinned_clock("2022/07/18 10:00:00"), "2022/07/18 10:00:00.00")
        self.assertEqual(harness.pinned_clock("2022/07/18 10:00:00.50"), "2022/07/18 10:00:00.50")


class GenerateTest(unittest.TestCase):
    def test_compile_break_detected(self):
        rs = json.loads((MINI / "runset.json").read_text())
        ch = json.loads((MINI / "changes" / "compile-break.json").read_text())
        self.assertTrue(generate.compile_break(ch, MINI, rs))
        ok = json.loads((MINI / "changes" / "field-label.json").read_text())
        self.assertFalse(generate.compile_break(ok, MINI, rs))

    def test_unknown_class_refused(self):
        with self.assertRaises(ValueError):
            generate.generate("nope", 1, MINI, json.loads((MINI / "runset.json").read_text()))


@unittest.skipUnless((CARDDEMO / "app" / "cbl").is_dir(), "vendor/carddemo missing: scripts/setup.sh fetches it")
class CardDemoTest(unittest.TestCase):
    def test_baseline_repeats_and_every_program_builds(self):
        rs = json.loads((REPO / "contracts" / "runset.json").read_text())
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            ra = harness.run(CARDDEMO, rs, a)
            rb = harness.run(CARDDEMO, rs, b)
        for k in ("compile", "steps", "outputs"):
            self.assertEqual(ra[k], rb[k], k)
        self.assertTrue(all(v["ok"] for v in ra["compile"].values()), ra["compile"])
        self.assertEqual(sorted(ra["compile"]), sorted(rs["programs"]))
        bad = [s for s in ra["steps"] if s["status"] not in ("ok", "skipped")]
        self.assertEqual(bad, [], ra["notes"])
        self.assertTrue(all(o["sha256"] for o in ra["outputs"].values()))

    def test_cics_only_reach(self):
        rs = json.loads((REPO / "contracts" / "runset.json").read_text())
        self.assertTrue(harness._cics_only(CARDDEMO, rs, ["app/cbl/COSGN00C.cbl"]))
        self.assertFalse(harness._cics_only(CARDDEMO, rs, ["app/cbl/CBACT01C.cbl"]))
        self.assertFalse(harness._cics_only(CARDDEMO, rs, ["app/cpy/CVACT01Y.cpy"]))
        self.assertFalse(harness._cics_only(CARDDEMO, rs, ["app/jcl/POSTTRAN.jcl"]))


if __name__ == "__main__":
    unittest.main()
