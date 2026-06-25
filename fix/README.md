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

It fixes **four** shapes (conservatively — refuses rather than emit a wrong patch):

```diff
  // 1. named-handler subscription -> detach on the owner's teardown event
  fGoods.PropertyChanged += new PropertyChangedEventHandler(GoodsPropertyChanged);
+ this.Closed += (s, e) => fGoods.PropertyChanged -= new PropertyChangedEventHandler(GoodsPropertyChanged);

  // 2. disposable field (Timer / CTS / …) -> dispose on teardown, after the ctor
  public ShareWindow() {
      InitializeComponent();
+     this.Closed += (s, e) => _timer?.Dispose();

  // 3. disposable local -> block `using` (only when it doesn't escape the block)
- var myProcess = new Process();
+ using (var myProcess = new Process())
+ {
      myProcess.Start();
+ }

  // 4. inline-lambda subscription -> extract to a named handler, then detach
- stage.PropertyChanged += (s2, e2) => OnPropertyChanged("Stages");
+ stage.PropertyChanged += OnStagePropertyChanged;
+ this.Closed += (s, e) => stage.PropertyChanged -= OnStagePropertyChanged;
+ private void OnStagePropertyChanged(object s2, PropertyChangedEventArgs e2) => OnPropertyChanged("Stages");
```

**Refusals stay honest** (surfaced in `applier.skipped`, never a fake patch): a local
that escapes its block (return/out/ref/store) → `local-escapes`; a block-body or
unknown-delegate lambda → `lambda-shape-unsupported` / `unknown-event-delegate`; an
unbraced guard → `unbraced-control-flow`; no safe teardown → `no-safe-teardown`.

## Next

- Promote proven-mechanical rules into `tiers._T1_RULES` (auto-commit) from real diffs.
- OWN fixer: fold into an existing `OnClosed`/`Dispose` override when one is present;
  widen lambda extraction to more event delegates.
- Windows-bound fix-spike: does `roslynator fix` load `Broker.sln` (docs/fix-arm.md §6).
