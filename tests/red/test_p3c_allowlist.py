"""F5, the allowlist (lane P3c)."""
from approval import allowlist
from tests.red._support import TempDirCase, assert_schema


def _radius(**kw):
    r = {"change_id": "T-1", "members": ["CVACT01Y"], "fields": [], "programs": ["CBACT01C"],
         "jobs": ["READACCT"], "steps": ["READACCT.STEP05"],
         "datasets": ["AWS.M2.CARDDEMO.ACCTDATA.PSCOMP", "AWS.M2.CARDDEMO.TRANREPT"],
         "unverifiable": [], "why": {}, "predictor": {"name": "test", "version": "0"}}
    r.update(kw)
    return r


class AllowlistRed(TempDirCase):
    def test_strictest_rule_wins_in_any_order(self):
        """deny beats ask beats allow, whatever the rule order; the change takes its strictest item."""
        rules = [{"pattern": "AWS.M2.**", "kind": "dataset", "action": "allow"},
                 {"pattern": "AWS.M2.CARDDEMO.TRANREPT", "kind": "dataset", "action": "deny"}]
        for rs in (rules, list(reversed(rules))):
            assert_schema(self, {"rules": rs}, "allowlist.schema.json")
            d = allowlist.decide(_radius(), rs)
            self.assertEqual(d["decision"], "deny")
            by = {(i["kind"], i["name"]): i["action"] for i in d["items"]}
            self.assertEqual(by[("dataset", "AWS.M2.CARDDEMO.TRANREPT")], "deny")
            self.assertEqual(by[("dataset", "AWS.M2.CARDDEMO.ACCTDATA.PSCOMP")], "allow")

    def test_pattern_matches_datasets_and_members(self):
        """A rule without kind is tried on every item; * stops at a dot and ** does not."""
        rules = [{"pattern": "AWS.M2.CARDDEMO.ACCTDATA.*", "action": "allow"},
                 {"pattern": "CVACT0?Y", "action": "allow"},
                 {"pattern": "AWS.*", "action": "deny"}]
        d = allowlist.decide(_radius(), rules)
        by = {(i["kind"], i["name"]): i for i in d["items"]}
        self.assertEqual(by[("member", "CVACT01Y")]["action"], "allow")
        self.assertEqual(by[("member", "CVACT01Y")]["rules"], [1])
        self.assertEqual(by[("dataset", "AWS.M2.CARDDEMO.ACCTDATA.PSCOMP")]["action"], "allow")
        self.assertEqual(by[("dataset", "AWS.M2.CARDDEMO.ACCTDATA.PSCOMP")]["rules"], [0])
        self.assertEqual(by[("program", "CBACT01C")]["action"], "ask")

    def test_empty_allowlist_asks_everything(self):
        """No rules: every item asks, and so does a change whose radius is only its member."""
        d = allowlist.decide(_radius(), [])
        self.assertEqual(d["decision"], "ask")
        self.assertTrue(d["items"])
        self.assertTrue(all(i["action"] == "ask" and i["rules"] == [] for i in d["items"]))
        empty = _radius(programs=[], jobs=[], steps=[], datasets=[])
        d = allowlist.decide(empty, [])
        self.assertEqual([(i["kind"], i["name"]) for i in d["items"]], [("member", "CVACT01Y")])
        self.assertEqual(d["decision"], "ask")
