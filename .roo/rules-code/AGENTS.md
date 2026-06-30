# Project Coding Rules (Non-Obvious Only)

- Do not duplicate the external `Own.NET/audit/` pipeline in this repo; local code should wrap, normalize, correlate, or test recorded artifacts.
- Fix-arm changes must preserve the safety wrapper contract in `fix/fixarm/orchestrate.py`: select → dry-run → apply → re-audit → reject any introduced finding → revert non-success paths.
- Use `fix/fixarm/tiers.py` as the single source of truth for T1/T2/T3/T4; `report/sarif.py` imports it for SARIF properties, so tier changes affect reporting.
- For OWN001/OWN014 fixes, prefer `fix/fixarm/own_fix.py`; refusals are intentional outputs (`applier.skipped`) rather than failed patches.
- Findings JSON shape is shared across arch/runtime/report/fix code: keep `tool`, `rule`, `category_name`, `resource`, `path`, `line`, `message`, and `suppressed` fields stable.
- C# files should keep CRLF line endings per `.editorconfig`; Python fixtures and JSON outputs use UTF-8 reads/writes explicitly.
