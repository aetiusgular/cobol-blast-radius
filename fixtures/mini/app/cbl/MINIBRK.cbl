       IDENTIFICATION DIVISION.
       PROGRAM-ID. MINIBRK.
      * Does not compile: WS-MISSING is never defined. No job runs it.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COUNT               PIC 9(5)   VALUE 0.
       PROCEDURE DIVISION.
           MOVE WS-MISSING TO WS-COUNT
           STOP RUN.
