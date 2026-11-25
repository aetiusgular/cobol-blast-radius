"""Lane P3c unit tests: allowlist matching and decisions (contracts/allowlist.md)."""
import itertools
import unittest

from approval import allowlist


def radius(**kw):
    r = {"change_id": "T", "members": ["CVACT01Y"], "programs": ["CBACT01C"], "jobs": ["READACCT"],
         "datasets": ["AWS.M2.CARDDEMO.ACCTDATA.PSCOMP"]}
    r.update(kw)
    return r


class Patterns(unittest.TestCase):
    def m(self, pat, name):
        return bool(allowlist.compile_pattern(pat).fullmatch(name))

    def test_star_question_doublestar(self):
        self.assertTrue(self.m("AWS.*.X", "AWS.M2.X"))
        self.assertFalse(self.m("AWS.*", "AWS.M2.X"))
        self.assertTrue(self.m("AWS.**", "AWS.M2.X"))
        self.assertTrue(self.m("AWS.**", "AWS."))
        self.assertTrue(self.m("CB?CT01C", "CBACT01C"))
        self.assertFalse(self.m("A?B", "A.B"))
        self.assertFalse(self.m("CBACT01", "CBACT01C"))   # whole name
        self.assertFalse(self.m("cbact01c", "CBACT01C"))  # case-sensitive

    def test_regex_characters_are_literal(self):
        self.assertTrue(self.m("SYSOUT:JOB(1)+[x]", "SYSOUT:JOB(1)+[x]"))
        self.assertFalse(self.m("A.B", "AXB"))
        self.assertFalse(self.m("A^B$", "AB"))


class Decide(unittest.TestCase):
    def test_kind_limits_a_rule(self):
        d = allowlist.decide(radius(datasets=["CVACT01Y"]), [{"pattern": "CVACT01Y", "kind": "dataset", "action": "deny"}])
        by = {(i["kind"], i["name"]): i for i in d["items"]}
        self.assertEqual(by[("member", "CVACT01Y")]["rules"], [])
        self.assertEqual(by[("member", "CVACT01Y")]["action"], "ask")
        self.assertEqual(by[("dataset", "CVACT01Y")]["action"], "deny")

    def test_explicit_any_is_every_kind(self):
        d = allowlist.decide(radius(), [{"pattern": "**", "kind": "any", "action": "allow"}])
        self.assertEqual(d["decision"], "allow")
        self.assertTrue(all(i["rules"] == [0] for i in d["items"]))

    def test_no_permutation_changes_the_decision(self):
        rules = [{"pattern": "**", "action": "allow"}, {"pattern": "CB*", "kind": "program", "action": "ask"},
                 {"pattern": "AWS.**", "kind": "dataset", "action": "allow"}, {"pattern": "READ*", "action": "deny"}]
        seen = set()
        for perm in itertools.permutations(rules):
            d = allowlist.decide(radius(), list(perm))
            seen.add((d["decision"], tuple((i["kind"], i["name"], i["action"]) for i in d["items"])))
        self.assertEqual(len(seen), 1)
        self.assertEqual(next(iter(seen))[0], "deny")

    def test_item_order_follows_the_contract(self):
        d = allowlist.decide(radius(datasets=["B", "A"]), [])
        self.assertEqual([(i["kind"], i["name"]) for i in d["items"]],
                         [("member", "CVACT01Y"), ("program", "CBACT01C"), ("job", "READACCT"),
                          ("dataset", "B"), ("dataset", "A")])

    def test_no_items_asks(self):
        self.assertEqual(allowlist.decide({}, [{"pattern": "**", "action": "allow"}])["decision"], "ask")

    def test_bad_rules_are_refused(self):
        for bad in ([{"pattern": "", "action": "allow"}], [{"pattern": "X", "action": "maybe"}],
                    [{"pattern": "X", "action": "allow", "kind": "step"}],
                    [{"pattern": "X", "action": "allow", "extra": 1}], {"rules": []}):
            with self.assertRaises(allowlist.RuleError):
                allowlist.decide(radius(), bad)


class RadiusCovers(unittest.TestCase):
    CH = {"id": "T", "edits": [{"file": "app/cpy/CVACT01Y.cpy"}, {"file": "app/jcl/readacct.jcl"}]}

    def test_edited_members(self):
        self.assertEqual(allowlist.edited_members(self.CH), ["CVACT01Y", "READACCT"])

    def test_a_radius_must_name_every_edited_member(self):
        allowlist.check_radius_covers(self.CH, radius(members=["CVACT01Y", "READACCT"]))
        for bad in (radius(members=["READACCT"]), radius(members=[]), radius(change_id="U", members=["CVACT01Y", "READACCT"])):
            with self.assertRaises(allowlist.RuleError):
                allowlist.check_radius_covers(self.CH, bad)


if __name__ == "__main__":
    unittest.main()
