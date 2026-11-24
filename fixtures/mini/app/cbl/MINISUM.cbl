       IDENTIFICATION DIVISION.
       PROGRAM-ID. MINISUM.
      * Sums the sorted MINIRPT output into one labelled record.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SORTED-FILE ASSIGN TO SORTED
                  ORGANIZATION IS SEQUENTIAL.
           SELECT SUM-FILE ASSIGN TO SUMFILE
                  ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  SORTED-FILE.
       01  SORTED-REC.
           05  SR-KEY             PIC X(5).
           05  SR-NAME            PIC X(10).
           05  SR-AMOUNT          PIC 9(6).
       FD  SUM-FILE.
       01  SUM-REC.
           05  SM-LABEL           PIC X(8).
           05  SM-TOTAL           PIC 9(8).
       WORKING-STORAGE SECTION.
       01  WS-CONSTANTS.
           COPY MINICNST.
       01  WS-TOTAL               PIC 9(8)   VALUE 0.
       01  WS-EOF                 PIC X      VALUE 'N'.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT SORTED-FILE
           OPEN OUTPUT SUM-FILE
           PERFORM UNTIL WS-EOF = 'Y'
               READ SORTED-FILE
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END ADD SR-AMOUNT TO WS-TOTAL
               END-READ
           END-PERFORM
           MOVE MC-LABEL TO SM-LABEL
           MOVE WS-TOTAL TO SM-TOTAL
           WRITE SUM-REC
           CLOSE SORTED-FILE
           CLOSE SUM-FILE
           DISPLAY 'MINISUM ' MC-LABEL ' ' WS-TOTAL
           STOP RUN.
