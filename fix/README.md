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
| `fixarm/own_fix.py` | **T4 OWN001/OWN014 fixer** — the one fixer no off-the-shelf tool covers (build-free, structural) |
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

## T4 — the OWN fixer (`fixarm/own_fix.py`)

The only fixer that is ours, because own-check's `OWN001`/`OWN014` rules are ours.
It plugs into the wrapper as an `Applier`, so it inherits dry-run, the no-new-findings
gate, and rollback. OWN is tier T4 → every result is **queued-for-review**, never auto.

```bash
PYTHONPATH=fix python3 -m fixarm.cli --fixture fix/fixtures/own001-sub-window \
    --rule OWN001 --applier own --show-diff
```

It fixes two shapes on a WPF owner by hanging cleanup on a teardown event
(`Window` → `Closed`, `FrameworkElement` → `Unloaded`):

```diff
  // named-handler subscription
  fGoods.PropertyChanged += new PropertyChangedEventHandler(GoodsPropertyChanged);
+ this.Closed += (s, e) => fGoods.PropertyChanged -= new PropertyChangedEventHandler(GoodsPropertyChanged);

  // disposable field (Timer / CancellationTokenSource / …), anchored after the ctor
  public ShareWindow() {
      InitializeComponent();
+     this.Closed += (s, e) => _timer?.Dispose();
```

It **refuses** the inline-lambda subscription (own-check: "no `-=` handle … could never
be detached" → needs extraction first) and the disposable-**local** (needs a scoped
`using`) — both are classified suggest-only and surfaced in `applier.skipped`, never
patched with a fake fix.

## Next

- Promote proven-mechanical rules into `tiers._T1_RULES` (auto-commit) from real diffs.
- OWN fixer: disposable-**local** → scoped `using`; inline-lambda **extraction** then
  detach; consolidate into an existing `OnClosed`/`Dispose` override when one is present.
- Windows-bound fix-spike: does `roslynator fix` load `Broker.sln` (docs/fix-arm.md §6).
