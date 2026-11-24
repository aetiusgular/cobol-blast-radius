"""F1, parsing sources into the graph (lane P3b)."""
from radius import graph
from tests.red._support import CARDDEMO, MINI, TempDirCase, need_carddemo


class GraphRed(TempDirCase):
    def test_copy_replacing_keeps_target(self):
        """COPY MINITAG REPLACING ... is still a COPY edge to MINITAG."""
        g = graph.build(MINI)
        self.assertIn(("program:MINIRPT", "COPY", "copybook:MINITAG"), g.edges)

    def test_nested_copybooks(self):
        """A COPY inside a copybook is an edge from that copybook, and the inner fields are declared."""
        g = graph.build(MINI)
        self.assertIn(("program:MINIRPT", "COPY", "copybook:MINIREC"), g.edges)
        self.assertIn(("copybook:MINIREC", "COPY", "copybook:MINIKEY"), g.edges)
        self.assertIn(("copybook:MINIKEY", "DECLARES", "field:MINIKEY.MR-KEY"), g.edges)
        self.assertIn(("copybook:MINICNST", "DECLARES", "field:MINICNST.MC-LABEL"), g.edges)

    def test_proc_expansion_and_symbolics(self):
        """EXEC MINIPROC,OUTDSN=MINI.OUTFILE expands the PROC and substitutes &OUTDSN; CardDemo's REPROC too."""
        g = graph.build(MINI)
        self.assertIn(("job:MINIJOB1", "RUNS", "step:MINIJOB1.STEP1.RUN"), g.edges)
        self.assertIn(("step:MINIJOB1.STEP1.RUN", "EXEC_PGM", "program:MINIRPT"), g.edges)
        self.assertIn(("dd:MINIJOB1.STEP1.RUN.OUTFILE", "DSN", "dataset:MINI.OUTFILE"), g.edges)
        self.assertNotIn("dataset:MINI.DEFAULT", g.nodes)
        need_carddemo(self)
        cd = graph.build(CARDDEMO)
        self.assertIn(("step:TRANREPT.STEP05R.PRC001", "EXEC_PGM", "program:IDCAMS"), cd.edges)
        self.assertIn(("step:TRANREPT.STEP05R.PRC001", "WRITES", "dataset:AWS.M2.CARDDEMO.TRANSACT.BKUP"), cd.edges)

    def test_gdg_relative_generations(self):
        """(+1) written in one job and (0) read in the next are the same base dataset."""
        g = graph.build(MINI)
        self.assertIn(("step:MINIJOB1.STEP1.RUN", "WRITES", "dataset:MINI.OUTFILE"), g.edges)
        self.assertIn(("step:MINIJOB2.STEP1", "READS", "dataset:MINI.OUTFILE"), g.edges)
        need_carddemo(self)
        cd = graph.build(CARDDEMO)
        self.assertIn(("step:INTCALC.STEP15", "WRITES", "dataset:AWS.M2.CARDDEMO.SYSTRAN"), cd.edges)
        self.assertIn(("step:COMBTRAN.STEP05R", "READS", "dataset:AWS.M2.CARDDEMO.SYSTRAN"), cd.edges)

    def test_programs_that_fail_to_compile_are_nodes(self):
        """MINIBRK and CardDemo's CBSTM03A do not compile, and COSGN00C is CICS; all are nodes."""
        g = graph.build(MINI)
        self.assertIn("program:MINIBRK", g.nodes)
        need_carddemo(self)
        cd = graph.build(CARDDEMO)
        for p in ("program:CBSTM03A", "program:CBEXPORT", "program:COSGN00C"):
            self.assertIn(p, cd.nodes)
