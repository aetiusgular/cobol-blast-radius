"""Lane P3b unit tests on CardDemo: format, determinism and hand-written changes.

Reads only the dev rows of the frozen split (contracts/eval.md rule 1).
"""
import json
import unittest
from pathlib import Path

from radius import graph, predict

REPO = Path(__file__).resolve().parents[2]
CARDDEMO = REPO / "vendor" / "carddemo"
RUNSET = json.loads((REPO / "contracts" / "runset.json").read_text())
SCHEMA = json.loads((REPO / "contracts" / "radius.schema.json").read_text())
LISTS = ("members", "fields", "programs", "jobs", "steps", "datasets", "unverifiable")


def dev_rows():
    rows = [json.loads(l) for l in (REPO / "contracts" / "split.jsonl").read_text().splitlines() if l.strip()]
    return [r for r in rows if r.get("split") == "dev"]


def edit(rel, find, new_text=None, insert=None):
    """A one-edit change on the first line of `rel` that contains `find`."""
    lines = (CARDDEMO / rel).read_text().split("\n")
    n = next(i for i, l in enumerate(lines) if find in l) + 1
    if insert is not None:
        e = {"file": rel, "line": n, "op": "insert_after", "before": None, "after": insert}
    else:
        e = {"file": rel, "line": n, "op": "replace", "before": lines[n - 1], "after": lines[n - 1].replace(find, new_text)}
    return {"id": "T-1", "class": "program_logic", "seed": None, "summary": "", "edits": [e], "compile_break": None}


class CardDemoPredict(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (CARDDEMO / "app" / "cbl").is_dir():
            raise AssertionError("vendor/carddemo is missing: run scripts/setup.sh")
        cls.g = graph.build(CARDDEMO)
        run_jobs = {j["job"] for j in RUNSET["jobs"]}
        cls.outputs = {b.split(":", 1)[1] for a, k, b in cls.g.edges if k == "WRITES" and a.split(":")[1].split(".")[0] in run_jobs}

    def check(self, r):
        from tests.red._support import schema_errors
        self.assertEqual(schema_errors(r, SCHEMA), [])
        for k in LISTS:
            self.assertEqual(r[k], sorted(set(r[k])), k)
        self.assertEqual(set(r["why"]), set(r["datasets"]))
        for d, path in r["why"].items():
            self.assertEqual(path[-1], f"dataset:{d}")
        self.assertTrue(set(r["datasets"]) <= self.outputs, set(r["datasets"]) - self.outputs)

    def test_graph_parses_every_carddemo_source(self):
        self.assertEqual(self.g.errors, [])

    def test_dev_rows_well_formed_and_repeatable(self):
        for c in dev_rows():
            with self.subTest(c["id"]):
                r = predict.predict(c, CARDDEMO, RUNSET)
                self.check(r)
                self.assertEqual(r, predict.predict(c, CARDDEMO, RUNSET))
                e = predict.predict_e0(c, CARDDEMO, RUNSET)
                self.check(e)
                self.assertEqual(e["predictor"]["name"], "e0-one-hop")
                if c["class"] == "noop":
                    self.assertEqual((r["programs"], r["jobs"], r["steps"], r["datasets"]), ([], [], [], []))

    def test_comment_inserted_in_a_program_reaches_nothing(self):
        r = predict.predict(edit("app/cbl/CBTRN02C.cbl", "PROCEDURE DIVISION", insert="      * note"), CARDDEMO, RUNSET)
        self.assertEqual(r["members"], ["CBTRN02C"])
        self.assertEqual(r["datasets"], [])

    def test_display_literal_reaches_only_its_sysout(self):
        r = predict.predict(edit("app/cbl/CBACT01C.cbl", "'ACCT-GROUP-ID           :'", "'ACCT-GROUP-ID          ::'"), CARDDEMO, RUNSET)
        self.assertEqual(r["datasets"], ["SYSOUT:READACCT.STEP05.SYSOUT"])
        self.assertEqual(r["programs"], ["CBACT01C"])

    def test_sort_key_change_crosses_into_later_jobs(self):
        r = predict.predict(edit("app/jcl/COMBTRAN.jcl", " SORT FIELDS=(TRAN-ID,A)", " SORT FIELDS=(TRAN-ID,D)"), CARDDEMO, RUNSET)
        self.assertIn("AWS.M2.CARDDEMO.TRANSACT.COMBINED", r["datasets"])
        self.assertIn("AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS", r["datasets"])
        self.assertNotIn("AWS.M2.CARDDEMO.ACCTDATA.PSCOMP", r["datasets"])
        self.assertIn("COMBTRAN.STEP05R", r["steps"])

    def test_copybook_field_reaches_cics_as_unverifiable(self):
        r = predict.predict(edit("app/cpy/CVACT01Y.cpy", "ACCT-CURR-BAL", "ACCT-CURR-BAX"), CARDDEMO, RUNSET)
        self.assertEqual(r["fields"], ["CVACT01Y.ACCT-CURR-BAL", "CVACT01Y.ACCT-CURR-BAX"])
        self.assertTrue(any(u.startswith("program:CO") for u in r["unverifiable"]), r["unverifiable"])


if __name__ == "__main__":
    unittest.main()
