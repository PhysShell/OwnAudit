# AGENTS.md

This file provides guidance to agents when working with code in this repository.

- OwnAudit is mostly a lift-out/orchestration repo: the canonical audit engine remains in external `Own.NET/audit/`; do not reimplement aggregation/reporting/runtime harness logic here.
- `src/OwnAudit.Cli` and `src/OwnAudit.Runtime` intentionally target `net8.0-windows` because runtime work depends on FlaUI/ClrMD; Linux work here is mainly the Python tooling/tests.
- Python tests are designed to run as bare scripts because `pytest` is not guaranteed in the dev shell: `PYTHONUTF8=1 python3 arch/tests/test_arch.py` or any `*/tests/test_*.py` file directly.
- Full Linux-safe regression sweep: `PYTHONUTF8=1 python3 arch/tests/test_arch.py && PYTHONUTF8=1 python3 fix/tests/test_orchestrate.py && PYTHONUTF8=1 python3 fix/tests/test_own_fix.py && PYTHONUTF8=1 python3 fix/tests/test_ai_fix.py && PYTHONUTF8=1 python3 leakmine/tests/test_leakmine.py && PYTHONUTF8=1 python3 report/tests/test_baseline.py && PYTHONUTF8=1 python3 report/tests/test_sarif.py && PYTHONUTF8=1 python3 runtime/tests/test_runtime.py && PYTHONUTF8=1 python3 oracle/fixtures/test_oracle_arch.py && PYTHONUTF8=1 python3 oracle/fixtures/test_oracle_runtime.py`.
- `Run-Audit.ps1` is Windows-stand oriented and drives external Own.NET worktrees; it sets `PYTHONUTF8=1`, emits SARIF into `artifacts/`, and clusters optional Infer#/Roslyn results only if their SARIF files already exist.
- Use `Run-Audit.ps1 -Codeql` for CodeQL corroboration; use `-LineTol 8` when folding Infer# or Roslyn because those tools report shifted/generated locations.
- `Run-Infersharp.ps1` consumes built STS `.dll` + `.pdb` files via WSL and filters third-party/generated SARIF before `Run-Audit.ps1` folds it.
- `Run-Roslyn.ps1` requires VS2022 BuildTools and injects analyzers with `/p:OwnAudit=true`; analyzer packs must stay in per-pack cache subdirs to avoid `Gu.Roslyn.Extensions` conflicts.
- Generated/derived outputs live under `artifacts/`, `arch/out/`, `report/out/`, `runtime/out/`, and `leakmine-out/`; avoid treating them as source truth unless a test fixture explicitly depends on them.
- `.editorconfig` has a project-specific C# gotcha: `*.cs` files use CRLF while JSON/YAML/Markdown/PowerShell use 2-space indentation.
