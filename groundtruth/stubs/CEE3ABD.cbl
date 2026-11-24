       IDENTIFICATION DIVISION.
       PROGRAM-ID. CEE3ABD.
      * Stand-in for the Language Environment abend service. It ends the
      * run unit the way an abend ends a step: the harness sees the marker
      * on stderr and records the step as an abend.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-ABCODE              PIC S9(9) BINARY.
       01  LK-TIMING              PIC S9(9) BINARY.
       PROCEDURE DIVISION USING LK-ABCODE LK-TIMING.
           DISPLAY 'GT-ABEND CEE3ABD U' LK-ABCODE UPON SYSERR
           MOVE 16 TO RETURN-CODE
           STOP RUN.
