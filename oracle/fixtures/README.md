# Oracle arch fixtures — the `graph.json` contract + a golden arch run

These fixtures let the architecture pass (`arch/`) be exercised on **real, oracle-shaped data**
right now — before the слой-2 Roslyn extractor exists — and pin the exact `graph.json` that
extractor must emit for [`oracle/LeakyOracle`](../LeakyOracle). They are the in-scope half of слой 2:
the Python side that *consumes* the graph, validated against a faithful hand-authored graph of the
real app.

## Files

- **`graph.json`** — the arch-graph of LeakyOracle: 8 internal types + the framework types they touch
  (`ownAudit/arch-graph/v1`, schema in [`docs/arch-graph.md`](../../docs/arch-graph.md)). **The
  *internal* type graph is the contract** the слой-2 extractor must reproduce. External nodes list the
  *meaningful* framework types those types reference; **pure-infrastructure BCL leaves
  (`System.Int32`, `System.Console`, `System.GC`, attributes, arrays) are elided** as
  analysis-irrelevant (external, never flaggable, never in a cycle, no effect on any rule), so a
  faithful extractor emits a **superset** of external edges — hand-authoring can't be byte-exact on BCL
  leaves and doesn't need to be. `System.String` *is* kept, because string duplication is one of the
  oracle's own smells. `test_oracle_arch.py` guards the contract against drift by checking every
  internal node points at a file that still exists under `oracle/` — it does not assert external
  completeness.
- **`rules.json`** — an **MVVM** layering profile for the oracle (the default `arch/rules.json` is
  STS-specific: `Sts.*` / SQL / WPF). Allowed direction: `Views → ViewModels → Services`; the reverse
  is forbidden. Demonstrates the rules engine is configurable per codebase, not STS-hardcoded.
- **`test_oracle_arch.py`** — runs the pass both directions (below). Wired into CI (normal + `-O`).

## What it proves

**Clean (faithful graph) → 0 findings.** The oracle is well-layered MVVM, so `arch/` correctly
reports nothing. Its real smells are *lifetime/heap* — the subscription leak (OWN001), duplicated
strings, killed virtualization (XAML107) — which are not architecture findings. This guards against
`arch/` crying wolf on clean code.

**Degraded (one planted edge) → 3 findings.** Adding a single MVVM inversion — a view-model reaching
back to a view (`WatchlistViewModel → MainWindow`) — lights up three distinct rule classes at once:

| rule | what it caught |
|---|---|
| `ARCH-MVVM-VM-VIEW` | the forbidden direction: `WatchlistViewModel → MainWindow` |
| `ARCH-CYCLE-TYPE` | the type cycle it creates: {`MainWindow`, `WatchlistViewModel`} |
| `ARCH-CYCLE-NS` | the namespace cycle: {`LeakyOracle.ViewModels`, `LeakyOracle.Views`} |

The test keeps the degraded graph in-memory (clean graph + one documented edge) so there's a single
source of truth and the regression can't silently drift from the contract.

## Runtime correlation (phase 5)

The same idea for the runtime side: pin the `runtime.json` contract the слой-2 ClrMD/gcdump collector
must emit for the oracle, and exercise `runtime/correlate.py` on it now.

- **`findings.json`** — the static leak SUSPECTS own-check would emit for the oracle's two intentional
  lifetime leaks (OWN001 subscription on `WatchlistViewModel`, OWN-TIMER on `TickerViewModel`).
  `resource` is a *description*, so correlation keys on the source-file stem (the owning class).
- **`runtime.json`** — the heap evidence, faithful to the headless leak proof: 50 of each leaky
  view-model survive GC (`expected` 0), plus the 250 000 `QuoteRow` they transitively retain.
- **`test_oracle_runtime.py`** — runs `correlate.py` and asserts the three-way split:

| bucket | result |
|---|---|
| **confirmed** | `WatchlistViewModel` ×50 + `TickerViewModel` ×50 — both **high**, each naming the leaked CLR type and the static rule it corroborates |
| **static-only** | _(none)_ — both suspects were retained |
| **runtime-only** | `QuoteRow` ×250 000 — a static blind spot (the rows are retained *through* the leaked VMs; the static pass flags the VM, not the pile) |

The `high` gate fails on the two confirmed leaks — the highest-signal finding the auditor produces.
A drift guard ties every retained type to a real `oracle/LeakyOracle/ViewModels/*.cs`.

## Run

```bash
PYTHONPATH=. python3 oracle/fixtures/test_oracle_arch.py
PYTHONPATH=. python3 oracle/fixtures/test_oracle_runtime.py
# or the passes directly:
PYTHONPATH=. python3 -m arch.cli --graph oracle/fixtures/graph.json --rules oracle/fixtures/rules.json
#   → architecture pass: 0 findings (clean)
PYTHONPATH=. python3 -m runtime.cli --findings oracle/fixtures/findings.json --runtime oracle/fixtures/runtime.json
#   → 2 high confirmed · 0 static-only · 1 runtime-only
```

When слой 2 lands in Own.NET, its extractor run over LeakyOracle should reproduce the **internal**
subgraph of `graph.json` (up to ids/loc; it may surface more framework-leaf edges), and this same
`arch/` pass will then run on *extracted* data instead of hand-authored — the contract makes that swap
mechanical.
