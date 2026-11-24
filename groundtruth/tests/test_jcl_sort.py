"""The JCL reader and the SORT control-statement parser, without a compiler."""
import tempfile
import unittest
from pathlib import Path

from groundtruth import jcl, utilities


class JCLTest(unittest.TestCase):
    def test_operands(self):
        ops = jcl.parse_operands("PGM=X,PARM='A,B''C',COND=((4,LT),(8,EQ,S1)),DISP=(,CATLG)")
        self.assertEqual(ops["PGM"], "X")
        self.assertEqual(ops["PARM"], "A,B'C")
        self.assertEqual(ops["COND"], [["4", "LT"], ["8", "EQ", "S1"]])
        self.assertEqual(ops["DISP"], ["", "CATLG"])
        self.assertEqual(jcl.parse_operands("DSN=A.B(+1),DCB=(*.SORTIN)")["DSN"], "A.B(+1)")

    def test_statements_continuation_comments_and_instream(self):
        text = "\n".join([
            "//J JOB 'X',CLASS=A,          comment here",
            "// NOTIFY=&SYSUID",
            "//* a comment",
            "//S1 EXEC PGM=SORT",
            "//SYSIN DD *",
            " SORT FIELDS=(1,2,CH,A)",
            "/*",
            "//OUT DD DSN=A.B,",
            "//         DISP=SHR                                                 00010000",
            "//",
            "//IGNORED DD DUMMY",
        ])
        st = jcl.statements(text)
        self.assertEqual([s[1] for s in st], ["JOB", "EXEC", "DD", "DD"])
        self.assertEqual(st[0][2], "'X',CLASS=A,NOTIFY=&SYSUID")
        self.assertEqual(st[2][3], [" SORT FIELDS=(1,2,CH,A)"])
        self.assertEqual(st[3][2], "DSN=A.B,DISP=SHR")

    def test_symbolics(self):
        self.assertEqual(jcl.substitute("DSN=&HLQ..DATA(&MEM),X=&&TEMP,Y=&UNKNOWN",
                                        {"HLQ": "A.B", "MEM": "M1"}),
                         "DSN=A.B.DATA(M1),X=&&TEMP,Y=&UNKNOWN")

    def test_proc_overrides_and_concatenation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "proc").mkdir()
            (root / "proc" / "P.prc").write_text("\n".join([
                "//P PROC OUT=D.DEFAULT",
                "//ST1 EXEC PGM=IEBGENER",
                "//SYSUT1 DD DSN=NULLFILE,DISP=SHR",
                "//SYSUT2 DD DSN=&OUT,DISP=(NEW,CATLG)",
                "// PEND", ""]))
            (root / "J.jcl").write_text("\n".join([
                "//J JOB",
                "//LIB JCLLIB ORDER=('MY.PROC')",
                "//A EXEC P,OUT=D.REAL",
                "//ST1.SYSUT1 DD DSN=D.IN1,DISP=SHR",
                "//          DD DSN=D.IN2,DISP=SHR",
                ""]))
            job = jcl.parse_job(root / "J.jcl", {"MY.PROC": {"dir": "proc", "ext": [".prc"]}}, root)
            self.assertEqual(len(job.steps), 1)
            s = job.steps[0]
            self.assertEqual((s.name, s.procstep, s.pgm), ("A", "ST1", "IEBGENER"))
            dds = {d.name: d for d in s.dds}
            self.assertEqual(dds["SYSUT1"].params["DSN"], "D.IN1")
            self.assertEqual([c.params["DSN"] for c in dds["SYSUT1"].concat], ["D.IN2"])
            self.assertEqual(dds["SYSUT2"].params["DSN"], "D.REAL")

    def test_missing_proc_is_unsupported(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "J.jcl"
            p.write_text("//J JOB\n//A EXEC NOPROC\n")
            job = jcl.parse_job(p, {}, tmp)
            self.assertTrue(job.steps[0].params["_unsupported"])


class SortParseTest(unittest.TestCase):
    SYMS = ["TRAN-CARD-NUM,263,16,ZD",
            "TRAN-PROC-DT,305,10,CH",
            "PARM-START-DATE,C'2022-01-01'                                      //Date",
            "PARM-END-DATE,C'2022-07-06'"]

    def test_symnames_and_include(self):
        syms = utilities.parse_symnames(self.SYMS)
        self.assertEqual(syms["TRAN-CARD-NUM"], ("field", (263, 16, "ZD")))
        self.assertEqual(syms["PARM-START-DATE"], ("const", "C'2022-01-01'"))
        stmts = utilities._sort_statements([
            " SORT FIELDS=(TRAN-CARD-NUM,A)",
            " INCLUDE COND=(TRAN-PROC-DT,GE,PARM-START-DATE,AND,",
            "         TRAN-PROC-DT,LE,PARM-END-DATE)"])
        self.assertEqual(stmts[1], "INCLUDE COND=(TRAN-PROC-DT,GE,PARM-START-DATE,AND,TRAN-PROC-DT,LE,PARM-END-DATE)")
        pred = utilities.parse_cond("TRAN-PROC-DT,GE,PARM-START-DATE,AND,TRAN-PROC-DT,LE,PARM-END-DATE", syms)
        rec = bytearray(b" " * 350)
        rec[304:314] = b"2022-06-10"
        self.assertTrue(pred(bytes(rec)))
        rec[304:314] = b"2022-07-18"
        self.assertFalse(pred(bytes(rec)))
        keys = utilities.parse_sort_fields("TRAN-CARD-NUM,A", syms)
        self.assertEqual(keys, [((263, 16, "ZD"), "A")])

    def test_zoned_decimal_signs(self):
        self.assertEqual(utilities._value(b"0012", 1, 4, "ZD"), 12)
        self.assertEqual(utilities._value(b"001r", 1, 4, "ZD"), -12)   # GnuCOBOL ASCII negative
        self.assertEqual(utilities._value(b"001K", 1, 4, "ZD"), -12)   # EBCDIC-style overpunch
        self.assertEqual(utilities._value(b"001B", 1, 4, "ZD"), 12)

    def test_or_binds_looser_than_and(self):
        pred = utilities.parse_cond("1,1,CH,EQ,C'A',OR,1,1,CH,EQ,C'B',AND,2,1,CH,EQ,C'X'", {})
        self.assertTrue(pred(b"AZ"))
        self.assertTrue(pred(b"BX"))
        self.assertFalse(pred(b"BZ"))

    def test_idcams_continuations_and_comments(self):
        cmds = utilities._idcams_commands([
            "  /* a comment */",
            "   DELETE A.B -",
            "          CLUSTER",
            "   IF MAXCC LE 08 THEN SET MAXCC = 0"])
        self.assertEqual(cmds, ["DELETE A.B CLUSTER", "IF MAXCC LE 08 THEN SET MAXCC = 0"])


if __name__ == "__main__":
    unittest.main()
