"""Lane P3c unit tests: the ledger's refusals and tamper checks (contracts/ledger.md)."""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from approval.ledger import ZERO, Ledger, LedgerError, canonical, entry_hash

REPO = Path(__file__).resolve().parents[2]
MINI = REPO / "fixtures" / "mini"


def change(name):
    return json.loads((MINI / "changes" / f"{name}.json").read_text())


def record(name, decision="allow"):
    ch = change(name)
    return {"change": ch, "radius": {"change_id": ch["id"]}, "decision": {"decision": decision, "items": []},
            "decided_by": "unit", "note": ""}


def digest(root):
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


class LedgerUnit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "tree"
        shutil.copytree(MINI, self.root)
        self.led = Ledger(self.tmp / "ledger")
        self.file = self.tmp / "ledger" / "ledger.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_ledger_verifies_with_zero_head(self):
        v = self.led.verify()
        self.assertEqual((v["ok"], v["entries"], v["head_sha256"]), (True, 0, ZERO))

    def test_first_entry_links_to_zero_and_hashes_canonically(self):
        e = self.led.deny(record("noop-comment", "deny"))
        self.assertEqual((e["seq"], e["prev_sha256"], e["files"]), (1, ZERO, []))
        self.assertEqual(e["entry_sha256"], entry_hash(e))
        self.assertEqual(self.file.read_bytes(), canonical(e) + b"\n")

    def test_approve_refuses_a_deny_decision(self):
        before = digest(self.root)
        with self.assertRaises(LedgerError):
            self.led.approve(record("field-label", "deny"), self.root)
        self.assertEqual(digest(self.root), before)
        self.assertFalse(self.file.exists())

    def test_a_change_that_does_not_apply_writes_nothing(self):
        rec = record("field-label")
        rec["change"]["edits"].append(dict(rec["change"]["edits"][0], before="not the line"))
        before = digest(self.root)
        with self.assertRaises(LedgerError):
            self.led.approve(rec, self.root)
        self.assertEqual(digest(self.root), before)
        self.assertEqual(self.led.entries(), [])

    def test_an_edit_outside_the_tree_is_refused(self):
        rec = record("field-label")
        rec["change"]["edits"][0]["file"] = "../outside.cpy"
        (self.tmp / "outside.cpy").write_text("x\n")
        with self.assertRaises(LedgerError):
            self.led.approve(rec, self.root)
        self.assertEqual((self.tmp / "outside.cpy").read_text(), "x\n")

    def test_deny_touches_no_file(self):
        before = digest(self.root)
        self.led.deny(record("field-label", "deny"))
        self.assertEqual(digest(self.root), before)

    def test_revert_refuses_when_the_file_changed_since(self):
        e = self.led.approve(record("field-label"), self.root)
        p = self.root / e["files"][0]["path"]
        p.write_bytes(p.read_bytes() + b"      * a later hand edit\n")
        edited = digest(self.root)
        with self.assertRaises(LedgerError):
            self.led.revert(e["seq"], self.root)
        self.assertEqual(digest(self.root), edited)
        self.assertEqual(len(self.led.entries()), 1)

    def test_only_an_approve_can_be_reverted(self):
        self.led.deny(record("field-label", "deny"))
        with self.assertRaises(LedgerError):
            self.led.revert(1, self.root)
        with self.assertRaises(LedgerError):
            self.led.revert(7, self.root)

    def test_revert_files_swap_before_and_after(self):
        a = self.led.approve(record("field-label"), self.root)
        r = self.led.revert(a["seq"], self.root)
        self.assertEqual(r["files"], [{"path": f["path"], "before_sha256": f["after_sha256"],
                                       "after_sha256": f["before_sha256"]} for f in a["files"]])
        self.assertIsNone(r["record"])

    def test_verify_catches_an_inserted_entry(self):
        self.led.approve(record("field-label"), self.root)
        self.led.deny(record("jcl-sort", "deny"))
        lines = self.file.read_text().splitlines()
        forged = json.loads(lines[1])
        forged["record"]["note"] = "forged"
        forged["entry_sha256"] = entry_hash(forged)  # self-consistent, but the chain breaks after it
        self.file.write_text("\n".join([lines[0], canonical(forged).decode(), lines[1]]) + "\n")
        self.assertFalse(self.led.verify()["ok"])

    def test_verify_catches_a_tampered_object(self):
        e = self.led.approve(record("field-label"), self.root)
        obj = self.tmp / "ledger" / "objects" / e["files"][0]["before_sha256"]
        obj.write_bytes(b"different\n")
        v = self.led.verify()
        self.assertFalse(v["ok"])
        self.assertEqual([p["seq"] for p in v["problems"]], [1])

    def test_verify_catches_a_forged_revert(self):
        self.led.deny(record("field-label", "deny"))
        lines = self.file.read_text().splitlines()
        prev = json.loads(lines[0])["entry_sha256"]
        e = {"seq": 2, "ts": "t", "kind": "revert", "record": None, "reverts": 1, "files": [], "prev_sha256": prev}
        e["entry_sha256"] = entry_hash(e)
        self.file.write_text(lines[0] + "\n" + canonical(e).decode() + "\n")
        self.assertFalse(self.led.verify()["ok"])

    def test_no_append_to_a_broken_chain(self):
        self.led.approve(record("field-label"), self.root)
        e = json.loads(self.file.read_text())
        e["record"]["decided_by"] = "someone else"
        self.file.write_bytes(canonical(e) + b"\n")
        tampered = self.file.read_bytes()
        with self.assertRaises(LedgerError):
            self.led.deny(record("jcl-sort", "deny"))
        with self.assertRaises(LedgerError):
            self.led.revert(1, self.root)
        self.assertEqual(self.file.read_bytes(), tampered)

    def test_a_non_canonical_line_is_reported(self):
        self.led.deny(record("field-label", "deny"))
        e = json.loads(self.file.read_text())
        self.file.write_text(json.dumps(e) + "\n")  # same content, spaces and key order differ
        v = self.led.verify()
        self.assertFalse(v["ok"])
        self.assertTrue(any("canonical" in p["problem"] for p in v["problems"]))


if __name__ == "__main__":
    unittest.main()
