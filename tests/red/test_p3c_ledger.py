"""F6, the hash-chained ledger, revert and the CLI (lane P3c)."""
import json
import subprocess
import sys

from approval.ledger import Ledger
from tests.red._support import MINI, REPO, TempDirCase, assert_schema, copy_tree, mini_change, tree_digest


def _record(name, decision="allow"):
    ch = mini_change(name)
    radius = {"change_id": ch["id"], "members": [], "fields": [], "programs": [], "jobs": [], "steps": [],
              "datasets": [], "unverifiable": [], "why": {}, "predictor": {"name": "test", "version": "0"}}
    return {"change": ch, "radius": radius, "decision": {"decision": decision, "items": []},
            "decided_by": "red-test", "note": ""}


class LedgerRed(TempDirCase):
    def _two_entries(self):
        root = copy_tree(MINI, self.tmp / "tree")
        led = Ledger(self.tmp / "ledger")
        led.approve(_record("field-label"), root)
        led.approve(_record("jcl-sort"), root)
        led.deny(_record("field-factor", "deny"))
        lines = (self.tmp / "ledger" / "ledger.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 3)
        for ln in lines:
            assert_schema(self, json.loads(ln), "ledger-entry.schema.json")
        self.assertTrue(led.verify()["ok"])
        return led, root, lines

    def _write(self, lines):
        (self.tmp / "ledger" / "ledger.jsonl").write_text("\n".join(lines) + "\n")

    def test_verify_catches_an_edited_entry(self):
        led, _, lines = self._two_entries()
        e = json.loads(lines[0])
        e["record"]["decided_by"] = "someone else"
        lines[0] = json.dumps(e, sort_keys=True, separators=(",", ":"))
        self._write(lines)
        v = led.verify()
        self.assertFalse(v["ok"])
        self.assertIn(1, [p["seq"] for p in v["problems"]])

    def test_verify_catches_a_deleted_entry(self):
        led, _, lines = self._two_entries()
        self._write([lines[0], lines[2]])
        self.assertFalse(led.verify()["ok"])

    def test_verify_catches_a_reordered_entry(self):
        led, _, lines = self._two_entries()
        self._write([lines[1], lines[0], lines[2]])
        self.assertFalse(led.verify()["ok"])

    def test_revert_restores_bytes(self):
        """approve then revert gives back the original tree byte for byte."""
        root = copy_tree(MINI, self.tmp / "tree")
        original = tree_digest(root)
        led = Ledger(self.tmp / "ledger")
        e = led.approve(_record("field-label"), root)
        self.assertNotEqual(tree_digest(root), original)
        led.revert(e["seq"], root)
        self.assertEqual(tree_digest(root), original)

    def test_revert_appends_and_never_rewrites(self):
        led, root, lines = self._two_entries()
        led.revert(1, root)
        after = (self.tmp / "ledger" / "ledger.jsonl").read_text().splitlines()
        self.assertEqual(after[:3], lines)
        last = json.loads(after[3])
        self.assertEqual((last["seq"], last["kind"], last["reverts"]), (4, "revert", 1))
        self.assertEqual(last["prev_sha256"], json.loads(lines[2])["entry_sha256"])
        self.assertTrue(led.verify()["ok"])
        with self.assertRaises(Exception):
            led.revert(1, root)

    def test_cli_verify(self):
        """python3 -m approval.cli verify --ledger <dir> prints the verify result as JSON (an empty ledger is ok)."""
        out = subprocess.run([sys.executable, "-m", "approval.cli", "verify", "--ledger", str(self.tmp / "ledger")],
                             cwd=REPO, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["ok"], True)
