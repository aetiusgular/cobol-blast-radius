       IDENTIFICATION DIVISION.
       PROGRAM-ID. COBDATFT.
      * Stand-in for CardDemo's assembler date formatter app/asm/COBDATFT.
      * The same bytes move as in the assembler source (record layout from
      * app/maclib/COCDATFT.mac):
      *   type 1 (YYYYMMDD in, output type 1): YYYY-MM-DD out
      *   type 2 (YYYY-MM-DD in, output type 2): YYYYMMDD out
      *   anything else: 'INVALID INPUT' in the error message.
      * Bytes of the output field that the assembler does not move are
      * left as they were.
       DATA DIVISION.
       LINKAGE SECTION.
       01  CO-REC.
           05  CO-INTYPE          PIC X.
           05  CO-INPDT           PIC X(20).
           05  CO-OUTTYPE         PIC X.
           05  CO-OUTDT           PIC X(20).
           05  CO-ERMSG           PIC X(38).
       PROCEDURE DIVISION USING CO-REC.
           EVALUATE TRUE
           WHEN CO-INTYPE = '1'
               IF CO-INPDT(5:1) = '-' OR CO-OUTTYPE = '2'
                   MOVE 'INVALID INPUT' TO CO-ERMSG
               ELSE
                   MOVE CO-INPDT(1:4) TO CO-OUTDT(1:4)
                   MOVE '-'           TO CO-OUTDT(5:1)
                   MOVE CO-INPDT(5:2) TO CO-OUTDT(6:2)
                   MOVE '-'           TO CO-OUTDT(8:1)
                   MOVE CO-INPDT(7:2) TO CO-OUTDT(9:2)
               END-IF
           WHEN CO-INTYPE = '2'
               IF CO-OUTTYPE = '1'
                   MOVE 'INVALID INPUT' TO CO-ERMSG
               ELSE
                   MOVE CO-INPDT(1:4)  TO CO-OUTDT(1:4)
                   MOVE CO-INPDT(6:2)  TO CO-OUTDT(5:2)
                   MOVE CO-INPDT(9:2)  TO CO-OUTDT(7:2)
               END-IF
           WHEN OTHER
               MOVE 'INVALID INPUT' TO CO-ERMSG
           END-EVALUATE
           MOVE 0 TO RETURN-CODE
           GOBACK.
