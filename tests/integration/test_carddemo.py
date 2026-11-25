"""The run set as P4 left it, on CardDemo at the pinned commit (RFI-P3a-1, RFI-P3a-2, RFI-P3b-1)."""
from groundtruth import harness
from radius import graph
from tests.integration._common import CARDDEMO, CONTRACTS, TempDirCase, load, need_carddemo, need_cobc

DALYREJS_REASON = slice(350, 354)
DALYREJS_LRECL = 430


class CarddemoRunset(TempDirCase):
    @classmethod
    def setUpClass(cls):
        cls.runset = load(CONTRACTS / "runset.json")

    def setUp(self):
        super().setUp()
        need_cobc(self)
        need_carddemo(self)

    def _run(self, name):
        return harness.run(CARDDEMO, self.runset, self.tmp / name)

    def test_the_baseline_builds_runs_and_repeats(self):
        a, b = self._run("a"), self._run("b")
        self.assertSchema(a, "run-result.schema.json")
        self.assertEqual(sorted(p for p, r in a["compile"].items() if not r["ok"]), [])
        bad = [s for s in a["steps"] if s["status"] not in ("ok", "skipped")]
        self.assertEqual(bad, [], a["notes"])
        self.assertEqual(a["clock"], "2022/07/01 10:00:00.00")
        for k in ("compile", "steps", "outputs"):
            self.assertEqual(a[k], b[k], k)

    def test_the_report_window_holds_the_clock(self):
        """RFI-P3a-2: TRANREPT's INCLUDE keeps the day's transactions, so CBTRN03C's report is scored."""
        out = self._run("a")["outputs"]
        for name in ("AWS.M2.CARDDEMO.TRANSACT.DALY", "AWS.M2.CARDDEMO.TRANREPT"):
            self.assertGreater(out[name]["bytes"], 0, name)

    def test_overpunched_signs_are_read(self):
        """RFI-P3a-1: with -fsign=EBCDIC, POSTTRAN rejects a minority of the daily transactions, not nearly all."""
        self._run("a")
        daly = (CARDDEMO / "app/data/ASCII/dailytran.txt").read_text().splitlines()
        rejs = sorted((self.tmp / "a" / "ds").glob("AWS.M2.CARDDEMO.DALYREJS*"))
        self.assertTrue(rejs)
        data = b"".join(p.read_bytes() for p in rejs)
        recs = [r for r in data.split(b"\n") if r] if b"\n" in data else \
            [data[i:i + DALYREJS_LRECL] for i in range(0, len(data), DALYREJS_LRECL)]
        self.assertGreater(len(recs), 0)
        self.assertLess(len(recs), len(daly) // 2)

    def test_the_graph_names_every_scored_output(self):
        out = self._run("a")["outputs"]
        nodes = graph.build(CARDDEMO).nodes
        self.assertEqual(sorted(n for n in out if f"dataset:{n}" not in nodes), [])

    def test_a_library_member_is_a_dataset_node(self):
        """RFI-P3b-1: runset.md and graph.md name a library member LIB(MEMBER)."""
        self.assertIn("dataset:AWS.M2.CARDDEMO.CNTL(REPROCT)", graph.build(CARDDEMO).nodes)
