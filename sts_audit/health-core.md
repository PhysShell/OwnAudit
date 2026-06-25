# Own.NET Audit — health report — `Core`

- commit: ``
- generated: ?
- profile: `?`
- tools run: codeql, own-check
- tiers: ?
- match: basename + line within ±3

**154 findings** (3 high-confidence, 151 candidate). High-confidence = flagged by ≥2 independent tools at the same spot.

## Where it hurts most

Modules ranked by pain index (severity weighted by cross-tool agreement, summed). This is the triage order — top is worst, bottom is almost fine.

| module | pain | findings | high-conf | top category |
|---|---:|---:|---:|---|
| `(root)` | 320.0 | 147 | 0 | general-quality |
| `Core` | 24.0 | 3 | 3 | idisposable-leak |
| `Ambient` | 4.0 | 2 | 0 | general-quality |
| `Extentions` | 2.0 | 1 | 0 | general-quality |
| `Properties` | 2.0 | 1 | 0 | general-quality |

## High-confidence findings — 3 (≥2 tools agree)

- `Core/CRC32.cs:117` **[P1 · idisposable-leak]** — codeql, own-check
- `Core/MSSQLUtils.cs:1044` **[P1 · idisposable-leak]** — codeql, own-check
- `Core/Mail.cs:32` **[P1 · idisposable-leak]** — codeql, own-check

## Candidates — 151 (single tool: unique catch or possible FP)

- `FileUtils.cs:190` **[P1 · idisposable-leak]** (codeql)
- `FileUtils.cs:205` **[P1 · idisposable-leak]** (codeql)
- `MSSQLUtils.cs:231` **[P1 · idisposable-leak]** (codeql)
- `MSSQLUtils.cs:411` **[P1 · idisposable-leak]** (codeql)
- `MSSQLUtils.cs:432` **[P1 · idisposable-leak]** (codeql)
- `MSSQLUtils.cs:553` **[P1 · idisposable-leak]** (codeql)
- `MSSQLUtils.cs:610` **[P1 · idisposable-leak]** (codeql)
- `MSSQLUtils.cs:682` **[P1 · idisposable-leak]** (codeql)
- `MSSQLUtils.cs:912` **[P1 · idisposable-leak]** (codeql)
- `MSSQLUtils.cs:1227` **[P1 · idisposable-leak]** (codeql)
- `MSSQLUtils.cs:1242` **[P1 · idisposable-leak]** (codeql)
- `MSSQLUtils.cs:1268` **[P1 · idisposable-leak]** (codeql)
- `Mail.cs:39` **[P1 · idisposable-leak]** (codeql)
- `BaseConverter.cs:59` **[P2 · general-quality]** (codeql)
- `BaseConverter.cs:100` **[P2 · general-quality]** (codeql)
- `BaseConverter.cs:139` **[P2 · general-quality]** (codeql)
- `BaseConverter.cs:154` **[P2 · general-quality]** (codeql)
- `BaseConverter.cs:178` **[P2 · general-quality]** (codeql)
- `BaseConverter.cs:193` **[P2 · general-quality]** (codeql)
- `BaseConverter.cs:210` **[P2 · general-quality]** (codeql)
- `BaseConverter.cs:229` **[P2 · general-quality]** (codeql)
- `BaseConverter.cs:244` **[P2 · general-quality]** (codeql)
- `BaseConverter.cs:259` **[P2 · general-quality]** (codeql)
- `BaseGlobalProperty.cs:22` **[P2 · general-quality]** (codeql)
- `BaseObject.cs:30` **[P2 · general-quality]** (codeql)
- `BaseObject.cs:211` **[P2 · general-quality]** (codeql)
- `BaseObject.cs:444` **[P2 · general-quality]** (codeql)
- `BaseObject.cs:615` **[P2 · general-quality]** (codeql)
- `BaseObject.cs:772` **[P2 · general-quality]** (codeql)
- `CRC32.cs:124` **[P2 · general-quality]** (codeql)
- `Currency.cs:13` **[P2 · general-quality]** (codeql)
- `Currency.cs:19` **[P2 · general-quality]** (codeql)
- `Excel.cs:40` **[P2 · general-quality]** (codeql)
- `Excel.cs:57` **[P2 · general-quality]** (codeql)
- `Excel.cs:79` **[P2 · general-quality]** (codeql)
- `Excel.cs:215` **[P2 · general-quality]** (codeql)
- `Excel.cs:221` **[P2 · general-quality]** (codeql)
- `Excel.cs:238` **[P2 · general-quality]** (codeql)
- `Excel.cs:249` **[P2 · general-quality]** (codeql)
- `FileLogger.cs:37` **[P2 · general-quality]** (codeql)
- … (+111 more)

## Coverage / honesty

- findings ingested: 216 (kept 216, suppressed 0)
- unmapped rules: none — every flagged rule is categorized
- by severity: P1=16, P2=138

## How to read this

- **Where it hurts most** is the triage order: fix top modules first.
- **High-confidence** = two independent tools flag the same spot — start here.
- **Candidates** are single-tool: either a unique own-check catch (the leak classes the oracles can't express) or a possible false positive to harden.
- **Coverage** is the honesty map: NO-TOOL categories are deferred to the runtime layer, not silently "clean"; suppressed DevExpress findings are counted, not hidden; unmapped rules are pending taxonomy, not lost.

