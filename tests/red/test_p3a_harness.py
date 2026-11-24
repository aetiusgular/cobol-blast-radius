"""F3, the ground-truth harness (lane P3a). Red in P2: the stubs raise NotImplementedError."""
import copy

from groundtruth import diff as gtdiff
from groundtruth import harness
from tests.red._support import MINI, TempDirCase, assert_schema, mini_change, mini_runset, tree_digest

MINI_OUTPUTS = {"MINI.OUTFILE", "MINI.SORTED", "MINI.SUMFILE",
                "SYSOUT:MINIJOB1.STEP1.RUN.SYSOUT", "SYSOUT:MINIJOB2.STEP2.SYSOUT"}


def _run(case, name, change=None, runset="runset.json"):
    work = case.tmp / name
    work.mkdir()
    return harness.run(MINI, mini_runset(runset), work, change=change)


class HarnessRed(TempDirCase):
    def test_baseline_repeats(self):
        """Two baseline runs give identical compile results, steps and output hashes; the tree is untouched."""
        before = tree_digest(MINI)
        a = _run(self, "a")
        b = _run(self, "b")
        assert_schema(self, a, "run-result.schema.json")
        self.assertEqual(set(a["outputs"]), MINI_OUTPUTS)
        self.assertTrue(all(o["sha256"] for o in a["outputs"].values()))
        for key in ("compile", "steps", "outputs"):
            self.assertEqual(a[key], b[key], key)
        self.assertEqual(tree_digest(MINI), before, "the harness wrote under root")

    def test_ebcdic_input_matches_ascii(self):
        """The same records as EBCDIC cp037 fixed records give the same outputs byte for byte."""
        a = _run(self, "ascii")
        e = _run(self, "ebcdic", runset="runset-ebcdic.json")
        self.assertEqual(a["outputs"], e["outputs"])

    def test_compile_failure_reported(self):
        """A change that breaks compilation is reported in compile, its step is not_run, and the diff excludes it."""
        base = _run(self, "base")
        after = _run(self, "broken", change=mini_change("compile-break"))
        self.assertFalse(after["compile"]["MINIRPT"]["ok"])
        self.assertIn("MR-NAMX", after["compile"]["MINIRPT"]["diagnostics"])
        self.assertTrue(after["compile"]["MINISUM"]["ok"])
        run_step = [s for s in after["steps"] if s["job"] == "MINIJOB1" and s["program"] == "MINIRPT"]
        self.assertEqual([s["status"] for s in run_step], ["not_run"])
        d = gtdiff.diff(base, after)
        assert_schema(self, d, "diff.schema.json")
        self.assertTrue(d["excluded"])
        self.assertEqual(d["exclusion_reason"], "compile_failure")

    def test_outputs_compared_byte_for_byte(self):
        """One differing hash, or an output gone, is changed; equal hashes are unchanged."""
        base = {"change_id": None, "carddemo_commit": "x", "cobc_version": "x", "clock": "x",
                "compile": {}, "steps": [], "input_notes": {},
                "outputs": {"A": {"sha256": "a" * 64, "bytes": 10, "generations": 1},
                            "B": {"sha256": "b" * 64, "bytes": 10, "generations": 1},
                            "C": {"sha256": "c" * 64, "bytes": 10, "generations": 1}}}
        after = copy.deepcopy(base)
        after["change_id"] = "T-1"
        after["outputs"]["B"]["sha256"] = "d" * 64
        after["outputs"]["C"] = {"sha256": None, "bytes": 0, "generations": 0}
        d = gtdiff.diff(base, after)
        self.assertEqual(d["changed"], ["B", "C"])
        self.assertEqual(d["unchanged"], ["A"])
        self.assertFalse(d["excluded"])

    def test_sort_order_change_reaches_only_sorted(self):
        """Sorting descending changes MINI.SORTED's bytes but not the order-free sum after it."""
        base = _run(self, "base")
        after = _run(self, "sort", change=mini_change("jcl-sort"))
        d = gtdiff.diff(base, after)
        self.assertEqual(d["changed"], ["MINI.SORTED"])
