# Own.NET Audit — health report — `STS_new/SectorTS`

- commit: ``
- generated: ?
- profile: `?`
- tools run: codeql, infersharp, own-check, roslyn
- tiers: ?
- match: basename + line within ±8

**15803 findings** (3602 high-confidence, 12201 candidate). High-confidence = flagged by ≥2 independent tools at the same spot.

## Where it hurts most

Modules ranked by pain index (severity weighted by cross-tool agreement, summed). This is the triage order — top is worst, bottom is almost fine.

| module | pain | findings | high-conf | top category |
|---|---:|---:|---:|---|
| `BrokerDataClasses` | 6189.0 | 2295 | 665 | general-quality |
| `Broker` | 3313.0 | 1216 | 357 | general-quality |
| `BrokerDataClasses/Reports` | 2176.0 | 551 | 282 | general-quality |
| `BrokerDataClasses/Spr` | 1389.0 | 551 | 135 | general-quality |
| `Broker/GTD` | 1175.0 | 523 | 108 | general-quality |
| `BrokerDataClasses/Property` | 1033.0 | 377 | 151 | inpc-correctness |
| `BrokerDataClasses/Transit` | 811.0 | 283 | 75 | inpc-correctness |
| `BrokerDataClasses/StatementDT` | 770.0 | 221 | 89 | inpc-correctness |
| `BrokerPrint/RepoLibrary` | 739.0 | 282 | 81 | general-quality |
| `Tests/UnitTests` | 732.0 | 356 | 39 | general-quality |
| `Tests/UnitTests/Regressions` | 690.0 | 295 | 65 | general-quality |
| `Core` | 683.0 | 233 | 81 | general-quality |
| `Broker/SprDlg` | 654.0 | 293 | 63 | general-quality |
| `BrokerDataClasses/DTS2` | 622.0 | 284 | 21 | inpc-correctness |
| `BrokerDataClasses/KDTKTS` | 613.0 | 233 | 69 | general-quality |
| `Broker/Transit` | 612.0 | 241 | 49 | general-quality |
| `BrokerDataClasses/KTS` | 601.0 | 228 | 56 | inpc-correctness |
| `Tests/DocumentsTest/G47` | 556.0 | 282 | 28 | general-quality |
| `BrokerDataClasses/Service` | 498.0 | 198 | 36 | general-quality |
| `BrokerDataClasses/CashBlock` | 486.0 | 212 | 33 | inpc-correctness |
| `Broker/StatementDT` | 472.0 | 178 | 40 | general-quality |
| `CommonLib` | 454.0 | 181 | 32 | general-quality |
| `BrokerDataClasses/DTS` | 419.0 | 154 | 45 | general-quality |
| `ELFunctions` | 392.0 | 180 | 28 | general-quality |
| `Broker/DTS2` | 379.0 | 170 | 31 | general-quality |
| `BrokerDataClasses/KDT` | 370.0 | 167 | 14 | general-quality |
| `BrokerDataClasses/PaymentGuaranteeCalculation` | 359.0 | 132 | 39 | inpc-correctness |
| `FLK` | 340.0 | 119 | 53 | general-quality |
| `Broker/CommonControls` | 313.0 | 132 | 27 | general-quality |
| `Transit` | 312.0 | 114 | 31 | general-quality |
| `BrokerDataClasses/DocCloud/Clients` | 306.0 | 48 | 43 | idisposable-leak |
| `Broker/Statement` | 296.0 | 98 | 31 | general-quality |
| `Tests/UnitTests/CloudMapping` | 289.0 | 143 | 15 | general-quality |
| `Broker/obj/Debug` | 288.0 | 144 | 0 | general-quality |
| `Broker/KTS` | 269.0 | 100 | 24 | general-quality |
| `Tests/DocumentsTest/ElCopy` | 259.0 | 127 | 13 | general-quality |
| `Broker/DTS` | 258.0 | 109 | 19 | general-quality |
| `Broker/obj/Debug/GTD` | 256.0 | 128 | 0 | general-quality |
| `BrokerDataClasses/ExpresDT` | 216.0 | 73 | 31 | inpc-correctness |
| `BrokerDataClasses/MDP` | 213.0 | 76 | 28 | inpc-correctness |

## High-confidence findings — 3602 (≥2 tools agree)

- `BaseDict/DictionaryList.cs:625` **[P1 · idisposable-leak]** — codeql, roslyn
- `BaseDict/DictionaryList.cs:703` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/AmountWindow.xaml.cs:72` **[P1 · subscription-leak]** — codeql, own-check, roslyn
- `Broker/App.xaml.cs:13` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/Copy_toG44_fromDT_byG40_win.xaml.cs:96` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/Copy_toG44_fromDT_byG40_win.xaml.cs:112` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/DatabaseOptimizationWindow.xaml.cs:174` **[P1 · subscription-leak]** — own-check, roslyn
- `Broker/DesignEditorWindow.xaml.cs:225` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/ElErrorWindow.xaml.cs:58` **[P1 · idisposable-leak]** — codeql, own-check, roslyn
- `Broker/FLKWindow.xaml.cs:62` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/GTDDataShow.cs:31` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/GTDDataShow.cs:227` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/GTDDataShow.cs:389` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/GTDDataShow.cs:460` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/GTDDataShow.cs:825` **[P1 · idisposable-leak]** — codeql, infersharp, roslyn
- `Broker/GTDDataShowPersonalize.cs:214` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/GTDDataShowPersonalize.cs:345` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/MainWindow.xaml.cs:360` **[P1 · idisposable-leak]** — codeql, own-check, roslyn
- `Broker/MainWindow.xaml.cs:1089` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/MainWindow.xaml.cs:1528` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/MainWindow.xaml.cs:1949` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/MainWindow.xaml.cs:3949` **[P1 · subscription-leak]** — codeql, own-check, roslyn
- `Broker/MainWindow.xaml.cs:4061` **[P1 · subscription-leak]** — own-check, roslyn
- `Broker/MainWindow.xaml.cs:4087` **[P1 · subscription-leak]** — own-check, roslyn
- `Broker/MainWindow.xaml.cs:4220` **[P1 · subscription-leak]** — own-check, roslyn
- `Broker/MainWindow.xaml.cs:4246` **[P1 · subscription-leak]** — own-check, roslyn
- `Broker/MainWindow.xaml.cs:9622` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/MainWindow.xaml.cs:10592` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/MainWindow.xaml.cs:12990` **[P1 · subscription-leak]** — own-check, roslyn
- `Broker/MainWindow.xaml.cs:13162` **[P1 · subscription-leak]** — own-check, roslyn
- `Broker/MainWindow.xaml.cs:13222` **[P1 · idisposable-leak]** — codeql, infersharp, own-check, roslyn
- `Broker/MainWindow.xaml.cs:13902` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/MainWindow.xaml.cs:14719` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/MainWindow.xaml.cs:15304` **[P1 · idisposable-leak]** — own-check, roslyn
- `Broker/MainWindow.xaml.cs:15834` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/MainWindow.xaml.cs:15958` **[P1 · subscription-leak]** — own-check, roslyn
- `Broker/OpenDocumentWindow.xaml.cs:203` **[P1 · idisposable-leak]** — codeql, roslyn
- `Broker/OpenDocumentWindow.xaml.cs:484` **[P1 · idisposable-leak]** — codeql, infersharp, roslyn
- `Broker/OpenDocumentWindow.xaml.cs:518` **[P1 · idisposable-leak]** — codeql, infersharp, roslyn
- `Broker/OpenDocumentWindow.xaml.cs:537` **[P1 · idisposable-leak]** — codeql, infersharp, roslyn
- … (+3562 more)

## Candidates — 12201 (single tool: unique catch or possible FP)

- `Broker/CalcProcent_win.xaml.cs:279` **[P1 · idisposable-leak]** (roslyn)
- `Broker/Contacts.xaml.cs:23` **[P1 · idisposable-leak]** (roslyn)
- `Broker/DatabaseOptimizationWindow.xaml.cs:22` **[P1 · idisposable-leak]** (own-check)
- `Broker/Helper.cs:82` **[P1 · idisposable-leak]** (roslyn)
- `Broker/Helper.cs:92` **[P1 · idisposable-leak]** (roslyn)
- `Broker/Helper.cs:112` **[P1 · idisposable-leak]** (roslyn)
- `Broker/MainWindow.xaml.cs:11933` **[P1 · idisposable-leak]** (roslyn)
- `Broker/MainWindow.xaml.cs:11944` **[P1 · idisposable-leak]** (roslyn)
- `Broker/MainWindow.xaml.cs:11961` **[P1 · idisposable-leak]** (roslyn)
- `Broker/MainWindow.xaml.cs:11985` **[P1 · idisposable-leak]** (roslyn)
- `Broker/MainWindow.xaml.cs:11996` **[P1 · idisposable-leak]** (roslyn)
- `Broker/MainWindow.xaml.cs:12007` **[P1 · idisposable-leak]** (roslyn)
- `Broker/ProgressWithTimeRemaining.cs:13` **[P1 · idisposable-leak]** (roslyn)
- `Broker/PromotionWindow.xaml.cs:28` **[P1 · idisposable-leak]** (roslyn)
- `Broker/SelectGoodyFromDT_win.xaml.cs:33` **[P1 · subscription-leak]** (own-check)
- `Broker/ShareWindow.xaml.cs:175` **[P1 · idisposable-leak]** (roslyn)
- `Broker/sprUslPrice.xaml.cs:374` **[P1 · idisposable-leak]** (roslyn)
- `Broker/tnvedTreeActionsPopupWindowxaml.xaml.cs:192` **[P1 · idisposable-leak]** (roslyn)
- `Broker/ucProductInfo.xaml.cs:183` **[P1 · idisposable-leak]** (roslyn)
- `Broker/ucProductInfo.xaml.cs:282` **[P1 · idisposable-leak]** (roslyn)
- `Broker/DocCloud/CloudFLKWindow.xaml.cs:323` **[P1 · idisposable-leak]** (roslyn)
- `Broker/Excel/Services/ImportFromExcelCOMService.cs:71` **[P1 · idisposable-leak]** (roslyn)
- `Broker/Excel/Services/ImportFromExcelNewService.cs:55` **[P1 · idisposable-leak]** (roslyn)
- `Broker/GTD/R2/G44Components/WinAutoFill_r2.xaml.cs:16` **[P1 · subscription-leak]** (own-check)
- `Broker/KDT2/KDTMain.xaml.cs:520` **[P1 · subscription-leak]** (own-check)
- `Broker/RegistrationDT/Pages/Error.xaml.cs:42` **[P1 · idisposable-leak]** (roslyn)
- `Broker/Services/ShareService.cs:162` **[P1 · idisposable-leak]** (roslyn)
- `Broker/Services/ShareService.cs:306` **[P1 · idisposable-leak]** (roslyn)
- `Broker/Services/ShareService.cs:353` **[P1 · idisposable-leak]** (roslyn)
- `Broker/Services/ShareService.cs:378` **[P1 · idisposable-leak]** (roslyn)
- `Broker/Services/ShareService.cs:588` **[P1 · idisposable-leak]** (roslyn)
- `Broker/SprDlg/DlgServices.xaml.cs:258` **[P1 · idisposable-leak]** (roslyn)
- `Broker/SprDlg/dlgTnvedTree.xaml.cs:1671` **[P1 · idisposable-leak]** (roslyn)
- `Broker/SprDlg/dlgTnvedTree.xaml.cs:2060` **[P1 · idisposable-leak]** (roslyn)
- `Broker/SprDlg/dlgTnvedTree.xaml.cs:2211` **[P1 · idisposable-leak]** (roslyn)
- `Broker/SprDlg/dlgTnvedTree.xaml.cs:2258` **[P1 · idisposable-leak]** (roslyn)
- `Broker/Statement/StatementWindow.xaml.cs:1220` **[P1 · idisposable-leak]** (roslyn)
- `Broker/StatementDT/StatementDTWindow.xaml.cs:1193` **[P1 · idisposable-leak]** (roslyn)
- `Broker/StatementDT/StatementDTWindow.xaml.cs:1368` **[P1 · subscription-leak]** (own-check)
- `Broker/Transit/eG14_r2.xaml.cs:114` **[P1 · idisposable-leak]** (roslyn)
- … (+12161 more)

## Coverage / honesty

- findings ingested: 73407 (kept 72569, suppressed 605)
  - suppressed — third-party: DevExpress.: 605
- analysis-skipped (coverage notes, not scored): 233 — OWN050 x233
- unmapped rules (pending taxonomy, not dropped): `CS0067` x5, `CS0105` x1, `CS0108` x17, `CS0114` x1, `CS0162` x3, `CS0168` x31, `CS0169` x24, `CS0219` x48, `CS0252` x4, `CS0414` x10, `CS0618` x43, `CS0649` x16, `CS0659` x2, `CS1717` x1, `CS1998` x26, `CS4014` x1, `CS9236` x5, `MSTEST0003` x1, `MSTEST0006` x2, `MSTEST0012` x2, `MSTEST0016` x9, `MSTEST0017` x19, `MSTEST0030` x1, `MSTEST0032` x1, `MSTEST0034` x1, `MSTEST0037` x222, `MSTEST0039` x11, `MSTEST0045` x8, `MSTEST0046` x26, `MSTEST0049` x63, `NULLPTR_DEREFERENCE` x58, `THREAD_SAFETY_VIOLATION` x8
- by severity: P1=1018, P2=12672, P3=2113

## How to read this

- **Where it hurts most** is the triage order: fix top modules first.
- **High-confidence** = two independent tools flag the same spot — start here.
- **Candidates** are single-tool: either a unique own-check catch (the leak classes the oracles can't express) or a possible false positive to harden.
- **Coverage** is the honesty map: NO-TOOL categories are deferred to the runtime layer, not silently "clean"; suppressed DevExpress findings are counted, not hidden; unmapped rules are pending taxonomy, not lost.

