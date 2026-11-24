"""F4, the seeded-change generator and change application (lane P3a)."""
import json
import shutil
import subprocess

from groundtruth import changes, generate
from tests.red._support import MINI, TempDirCase, assert_schema, copy_tree, mini_change, mini_runset, tree_digest

CLASSES = ["copybook_field", "program_logic", "jcl_step", "noop"]


class GenerateRed(TempDirCase):
    def test_same_seed_same_change(self):
        """generate(cls, seed) twice gives the same change, of that class, whose before-lines match the tree."""
        rs = mini_runset()
        for cls in CLASSES:
            a = generate.generate(cls, 7, MINI, rs)
            b = generate.generate(cls, 7, MINI, rs)
            self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True), cls)
            assert_schema(self, a, "change.schema.json")
            self.assertEqual(a["class"], cls)
            for e in a["edits"]:
                if e["op"] == "replace":
                    lines = (MINI / e["file"]).read_bytes().decode().split("\n")
                    self.assertEqual(lines[e["line"] - 1], e["before"])

    def test_each_class_compiles_or_is_marked(self):
        """Every generated change either compiles (compile_break false) or is marked compile_break true."""
        rs = mini_runset()
        for cls in CLASSES:
            for seed in range(1, 6):
                ch = generate.generate(cls, seed, MINI, rs)
                self.assertIn(ch["compile_break"], (True, False), f"{cls} seed {seed}")
                cobc = shutil.which("cobc")
                self.assertIsNotNone(cobc, "cobc not found: run scripts/setup.sh")
                root = copy_tree(MINI, self.tmp / f"{cls}-{seed}")
                changes.apply(ch, root)
                rcs = [subprocess.run([cobc, "-fsyntax-only", *rs["cobc_flags"], "-I", str(root / "app/cpy"),
                                       str(root / "app/cbl" / f"{p}.cbl")], capture_output=True).returncode
                       for p in rs["programs"]]
                self.assertEqual(any(rcs), ch["compile_break"], f"{cls} seed {seed}: rcs {rcs}")
                shutil.rmtree(root.parent)

    def test_apply_is_all_or_nothing(self):
        """A change whose second edit does not match writes nothing; a good change writes exactly its line."""
        root = copy_tree(MINI, self.tmp)
        before = tree_digest(root)
        bad = mini_change("field-label")
        bad["edits"].append(dict(bad["edits"][0], line=1, before="no such line"))
        with self.assertRaises(changes.ApplyError):
            changes.apply(bad, root)
        self.assertEqual(tree_digest(root), before)
        good = mini_change("field-label")
        changes.apply(good, root)
        e = good["edits"][0]
        self.assertEqual((root / e["file"]).read_text().split("\n")[e["line"] - 1], e["after"])
