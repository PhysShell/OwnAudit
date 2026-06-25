# Fix arm — first slice

The audit-grade safety wrapper from [`../docs/fix-arm.md`](../docs/fix-arm.md) §4, end
to end on one rule. **We don't ship a fix engine** — `roslynator fix` / `dotnet format`
are the appliers. This is the glue that makes mass-apply honest:

```text
select(rule) → dry-run → diff → apply → re-audit → assert NO new findings → tier gate
```

## Run it (bare python3 — no .NET)

```bash
# fixarm lives under fix/, so put it on PYTHONPATH (or cd fix first)
PYTHONPATH=fix python3 fix/tests/test_orchestrate.py            # the contract tests
PYTHONPATH=fix python3 -m fixarm.cli --fixture fix/fixtures/idisp001-clean --rule IDISP001   # demo
```

The demo applies the IDISP001 fix to a recorded fixture, prints the coverage ledger,
and — because IDISP001 is **T2 (semantic)** — emits the reviewable patch instead of
auto-committing. The `idisp001-regress` fixture shows the crux: a fix that removes the
target but **introduces** a new finding is **rejected** (exit 2), never committed.

## Layout

| file | role |
|---|---|
| `fixarm/tiers.py` | rule → risk tier (T1 auto / T2 review / T3 unfixable / T4 bespoke) |
| `fixarm/orchestrate.py` | the wrapper: select, diff two audit runs, no-new-findings gate, ledger |
| `fixarm/appliers.py` | adapters — `Replay*` (CI fixtures) and real `Roslynator`/`DotnetFormat`/`ScriptReaudit` (.NET stand) |
| `fixarm/cli.py` | run a fixture through the wrapper |
| `fixtures/` | recorded before/after trees + before/after `findings.json` per rule |
| `tests/` | the safety-contract tests (bare python3 or pytest) |

## What's real vs. stand-bound

- **Real here (CI/Linux):** the whole wrapper — selection, the regression check, the
  tier gate, the ledger, the patch — tested on fixtures with `Replay*` adapters.
- **Stand-bound (Windows/.NET):** swap in `RoslynatorApplier(sln)` + `ScriptReaudit(
  Run-Audit.ps1, …)` for the real appliers and the real re-audit. Same `run_fix()` call.
  Gated on the **fix-spike** (`docs/fix-arm.md` §6): does `roslynator fix` even load
  `Broker.sln` through MSBuildWorkspace?

## Next

- Promote proven-mechanical rules into `tiers._T1_RULES` (auto-commit) from real diffs.
- Add the **T4 OWN001/OWN014 fixer** behind the same `Applier` interface — the one piece
  no off-the-shelf tool covers.
