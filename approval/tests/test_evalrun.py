"""Lane P3c unit tests: scoring, exclusions, provenance and the CLI (contracts/eval.md, seams.md)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from approval import cli, evalrun

REPO = Path(__file__).resolve().parents[2]
CONTRACTS = REPO / "contracts"
MINI = REPO / "fixtures" / "mini"
RUNSET = {"carddemo_commit": "fixture"}


def ch(cid, cls):
    return {"id": cid, "class": cls, "seed": None, "summary": "", "edits": [], "compile_break": None}


def fakes(table):
    """table: change id -> (predicted datasets or an Exception, changed, universe, exclusion reason)."""
    def predict(c):
        p = table[c["id"]][0]
        if isinstance(p, Exception):
            raise p
        return {"change_id": c["id"], "datasets": p, "unverifiable": [], "predictor": {"name": "fake", "version": "1"}}

    def truth(c):
        _, changed, universe, reason = table[c["id"]]
        return {"change_id": c["id"], "changed": changed, "unchanged": sorted(set(universe) - set(changed)),
                "excluded": reason is not None, "exclusion_reason": reason, "status_changes": []}
    return predict, truth


class EvalUnit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def split(self, changes, split="dev"):
        p = self.tmp / "split.jsonl"
        p.write_text("".join(json.dumps(dict(c, split=split)) + "\n" for c in changes))
        return p

    def test_exclusions_errors_classes_and_noops(self):
        U = ["A", "B", "C"]
        table = {"c1": (["A", "B"], ["A"], U, None),            # 1 hit, 1 false alarm
                 "c2": (RuntimeError("boom"), ["C"], U, None),    # predictor crash: a miss, shown
                 "c3": (["A"], ["A", "B", "C"], U, "compile_failure"),
                 "n1": ([], [], U, None),
                 "n2": (["B"], [], U, None)}
        changes = [ch("c1", "copybook_field"), ch("c2", "program_logic"), ch("c3", "program_logic"),
                   ch("n1", "noop"), ch("n2", "noop")]
        predict, truth = fakes(table)
        rows = evalrun.run("dev", self.split(changes), CONTRACTS / "eval.md", MINI, RUNSET,
                           self.tmp / "out.jsonl", predict, truth)
        s = rows[-1]
        self.assertEqual((s["hits"], s["changed_count"], s["predicted_count"]), (1, 2, 3))
        self.assertAlmostEqual(s["recall"], 1 / 2)
        self.assertAlmostEqual(s["precision"], 1 / 3)
        self.assertEqual(s["excluded_by_reason"], {"compile_failure": 1})
        self.assertEqual(s["predict_errors"], 1)
        self.assertEqual((s["noop"]["correct"], s["noop"]["incorrect"], s["noop"]["ids_incorrect"]), (1, 1, ["n2"]))
        self.assertIsNone(s["per_class"]["program_logic"]["precision"])
        self.assertEqual(s["per_class"]["program_logic"]["recall"], 0.0)
        by = {r["change_id"]: r for r in rows if r["kind"] == "change"}
        self.assertEqual(by["c2"]["predictor"], "error")
        self.assertIn("boom", by["c2"]["predict_error"])
        self.assertEqual(by["c1"]["false_positive"], ["B"])
        self.assertIsNone(by["c3"]["recall"])
        self.assertEqual(s["predictor"], "fake@1")

    def test_outside_universe_is_its_own_column(self):
        predict, truth = fakes({"c1": (["A", "ZZ"], ["A"], ["A", "B"], None)})
        rows = evalrun.run("dev", self.split([ch("c1", "jcl_step")]), CONTRACTS / "eval.md", MINI, RUNSET,
                           self.tmp / "o.jsonl", predict, truth)
        self.assertEqual(rows[0]["predicted"], ["A"])
        self.assertEqual(rows[0]["predicted_outside_universe"], ["ZZ"])
        self.assertEqual(rows[-1]["precision"], 1.0)

    def test_only_rows_of_the_split_run(self):
        p = self.tmp / "split.jsonl"
        p.write_text(json.dumps(dict(ch("d", "noop"), split="dev")) + "\n"
                     + json.dumps(dict(ch("h", "noop"), split="heldout")) + "\n")
        predict, truth = fakes({"d": ([], [], [], None)})
        rows = evalrun.run("dev", p, CONTRACTS / "eval.md", MINI, RUNSET, self.tmp / "o.jsonl", predict, truth)
        self.assertEqual([r.get("change_id") for r in rows], ["d", None])

    def test_frozen_split_is_marked_and_rows_append(self):
        table = {}
        for ln in (CONTRACTS / "split.jsonl").read_text().splitlines():
            table[json.loads(ln)["id"]] = ([], [], [], None)
        predict, truth = fakes(table)
        out = self.tmp / "E1-dev.jsonl"
        first = evalrun.run("dev", CONTRACTS / "split.jsonl", CONTRACTS / "eval.md", MINI, RUNSET, out, predict, truth)
        second = evalrun.run("dev", CONTRACTS / "split.jsonl", CONTRACTS / "eval.md", MINI, RUNSET, out, predict, truth)
        self.assertEqual(len(first), 21)
        self.assertTrue(first[-1]["split_matches_contract"])
        self.assertEqual(len(out.read_text().splitlines()), 42)
        strip = lambda rows: [{k: v for k, v in r.items() if k not in ("run_id", "date")} for r in rows]
        self.assertEqual(strip(first), strip(second))  # eval.md rule 4: a repeat run is identical
        self.assertNotEqual(first[0]["run_id"], second[0]["run_id"])

    def test_rows_come_from_the_bytes_that_were_hashed(self):
        p = self.tmp / "split.jsonl"
        p.write_text(json.dumps(dict(ch("other", "noop"), split="dev")) + "\n")
        data = (json.dumps(dict(ch("hashed", "noop"), split="dev")) + "\n").encode()
        self.assertEqual([c["id"] for c in evalrun.load_split(p, "dev", data)], ["hashed"])
        self.assertEqual([c["id"] for c in evalrun.load_split(p, "dev")], ["other"])

    def test_a_dev_run_on_another_file_is_marked(self):
        predict, truth = fakes({"c": ([], [], [], None)})
        rows = evalrun.run("dev", self.split([ch("c", "noop")]), CONTRACTS / "eval.md", MINI, RUNSET,
                           self.tmp / "o.jsonl", predict, truth)
        self.assertFalse(rows[-1]["split_matches_contract"])

    def test_unknown_split_is_refused(self):
        with self.assertRaises(ValueError):
            evalrun.run("test", self.split([]), CONTRACTS / "eval.md", MINI, RUNSET, self.tmp / "o", None, None)

    def test_broken_baseline_stops_the_eval(self):
        base = {"compile": {"P1": {"ok": False, "diagnostics": "no"}}, "outputs": {}, "steps": []}
        with mock.patch("groundtruth.harness.run", return_value=base):
            gt = cli.harness_ground_truth(MINI, RUNSET, self.tmp)
            with self.assertRaises(cli.BaselineBroken):
                gt(ch("c", "noop"))


class CliUnit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        import shutil
        self.root = self.tmp / "tree"
        shutil.copytree(MINI, self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def cli(self, *args):
        out = subprocess.run([sys.executable, "-m", "approval.cli", *map(str, args)], cwd=REPO,
                             capture_output=True, text=True)
        return out.returncode, (json.loads(out.stdout) if out.stdout.strip() else None), out.stderr

    def rules(self, rules):
        p = self.tmp / f"rules{len(rules)}.json"
        p.write_text(json.dumps({"rules": rules}))
        return p

    def common(self):
        return ["--root", self.root, "--runset", MINI / "runset.json", "--ledger", self.tmp / "led", "--by", "unit"]

    def test_ask_needs_confirm_and_deny_is_recorded_not_applied(self):
        c = MINI / "changes" / "field-label.json"
        before = (self.root / "app/cpy/MINICNST.cpy").read_bytes()
        code, doc, _ = self.cli("approve", "--change", c, "--allowlist", self.rules([]), *self.common())
        self.assertEqual((code, doc["refused"]), (3, "ask"))
        self.assertFalse((self.tmp / "led" / "ledger.jsonl").exists())
        code, doc, _ = self.cli("approve", "--change", c, "--allowlist",
                                self.rules([{"pattern": "MINI.SUMFILE", "action": "deny"}]), *self.common())
        self.assertEqual((code, doc["refused"], doc["entry"]["kind"]), (4, "deny", "deny"))
        self.assertEqual((self.root / "app/cpy/MINICNST.cpy").read_bytes(), before)
        code, doc, _ = self.cli("approve", "--change", c, "--allowlist", self.rules([]), "--confirm", *self.common())
        self.assertEqual((code, doc["kind"], doc["seq"]), (0, "approve", 2))
        self.assertEqual(doc["record"]["radius"]["datasets"], ["MINI.SUMFILE", "SYSOUT:MINIJOB2.STEP2.SYSOUT"])
        self.assertNotEqual((self.root / "app/cpy/MINICNST.cpy").read_bytes(), before)
        code, doc, _ = self.cli("revert", "--ledger", self.tmp / "led", "--seq", 2, "--root", self.root)
        self.assertEqual((code, doc["reverts"]), (0, 2))
        self.assertEqual((self.root / "app/cpy/MINICNST.cpy").read_bytes(), before)

    def test_verify_expect_head_catches_a_truncated_tail(self):
        c = MINI / "changes" / "noop-comment.json"
        self.cli("deny", "--change", c, *self.common())
        self.cli("deny", "--change", c, *self.common())
        code, doc, _ = self.cli("verify", "--ledger", self.tmp / "led")
        head = doc["head_sha256"]
        f = self.tmp / "led" / "ledger.jsonl"
        f.write_text(f.read_text().splitlines()[0] + "\n")
        self.assertEqual(self.cli("verify", "--ledger", self.tmp / "led")[0], 0)
        code, doc, _ = self.cli("verify", "--ledger", self.tmp / "led", "--expect-head", head)
        self.assertEqual((code, doc["ok"]), (1, False))

    def test_a_supplied_radius_must_name_the_edited_members(self):
        # CB-P3c-r1-S1: a radius file without the edited member let a deny rule on it go unchecked.
        c = MINI / "changes" / "field-label.json"
        before = (self.root / "app/cpy/MINICNST.cpy").read_bytes()
        code, radius, _ = self.cli("predict", "--change", c, "--root", self.root, "--runset", MINI / "runset.json")
        self.assertEqual((code, radius["members"]), (0, ["MINICNST"]))
        radius["members"] = []
        rp = self.tmp / "radius.json"
        rp.write_text(json.dumps(radius))
        rules = self.rules([{"pattern": "MINICNST", "kind": "member", "action": "deny"}, {"pattern": "**", "action": "allow"}])
        code, doc, err = self.cli("approve", "--change", c, "--radius", rp, "--allowlist", rules, *self.common())
        self.assertEqual((code, doc), (2, None))
        self.assertIn("edited members", json.loads(err)["error"])
        self.assertEqual((self.root / "app/cpy/MINICNST.cpy").read_bytes(), before)
        self.assertFalse((self.tmp / "led" / "ledger.jsonl").exists())
        code, doc, _ = self.cli("approve", "--change", c, "--allowlist", rules, *self.common())
        self.assertEqual((code, doc["refused"]), (4, "deny"))

    def test_a_supplied_radius_must_include_the_predicted_items(self):
        # CB-P3c-r2-S1: a radius file that kept the edited member but dropped a denied dataset was applied as allow.
        c = MINI / "changes" / "field-label.json"
        before = (self.root / "app/cpy/MINICNST.cpy").read_bytes()
        code, radius, _ = self.cli("predict", "--change", c, "--root", self.root, "--runset", MINI / "runset.json")
        self.assertIn("MINI.SUMFILE", radius["datasets"])
        rules = self.rules([{"pattern": "MINI.SUMFILE", "kind": "dataset", "action": "deny"}, {"pattern": "**", "action": "allow"}])
        narrow = dict(radius, programs=[], jobs=[], datasets=[], why={})
        rp = self.tmp / "narrow.json"
        rp.write_text(json.dumps(narrow))
        code, doc, err = self.cli("approve", "--change", c, "--radius", rp, "--allowlist", rules, *self.common())
        self.assertEqual((code, doc), (2, None))
        self.assertIn("predicted items", json.loads(err)["error"])
        self.assertEqual((self.root / "app/cpy/MINICNST.cpy").read_bytes(), before)
        self.assertFalse((self.tmp / "led" / "ledger.jsonl").exists())
        wide = self.tmp / "wide.json"
        wide.write_text(json.dumps(dict(radius, datasets=radius["datasets"] + ["EXTRA.DS"])))
        code, doc, _ = self.cli("approve", "--change", c, "--radius", wide, "--allowlist", rules, *self.common())
        self.assertEqual((code, doc["refused"]), (4, "deny"))

    def test_predicted_radii_name_their_edited_members(self):
        from approval import allowlist
        from radius import predict as rp
        for p in sorted((MINI / "changes").glob("*.json")):
            ch = json.loads(p.read_text())
            for fn in (rp.predict, rp.predict_e0):
                allowlist.check_radius_covers(ch, fn(ch, self.root, json.loads((MINI / "runset.json").read_text())))

    def test_errors_go_to_stderr_with_exit_2(self):
        code, doc, err = self.cli("revert", "--ledger", self.tmp / "led", "--seq", 1, "--root", self.root)
        self.assertEqual((code, doc), (2, None))
        self.assertIn("no entry 1", json.loads(err)["error"])


if __name__ == "__main__":
    unittest.main()
