"""changes.apply and diff.diff edge cases (contracts/change.md, contracts/ground-truth.md)."""
import tempfile
import unittest
from pathlib import Path

from groundtruth import changes, diff


def _change(*edits):
    return {"id": "T", "class": "noop", "seed": None, "summary": "", "compile_break": False, "edits": list(edits)}


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "app").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, data):
        p = self.root / "app" / "F.cbl"
        p.write_bytes(data)
        return p

    def test_keeps_cr_and_missing_final_newline(self):
        p = self.write(b"one\r\ntwo\r\nthree")
        changes.apply(_change({"file": "app/F.cbl", "line": 2, "op": "replace", "before": "two\r", "after": "TWO\r"}), self.root)
        self.assertEqual(p.read_bytes(), b"one\r\nTWO\r\nthree")

    def test_insert_at_top_and_after_last(self):
        p = self.write(b"a\nb\n")
        changes.apply(_change({"file": "app/F.cbl", "line": 0, "op": "insert_after", "before": None, "after": "top"},
                              {"file": "app/F.cbl", "line": 3, "op": "insert_after", "before": None, "after": "end"}),
                      self.root)
        self.assertEqual(p.read_bytes(), b"top\na\nb\nend\n")

    def test_edits_see_earlier_edits(self):
        p = self.write(b"a\nb\n")
        changes.apply(_change({"file": "app/F.cbl", "line": 1, "op": "insert_after", "before": None, "after": "x"},
                              {"file": "app/F.cbl", "line": 2, "op": "replace", "before": "x", "after": "y"}),
                      self.root)
        self.assertEqual(p.read_bytes(), b"a\ny\nb\n")

    def test_non_utf8_bytes_survive(self):
        p = self.write(b"\xc1\xc2\nkeep\n")
        changes.apply(_change({"file": "app/F.cbl", "line": 2, "op": "replace", "before": "keep", "after": "kept"}), self.root)
        self.assertEqual(p.read_bytes(), b"\xc1\xc2\nkept\n")

    def test_missing_file_and_escape_refused(self):
        with self.assertRaises(changes.ApplyError):
            changes.apply(_change({"file": "app/NOPE.cbl", "line": 1, "op": "replace", "before": "a", "after": "b"}), self.root)
        with self.assertRaises(changes.ApplyError):
            changes.apply(_change({"file": "app/../../x", "line": 1, "op": "replace", "before": "a", "after": "b"}), self.root)

    def test_line_past_end_refused(self):
        self.write(b"a\n")
        with self.assertRaises(changes.ApplyError):
            changes.apply(_change({"file": "app/F.cbl", "line": 5, "op": "replace", "before": "a", "after": "b"}), self.root)


def _run(outputs, compile_=None, steps=None, **kw):
    r = {"change_id": kw.get("cid"), "compile": compile_ or {}, "steps": steps or [], "outputs": outputs}
    r.update({k: v for k, v in kw.items() if k != "cid"})
    return r


class DiffTest(unittest.TestCase):
    H = {"sha256": "a" * 64, "bytes": 1, "generations": 1}

    def test_new_output_in_after_is_changed(self):
        d = diff.diff(_run({"A": self.H}), _run({"A": self.H, "N": self.H}, cid="x"))
        self.assertEqual(d["changed"], ["N"])
        self.assertEqual(d["unchanged"], ["A"])
        self.assertEqual(d["change_id"], "x")

    def test_compile_failure_only_when_baseline_compiled(self):
        base = _run({}, {"P": {"ok": False, "diagnostics": ""}})
        after = _run({}, {"P": {"ok": False, "diagnostics": ""}})
        self.assertFalse(diff.diff(base, after)["excluded"])
        base["compile"]["P"]["ok"] = True
        self.assertEqual(diff.diff(base, after)["exclusion_reason"], "compile_failure")

    def test_apply_and_cics_reasons(self):
        self.assertEqual(diff.diff(_run({}), _run({}, apply_error="x"))["exclusion_reason"], "apply_failure")
        self.assertEqual(diff.diff(_run({}), _run({}, cics_only=True))["exclusion_reason"], "cics_only")

    def test_status_changes(self):
        s = {"job": "J", "step": "S", "procstep": None, "program": "P", "status": "ok", "rc": 0}
        t = dict(s, status="abend", rc=None)
        d = diff.diff(_run({}, steps=[s]), _run({}, steps=[t]))
        self.assertEqual(d["status_changes"], [{"step": "J.S", "before": {"status": "ok", "rc": 0},
                                                "after": {"status": "abend", "rc": None}}])
        self.assertEqual(diff.diff(_run({}, steps=[s]), _run({}, steps=[s]))["status_changes"], [])


if __name__ == "__main__":
    unittest.main()
