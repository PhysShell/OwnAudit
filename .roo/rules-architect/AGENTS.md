# Project Architecture Rules (Non-Obvious Only)

- The main flow is external/static tools → SARIF → external Own.NET normalize/report → local baseline/SARIF/runtime/fix tooling.
- Architecture analysis starts from `sts_audit/graph.json`, a Roslyn-extracted symbol graph from the stand; `arch.cli` itself is build-free and exits 0 after reporting findings.
- Baseline gating in `report.diff_cli` fails only on new findings at/above `--gate-level`; accepted legacy backlog is intentionally non-blocking.
- Runtime correlation separates confirmed, static-only, and runtime-only leaks; `runtime-findings.json` intentionally includes confirmed plus runtime-only blind spots.
- LeakFixMine stages compose through JSON and optional SQLite; BigQuery contents scans are deliberately capped/sampled because full scans are expensive.
- The .NET runtime arm is Windows-only by target framework; keep Linux CI expectations focused on Python contracts and recorded fixtures.
