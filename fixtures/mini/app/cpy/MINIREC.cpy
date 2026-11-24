      * Input record, 25 bytes. The key comes from a nested copybook.
       01  MINI-REC.
           COPY MINIKEY.
           05  MR-NAME            PIC X(10).
           05  MR-AMOUNT          PIC 9(5).
           05  MR-SPARE           PIC X(5).
