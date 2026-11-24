"""F2, predicting the blast radius (lane P3b)."""
from radius import predict
from tests.red._support import MINI, TempDirCase, assert_schema, mini_change, mini_runset

RPT_OUT = "MINI.OUTFILE"
RPT_SYSOUT = "SYSOUT:MINIJOB1.STEP1.RUN.SYSOUT"
SUM_SYSOUT = "SYSOUT:MINIJOB2.STEP2.SYSOUT"


class PredictRed(TempDirCase):
    def _predict(self, name, e0=False):
        fn = predict.predict_e0 if e0 else predict.predict
        r = fn(mini_change(name), MINI, mini_runset())
        assert_schema(self, r, "radius.schema.json")
        self.assertEqual(r["change_id"], mini_change(name)["id"])
        return r

    def test_field_level_not_whole_copybook(self):
        """MC-LABEL is used only by MINISUM, so MINIRPT's outputs are not in the radius though it COPYs MINICNST."""
        r = self._predict("field-label")
        self.assertEqual(r["fields"], ["MINICNST.MC-LABEL"])
        self.assertIn("MINI.SUMFILE", r["datasets"])
        self.assertIn(SUM_SYSOUT, r["datasets"])
        for d in (RPT_OUT, "MINI.SORTED", RPT_SYSOUT):
            self.assertNotIn(d, r["datasets"])
        self.assertNotIn("MINIRPT", r["programs"])

    def test_unperformed_paragraph_gives_empty_radius(self):
        """A change only inside a paragraph nothing PERFORMs reaches nothing."""
        r = self._predict("unperformed")
        self.assertEqual((r["programs"], r["jobs"], r["steps"], r["datasets"]), ([], [], [], []))

    def test_datasets_passed_between_jobs(self):
        """MC-FACTOR feeds MINIRPT's output, which MINIJOB2 sorts and sums: the radius crosses the job boundary."""
        r = self._predict("field-factor")
        for d in (RPT_OUT, "MINI.SORTED", "MINI.SUMFILE", SUM_SYSOUT):
            self.assertIn(d, r["datasets"])
        self.assertIn("MINIJOB2", r["jobs"])
        self.assertIn("dataset:MINI.OUTFILE", r["why"]["MINI.SUMFILE"])

    def test_noop_gives_empty_radius(self):
        """A comment-only change touches its member and nothing else."""
        r = self._predict("noop-comment")
        self.assertEqual(r["members"], ["MINIRPT"])
        self.assertEqual((r["fields"], r["programs"], r["jobs"], r["steps"], r["datasets"]), ([], [], [], [], []))

    def test_e0_is_one_hop(self):
        """E0: every output of every job that runs a program COPYing the changed member."""
        r = self._predict("field-label", e0=True)
        self.assertEqual(r["predictor"]["name"], "e0-one-hop")
        self.assertEqual(r["datasets"], sorted([RPT_OUT, RPT_SYSOUT, "MINI.SORTED", "MINI.SUMFILE", SUM_SYSOUT]))
