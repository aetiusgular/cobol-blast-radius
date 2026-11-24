# fixtures/

Written in P2. Small, committed inputs the red tests and lanes run against. Public data only; record where each fixture came from and its licence. No customer data, no scraped marketplace data, no keys. Lanes do not edit this folder.

| Fixture | What | Source and licence |
|---|---|---|
| `mini/app/` | A two-job batch app laid out like CardDemo (`app/cbl`, `app/cpy`, `app/jcl`, `app/proc`, `app/data`). MINIJOB1 defines a GDG and runs MINIRPT through the PROC MINIPROC, whose output DSN is a symbolic parameter (`&OUTDSN(+1)`). MINIJOB2 sorts generation `(0)` and MINISUM sums it. MINIREC nests MINIKEY; MINIRPT COPYs MINITAG with REPLACING; MINICNST holds one field each program uses (MC-FACTOR in MINIRPT, MC-LABEL in MINISUM); MINIRPT has a paragraph nothing PERFORMs; MINIBRK does not compile. | Written for this repo in P2, Apache-2.0 like the repo. Checked in P2 with GnuCOBOL 3.2.0: MINIRPT and MINISUM compile and run (6 records in, total 420), MINIBRK fails with "'WS-MISSING' is not defined". |
| `mini/app/data/ASCII/mini.txt` | Six 25-byte records, one per line. | Written in P2. |
| `mini/app/data/EBCDIC/MINI.INPUT.PS` | The same six records as 150 bytes of fixed records, code page 037 (`str.encode("cp037")`). | Generated in P2 from `mini.txt`. |
| `mini/runset.json`, `mini/runset-ebcdic.json` | Run sets for the mini app (format in `contracts/runset.md`), the second reading the EBCDIC input. | Written in P2. |
| `mini/changes/*.json` | Hand-written changes (`contracts/change.md`): `noop-comment`, `field-label`, `field-factor`, `unperformed`, `compile-break`, `jcl-sort`. Each `before` matches the tree (`scripts/check-contracts.py`). In P2 the four COBOL ones other than `compile-break` pass a GnuCOBOL 3.2.0 syntax check and `compile-break` fails it, as its `compile_break: true` says. | Written in P2. |
| `carddemo/dateparm.txt` | The DATEPARM record CardDemo's CBTRN03C reads (start and end date, `PIC X(10)` each with one space between). CardDemo does not ship this dataset; the dates are the ones in TRANREPT.jcl's SYMNAMES (`2022-01-01`, `2022-07-06`). | Written in P2 from CardDemo's own JCL (Apache-2.0). |

CardDemo itself is not a fixture: `scripts/fetch-carddemo.sh` checks it out at the pinned commit into `vendor/carddemo`, which git ignores.
