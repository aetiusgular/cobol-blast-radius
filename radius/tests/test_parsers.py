"""Lane P3b unit tests: the source, COBOL and JCL layers under the predictor."""
import unittest

from radius import cobol, jcl
from radius.source import Tree, apply_edits, norm_line


class MemTree(Tree):
    """A Tree whose files live in a dict."""

    def __init__(self, files):
        super().__init__("/nonexistent", files)


def cbl(*lines):
    return "\n".join(("       " + l) if not l.startswith("*") else ("      " + l) for l in lines) + "\n"


class SourceTest(unittest.TestCase):
    def test_comment_and_sequence_edits_change_no_line(self):
        text = "000100     MOVE 1 TO X.                                                  SEQ00001\n"
        seq = text.replace("SEQ00001", "SEQ00002").rstrip("\n")
        _, b, a, mm = apply_edits(text, [{"op": "replace", "line": 1, "before": text.rstrip("\n"), "after": seq}], "cobol")
        self.assertEqual((b, a, mm), (set(), set(), 0))
        _, b, a, _ = apply_edits(text, [{"op": "insert_after", "line": 1, "before": None, "after": "      * note"}], "cobol")
        self.assertEqual((b, a), (set(), set()))
        _, b, a, _ = apply_edits(text, [{"op": "insert_after", "line": 0, "before": None, "after": "           MOVE 2 TO X."}], "cobol")
        self.assertEqual((b, a), (set(), {1}))

    def test_line_numbers_follow_earlier_inserts(self):
        text = "//A JOB\n//S1 EXEC PGM=X\n//S2 EXEC PGM=Y\n"
        edits = [
            {"op": "insert_after", "line": 1, "before": None, "after": "//*"},
            {"op": "replace", "line": 4, "before": "//S2 EXEC PGM=Y", "after": "//S2 EXEC PGM=Z"},
        ]
        new, b, a, mm = apply_edits(text, edits, "jcl")
        self.assertEqual((b, a, mm), ({3}, {4}, 0))
        self.assertIn("PGM=Z", new)

    def test_norm_line_kinds(self):
        self.assertIsNone(norm_line("jcl", "//* comment"))
        self.assertIsNone(norm_line("ctl", "/* licence */"))
        self.assertEqual(norm_line("ctl", "  REPRO INFILE(A) /* x */"), "REPRO INFILE(A)")
        self.assertIsNone(norm_line("cobol", "      *    DISPLAY X"))


class CobolTest(unittest.TestCase):
    def test_reference_modification_and_pictures(self):
        toks = cobol.tokenize(cbl("MOVE A TO B(1:WS-LEN).", "05 X PIC S9(4)V99 VALUE -1.5."), "p.cbl")
        texts = [t.text for t in toks]
        self.assertIn("WS-LEN", texts)
        self.assertIn("S9(4)V99", texts)
        self.assertIn("1.5", texts)

    def test_sizes_offsets_redefines_occurs(self):
        toks = cobol.tokenize(cbl(
            "01  R.",
            "    05  A        PIC X(3).",
            "    05  B        PIC S9(7)V99 COMP-3.",
            "    05  C        PIC 9(4) BINARY.",
            "    05  D REDEFINES C PIC XX.",
            "    05  E OCCURS 3 TIMES.",
            "        10 E1    PIC X.",
            "        10 E2    PIC 99.",
            "    05  F        PIC X.",
        ), "p.cbl")
        items, _ = cobol.parse_data(toks)
        by = {i.name: i for i in items}
        self.assertEqual([(by[n].offset, by[n].size) for n in "ABCDF"], [(0, 3), (3, 5), (8, 2), (8, 2), (19, 1)])
        self.assertEqual((by["E"].offset, by["E"].span), (10, 9))
        self.assertEqual(by["R"].size, 20)
        self.assertEqual(by["D"].storage, by["C"].storage)

    def test_copy_replacing_tags_and_nesting(self):
        t = MemTree({
            "app/cbl/P.cbl": cbl("IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "DATA DIVISION.",
                                 "WORKING-STORAGE SECTION.", "COPY T REPLACING ==:X:== BY ==WS==.",
                                 "PROCEDURE DIVISION.", "    STOP RUN."),
            "app/cpy/T.cpy": cbl("01  :X:-REC.", "    COPY K."),
            "app/cpy/K.cpy": cbl("    05  KEY-A PIC X."),
        })
        p = cobol.Program(t, "app/cbl/P.cbl", ["app/cpy"])
        self.assertIn("WS-REC", p.by_name)
        self.assertEqual(p.by_name["KEY-A"][0].lines, {("app/cpy/K.cpy", 1)})
        self.assertEqual(sorted(c.member for c in p.copies), ["K", "T"])

    def _prog(self, *proc):
        t = MemTree({"app/cbl/P.cbl": cbl(
            "IDENTIFICATION DIVISION.", "PROGRAM-ID. P.", "DATA DIVISION.", "WORKING-STORAGE SECTION.",
            "01  G1.", "    05 G1-A PIC X(2).", "    05 G1-B PIC X(2).",
            "01  G2.", "    05 G2-A PIC X(2).", "    05 G2-B PIC X(2).",
            "01  F PIC X.", "    88 F-ON VALUE 'Y'.", "01  N PIC 9.",
            "PROCEDURE DIVISION.", *proc)})
        return cobol.Program(t, "app/cbl/P.cbl", [])

    def test_unreached_paragraph_and_fallthrough(self):
        p = self._prog("MAIN-PARA.", "    PERFORM A-PARA", "    STOP RUN.", "A-PARA.", "    DISPLAY 'A'.",
                       "B-PARA.", "    DISPLAY 'B'.")
        reach, flow = cobol.reachable(p)
        self.assertEqual({p.paras[k].name for k in reach}, {"MAIN-PARA", "A-PARA"})
        p = self._prog("MAIN-PARA.", "    DISPLAY 'M'.", "NEXT-PARA.", "    STOP RUN.")
        self.assertEqual(cobol.reachable(p)[0], {0, 1})

    def test_group_move_keeps_byte_positions(self):
        p = self._prog("MAIN-PARA.", "    MOVE G1 TO G2", "    DISPLAY G2-A", "    STOP RUN.")
        tn = cobol.Taint()
        tn.add(p.by_name["G1-B"])
        sinks, _ = cobol.analyse(p, tn, set())
        self.assertEqual(sinks, {})
        self.assertTrue(tn.hit(p.by_name["G2-B"]))
        tn.add(p.by_name["G1-A"])
        sinks, _ = cobol.analyse(p, tn, set())
        self.assertEqual(sinks, {"SYSOUT": "content"})

    def test_condition_controls_its_branch(self):
        p = self._prog("MAIN-PARA.", "    IF F-ON", "        MOVE 1 TO N", "    END-IF", "    DISPLAY N",
                       "    STOP RUN.")
        tn = cobol.Taint()
        tn.conds88.add(p.by_name["F-ON"][0])
        sinks, flags = cobol.analyse(p, tn, set())
        self.assertEqual(sinks, {"SYSOUT": "content"})
        self.assertFalse(flags["terminates"])

    def test_tainted_stop_ends_every_output(self):
        p = self._prog("MAIN-PARA.", "    IF N = 1", "        STOP RUN", "    END-IF", "    DISPLAY 'X'",
                       "    STOP RUN.")
        tn = cobol.Taint()
        tn.add(p.by_name["N"])
        sinks, flags = cobol.analyse(p, tn, set())
        self.assertTrue(flags["terminates"])
        self.assertEqual(sinks, {"SYSOUT": "shape"})


class JclTest(unittest.TestCase):
    def test_continuation_concatenation_instream_and_gdg(self):
        t = MemTree({"app/jcl/J.jcl": "\n".join([
            "//J JOB 'X',CLASS=A,",
            "// NOTIFY=&SYSUID",
            "//S1 EXEC PGM=SORT",
            "//SORTIN DD DISP=SHR,",
            "//         DSN=A.B(0)",
            "//         DD DISP=SHR,DSN=C.D",
            "//SYSIN DD *",
            " SORT FIELDS=(1,5,CH,A)",
            "/*",
            "//SORTOUT DD DSN=E.F(+1),DISP=(NEW,CATLG,DELETE)",
        ])})
        j = jcl.JclReader(t).read_job("app/jcl/J.jcl")
        st = j.steps[0]
        self.assertEqual((j.name, st.id, st.pgm), ("J", "J.S1", "SORT"))
        self.assertEqual(st.dds["SORTIN"].dsns, ["A.B", "C.D"])
        self.assertEqual([x[1] for x in st.dds["SYSIN"].instream], [8])
        self.assertEqual(st.dds["SORTOUT"].dsns, ["E.F"])
        self.assertEqual(j.card_lines, {("app/jcl/J.jcl", 1), ("app/jcl/J.jcl", 2)})

    def test_proc_symbolics_and_overrides(self):
        t = MemTree({
            "app/jcl/J.jcl": "//J JOB\n//S EXEC P,OUT=X.Y\n//R.IN DD DSN=OVR,DISP=SHR\n",
            "app/proc/P.prc": "//P PROC OUT=DEF\n//R EXEC PGM=Q\n//IN DD DSN=ORIG,DISP=SHR\n//OUT DD DSN=&OUT..Z,DISP=NEW\n// PEND\n",
        })
        st = jcl.JclReader(t).read_job("app/jcl/J.jcl").steps[0]
        self.assertEqual((st.id, st.pgm, st.proc_file), ("J.S.R", "Q", "app/proc/P.prc"))
        self.assertEqual(st.dds["IN"].dsns, ["OVR"])
        self.assertEqual(st.dds["OUT"].dsns, ["X.Y.Z"])
        self.assertIn(("app/jcl/J.jcl", 2), st.exec_lines)

    def test_dataset_names(self):
        self.assertEqual(jcl.dsn_name("A.B(+1)"), "A.B")
        self.assertEqual(jcl.dsn_name("'A.B(-2)'"), "A.B")
        self.assertEqual(jcl.dsn_name("LIB(MEM)"), "LIB(MEM)")
        self.assertIsNone(jcl.dsn_name("NULLFILE"))


if __name__ == "__main__":
    unittest.main()
