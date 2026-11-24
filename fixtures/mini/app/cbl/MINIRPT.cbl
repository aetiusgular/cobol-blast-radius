       IDENTIFICATION DIVISION.
       PROGRAM-ID. MINIRPT.
      * Reads MINI-REC records, writes each with its amount scaled.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INFILE
                  ORGANIZATION IS SEQUENTIAL.
           SELECT OUT-FILE ASSIGN TO OUTFILE
                  ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
           COPY MINIREC.
       FD  OUT-FILE.
       01  OUT-REC.
           05  OR-KEY             PIC X(5).
           05  OR-NAME            PIC X(10).
           05  OR-AMOUNT          PIC 9(6).
       WORKING-STORAGE SECTION.
       01  WS-CONSTANTS.
           COPY MINICNST.
           COPY MINITAG REPLACING ==:TAG:== BY ==WS-IN==.
       01  WS-EOF                 PIC X      VALUE 'N'.
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT IN-FILE
           OPEN OUTPUT OUT-FILE
           PERFORM 1000-READ
           PERFORM 2000-PROCESS UNTIL WS-EOF = 'Y'
           CLOSE IN-FILE
           CLOSE OUT-FILE
           DISPLAY 'MINIRPT RECORDS ' WS-IN-COUNT
           STOP RUN.
       1000-READ.
           READ IN-FILE
               AT END MOVE 'Y' TO WS-EOF
           END-READ.
       2000-PROCESS.
           ADD 1 TO WS-IN-COUNT
           MOVE MR-KEY TO OR-KEY
           MOVE MR-NAME TO OR-NAME
           COMPUTE OR-AMOUNT = MR-AMOUNT * MC-FACTOR
           WRITE OUT-REC
           PERFORM 1000-READ.
      * Nothing PERFORMs, GO TOs or falls into this paragraph.
       9000-UNUSED.
           MOVE 'UNUSED' TO OR-NAME
           DISPLAY 'NEVER REACHED'.
