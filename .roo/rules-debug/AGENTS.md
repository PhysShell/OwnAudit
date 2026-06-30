# Project Debug Rules (Non-Obvious Only)

- If `python3 -m pytest` fails, do not install pytest just to validate; tests intentionally run directly as scripts.
- Use `PYTHONUTF8=1` for audit/report commands; the Windows target has cp1251 console crashes with report glyphs.
- `Run-Audit.ps1` errors often point to the external Own.NET worktree (`audit/aggregate/normalize.py`) rather than this repo.
- Missing `infersharp.sarif` or `roslyn.sarif` is not an audit failure; `Run-Audit.ps1` folds them only when already present in `artifacts/`.
- Runtime correlation failures about `sts_audit/runtime.json` mean the Windows stand heap-dump collector has not produced the contract artifact yet.
- Roslyn analyzer explosions can come from flattening analyzer packs; `Run-Roslyn.ps1` intentionally caches each pack in its own subdirectory.
