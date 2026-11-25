"""The three lanes together on fixtures/mini (P4 cross-lane tests)."""
import json
import os
import shutil

from groundtruth import diff as gtdiff
from groundtruth import harness
from radius import graph, predict
from tests.integration._common import (MINI, TempDirCase, cli, load, need_cobc, sha256_file,
                                       tree_digest)

RUNSET = MINI / "runset.json"
CHANGES = sorted((MINI / "changes").glob("*.json"))


class MiniCrossLane(TempDirCase):
    def setUp(self):
        super().setUp()
        need_cobc(self)
        self.runset = load(RUNSET)

    def _tree(self, name="tree"):
        dst = self.tmp / name
        shutil.copytree(MINI, dst)
        return dst

    def _rules(self, rules):
        p = self.tmp / "allowlist.json"
        p.write_text(json.dumps({"rules": rules}))
        return p

    def test_every_harness_output_is_a_graph_dataset(self):
        """P3a and P3b name datasets the same way (runset.md, graph.md)."""
        base = harness.run(MINI, self.runset, self.tmp / "base")
        self.assertSchema(base, "run-result.schema.json")
        nodes = graph.build(MINI).nodes
        missing = sorted(n for n in base["outputs"] if f"dataset:{n}" not in nodes)
        self.assertEqual(missing, [])

    def test_documents_that_cross_lanes_match_their_schemas(self):
        base = harness.run(MINI, self.runset, self.tmp / "base")
        for path in CHANGES:
            ch = load(path)
            with self.subTest(change=ch["id"]):
                self.assertSchema(ch, "change.schema.json")
                rad = predict.predict(ch, MINI, self.runset)
                self.assertSchema(rad, "radius.schema.json")
                self.assertSchema(predict.predict_e0(ch, MINI, self.runset), "radius.schema.json")
                after = harness.run(MINI, self.runset, self.tmp / ch["id"], ch)
                self.assertSchema(after, "run-result.schema.json")
                d = gtdiff.diff(base, after)
                self.assertSchema(d, "diff.schema.json")
                universe = set(d["changed"]) | set(d["unchanged"])
                if not d["excluded"]:
                    self.assertEqual(universe, set(base["outputs"]))

    def test_approve_verify_revert_round_trip(self):
        root = self._tree()
        before = tree_digest(root)
        rules = self._rules([{"pattern": "**", "action": "allow"}])
        rc, entry, err = cli("approve", "--change", MINI / "changes/field-label.json", "--allowlist", rules,
                             "--root", root, "--runset", RUNSET, "--ledger", self.tmp / "led", "--by", "it")
        self.assertEqual(rc, 0, err)
        self.assertSchema(entry, "ledger-entry.schema.json")
        self.assertEqual(entry["record"]["runset_sha256"], sha256_file(RUNSET))
        self.assertEqual(entry["record"]["applied_as"]["uid"], os.geteuid())
        self.assertNotEqual(tree_digest(root), before)
        rc, v, err = cli("verify", "--ledger", self.tmp / "led")
        self.assertEqual(rc, 0, err)
        rc, v, err = cli("verify", "--ledger", self.tmp / "led", "--expect-head", v["head_sha256"])
        self.assertEqual(rc, 0, err)
        rc, rev, err = cli("revert", "--ledger", self.tmp / "led", "--seq", 1, "--root", root)
        self.assertEqual(rc, 0, err)
        self.assertEqual(rev["kind"], "revert")
        self.assertEqual(tree_digest(root), before)

    def test_a_predicted_dataset_reaches_the_allowlist(self):
        """The predictor's datasets drive the decision: a deny rule on one of them stops the change."""
        root = self._tree()
        before = tree_digest(root)
        rad = predict.predict(load(MINI / "changes/field-label.json"), MINI, self.runset)
        self.assertIn("MINI.SUMFILE", rad["datasets"])
        rules = self._rules([{"pattern": "MINI.SUMFILE", "kind": "dataset", "action": "deny"},
                             {"pattern": "**", "action": "allow"}])
        rc, out, err = cli("approve", "--change", MINI / "changes/field-label.json", "--allowlist", rules,
                           "--root", root, "--runset", RUNSET, "--ledger", self.tmp / "led", "--by", "it")
        self.assertEqual(rc, 4, err)
        self.assertEqual(out["entry"]["kind"], "deny")
        self.assertEqual(tree_digest(root), before)

    def test_a_runset_for_another_tree_is_refused(self):
        """CB-P3c-r3-S1: CardDemo's run set on the mini tree predicted an empty radius and allowed a denied change."""
        root = self._tree()
        before = tree_digest(root)
        rules = self._rules([{"pattern": "MINI.SUMFILE", "kind": "dataset", "action": "deny"},
                             {"pattern": "**", "action": "allow"}])
        for extra in ([], ["--radius", self._radius_file()]):
            with self.subTest(radius=bool(extra)):
                rc, out, err = cli("approve", "--change", MINI / "changes/field-label.json", "--allowlist", rules,
                                   "--root", root, "--ledger", self.tmp / "led", "--by", "it", *extra)
                self.assertEqual(rc, 2, (out, err))
                self.assertIn("run set does not describe", err)
                self.assertEqual(tree_digest(root), before)
                led = self.tmp / "led" / "ledger.jsonl"
                self.assertFalse(led.exists() and led.read_text().strip())

    def _radius_file(self):
        ch = load(MINI / "changes/field-label.json")
        p = self.tmp / "radius.json"
        p.write_text(json.dumps(predict.predict(ch, MINI, self.runset)))
        return p

    def test_eval_runner_rows_list_only_schema_fields(self):
        """RFI-P3c-1: every field the runner writes is named in results-row.schema.json."""
        split = self.tmp / "split.jsonl"
        split.write_text("".join(json.dumps(dict(load(p), split="dev")) + "\n" for p in CHANGES))
        out = self.tmp / "E-dev.jsonl"
        rc, summary, err = cli("eval", "--split", "dev", "--split-path", split, "--root", MINI,
                               "--runset", RUNSET, "--out", out, "--workdir", self.tmp / "work")
        self.assertEqual(rc, 0, err)
        rows = [json.loads(ln) for ln in out.read_text().splitlines()]
        self.assertEqual(len(rows), len(CHANGES) + 1)
        props = set(load(MINI.parents[1] / "contracts/results-row.schema.json")["properties"])
        for r in rows:
            self.assertSchema(r, "results-row.schema.json")
            self.assertEqual(sorted(set(r) - props), [], r.get("change_id", "summary"))
        self.assertFalse(summary["split_matches_contract"])
        self.assertEqual(summary["predict_errors"], 0)

    def test_a_step_that_writes_past_the_cap_abends(self):
        """SECURITY.md G-2: the harness caps the size of every file a step's program writes."""
        old = harness.STEP_FILE_CAP
        harness.STEP_FILE_CAP = 64
        try:
            run = harness.run(MINI, self.runset, self.tmp / "capped")
        finally:
            harness.STEP_FILE_CAP = old
        self.assertIn("abend", [s["status"] for s in run["steps"]])
        self.assertTrue(any("output cap" in n for n in run["notes"]), run["notes"])
        full = harness.run(MINI, self.runset, self.tmp / "full")
        self.assertNotIn("abend", [s["status"] for s in full["steps"]])
