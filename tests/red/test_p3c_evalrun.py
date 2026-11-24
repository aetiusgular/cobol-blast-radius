"""F7, the eval runner (lane P3c)."""
import json
import os

from approval import evalrun
from tests.red._support import CONTRACTS, MINI, TempDirCase, assert_schema, mini_change, mini_runset

SECTION6 = ["run_id", "git_sha", "machine", "model_revision", "quant", "runtime", "date"]


def _fakes(calls):
    truth = {"M-factor": ["MINI.OUTFILE", "MINI.SORTED", "MINI.SUMFILE", "SYSOUT:MINIJOB2.STEP2.SYSOUT"],
             "M-noop": []}
    guess = {"M-factor": ["MINI.OUTFILE", "MINI.SUMFILE", "NOT.IN.UNIVERSE"], "M-noop": []}
    universe = sorted(set(truth["M-factor"]) | {"SYSOUT:MINIJOB1.STEP1.RUN.SYSOUT"})

    def predict(ch):
        calls.append(("predict", ch["id"]))
        return {"change_id": ch["id"], "members": [], "fields": [], "programs": [], "jobs": [], "steps": [],
                "datasets": guess[ch["id"]], "unverifiable": [], "why": {},
                "predictor": {"name": "fake", "version": "0"}}

    def ground_truth(ch):
        calls.append(("truth", ch["id"]))
        changed = truth[ch["id"]]
        return {"change_id": ch["id"], "changed": changed, "unchanged": [u for u in universe if u not in changed],
                "excluded": False, "exclusion_reason": None, "status_changes": []}
    return predict, ground_truth


class EvalRunRed(TempDirCase):
    def _split(self):
        p = self.tmp / "split.jsonl"
        rows = [dict(mini_change("field-factor"), split="dev"), dict(mini_change("noop-comment"), split="dev")]
        p.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return p

    def test_rows_carry_section6_fields(self):
        """Each row has the section 6 fields and the eval.md fields; recall and precision are micro averages."""
        calls = []
        predict, truth = _fakes(calls)
        out = self.tmp / "E1-dev.jsonl"
        rows = evalrun.run("dev", self._split(), CONTRACTS / "eval.md", MINI, mini_runset(), out, predict, truth)
        written = [json.loads(ln) for ln in out.read_text().splitlines()]
        self.assertEqual(written, rows)
        for r in rows:
            assert_schema(self, r, "results-row.schema.json")
            for k in SECTION6:
                self.assertIn(k, r)
        summary = [r for r in rows if r["kind"] == "summary"]
        self.assertEqual(len(summary), 1)
        self.assertAlmostEqual(summary[0]["recall"], 2 / 4)
        self.assertAlmostEqual(summary[0]["precision"], 2 / 2)
        self.assertEqual(len({r["run_id"] for r in rows}), 1)

    def test_machine_read_at_run_time(self):
        """FORGE_MACHINE_FILE wins when set; otherwise the CPU model is read from /proc/cpuinfo."""
        f = self.tmp / "machine"
        f.write_text("TESTBOX|1 GiB|no GPU\n")
        old = os.environ.get("FORGE_MACHINE_FILE")
        try:
            os.environ["FORGE_MACHINE_FILE"] = str(f)
            self.assertEqual(evalrun.machine(), "TESTBOX|1 GiB|no GPU")
            del os.environ["FORGE_MACHINE_FILE"]
            cpu = next(ln.split(":", 1)[1].strip() for ln in open("/proc/cpuinfo") if ln.startswith("model name"))
            self.assertTrue(evalrun.machine().startswith(cpu + "|"))
        finally:
            if old is None:
                os.environ.pop("FORGE_MACHINE_FILE", None)
            else:
                os.environ["FORGE_MACHINE_FILE"] = old

    def test_heldout_refused_when_split_hash_differs(self):
        """A heldout run on a split that does not hash to eval.md's split-sha256 stops before any work."""
        tampered = self.tmp / "split.jsonl"
        data = (CONTRACTS / "split.jsonl").read_bytes()
        tampered.write_bytes(data.replace(b'"split":"heldout"', b'"split":"dev"', 1))
        calls = []
        predict, truth = _fakes(calls)
        out = self.tmp / "E1-heldout.jsonl"
        with self.assertRaises(evalrun.SplitHashMismatch):
            evalrun.run("heldout", tampered, CONTRACTS / "eval.md", MINI, mini_runset(), out, predict, truth)
        self.assertEqual(calls, [])
        self.assertFalse(out.exists())
