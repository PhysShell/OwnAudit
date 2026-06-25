# OwnAudit — Fix arm (Arm 3 · remediation)

The audit has three arms. **Arm 1 (static)** is done and validated over STS. **Arm 2
(runtime)** proves the top suspects actually retain — but it needs a Windows stand
(WPF · login · live DB), so it can't run in CI/Linux and is parked on that dependency.
**Arm 3 (this doc) — Fix** turns the static findings into reviewable remediations. It
is the productive line *right now*, because ~90% of the work is already shipped by
off-the-shelf tools and the rest is build-free glue that develops and tests on Linux.

The thesis in one line: **we do not build a fix engine. We wire ready-made mass
appliers, add an audit-grade safety wrapper, and build the one fixer nobody else can
(the OWN rules).**

---

## 1. Fixability triage (grounded in the real STS run)

From `sts_audit/findings.json` — **72 569 kept findings** (after DevExpress suppress).
Bucketed by the analyzer that produced them and whether that analyzer **ships a
CodeFixProvider**:

| source | findings | ships a code fix? |
|---|---:|---|
| Meziantou.Analyzer | 23 657 | mostly |
| PropertyChangedAnalyzers | 17 122 | yes |
| Roslynator | 15 301 | yes (batch CLI) |
| WpfAnalyzers | 3 902 | yes |
| IDisposableAnalyzers | 1 658 | partial |
| AsyncFixer | 94 | yes |
| **CodeQL** (`cs/…`) | 9 644 | **no — detect-only** |
| **Infer#** (`*_DEREFERENCE`, …) | 207 | **no — detect-only** |
| **own-check** (`OWN001`, `OWN014`) | 380 | **no — we build it** |
| MSTEST / C# compiler / other | ~600 | mixed |

**85 % (62 338) come from analyzers that already ship a code fix.** Top rules confirm
it — they are almost entirely fixer-backed: `INPC020` (5607), `MA0006` (5198), `MA0003`
(3991), `INPC003` (3472), `WPF0041` (3351), `MA0011` (3194), `INPC017`, `INPC013`,
`INPC002`, `RCS10xx`, `IDISP001/003`. The detect-only residue is CodeQL + Infer#
(~9 851); the genuinely unfixable-by-anyone-else slice is **own-check's 380**.

Implication: for the bulk, **applying** a fix is a solved problem. The engineering left
is *which* fixes are safe to apply unattended, *proving* a fix didn't make things worse,
and the OWN gap.

---

## 2. The landscape — what already exists (so we don't reinvent it)

### A. Mass appliers (mature — this is what we drive)
- **`dotnet format analyzers`** — built into the SDK; applies fixable analyzer
  diagnostics across a solution in one pass.
- **`roslynator fix <solution>`** — more capable; can load external analyzer assemblies
  (`--analyzer-assemblies`) and apply *their* fixes too, with diagnostic filtering.
- Both ride Roslyn's own **`WellKnownFixAllProviders.BatchFixer`** (FixAll). The
  "mass-apply engine" is already inside Roslyn — it is invoked, not written.

### B. Full refactoring platforms (recipe-based)
- **OpenRewrite** — the canonical org-wide mass-refactor engine. C# support exists
  (`rewrite-csharp`), but C# recipes run **only via the Moderne CLI/Platform**, which is
  free for OSS and **licensed for closed-source**. STS is proprietary → licensing blocks
  it. .NET recipe coverage is also younger than the JVM side. Noted, not adopted.
- **GitHub Copilot Autofix** — mass AI-generated fixes for code-scanning (CodeQL)
  alerts. Fixes are **AI-judged**, which violates this audit's "never AI-judged"
  discipline, and it is bound to GitHub code scanning. Out of scope as an applier.

### C. The gap — what no off-the-shelf tool does for us
A harness that ingests **our** multi-tool `findings.json` (own-check + codeql + roslyn +
infer), gates fixes by risk tier, dry-runs, emits reviewable diffs, **re-runs the static
audit to prove no new findings**, and fixes the **OWN** rules that are ours alone. This
is thin glue over (A) plus one bespoke fixer — not a fix engine.

---

## 3. Risk tiers — the gate that makes mass-apply honest

You cannot blind-apply 62k edits to a legacy app; that is the opposite of the audit's
"never faked clean" discipline. Every finding is routed to a tier, and the tier decides
**auto vs review**:

| tier | what | examples | policy |
|---|---|---|---|
| **T1** | mechanical / behavior-preserving | `RCS1xxx` style, readonly, ternary, formatting, `MA` style | batch-auto, single squashed diff |
| **T2** | semantic / structure-changing | `INPC*` correctness, `IDISP*`, `WPF*` freezable, `MA` correctness, `CA*` | apply per-rule, **diff on review**, re-run static |
| **T3** | detect-only, no fix exists | CodeQL `cs/*`, Infer# | not auto-fixable; only annotate, or pair with a T1/T2 analyzer firing at the same site |
| **T4** | bespoke (ours) | `OWN001` subscription/disposable, `OWN014` region-escape | **suggested patch, always reviewed** — teardown placement is not mechanical |

T1 is where unattended mass-apply is safe. T2 is mass-apply-then-review. T3 can't be
fixed (be honest about it — don't pretend coverage). T4 is the only thing we author.

---

## 4. The safety contract (what the wrapper guarantees)

The wrapper is the deliverable, not the fixers. For any fix run it must:

1. **Select** findings from `findings.json` by rule/tier (never "fix everything").
2. **Dry-run** the underlying applier; capture the proposed edits without writing.
3. **Diff** — emit a reviewable patch per rule (and per file for T4).
4. **Re-run the static audit** on the patched tree and assert **no new findings** were
   introduced (a fix that trades one finding for another is rejected). This reuses
   `Run-Audit.ps1` — the audit is its own regression oracle.
5. **Gate** by tier: T1 may auto-commit; T2/T4 stop for human review; T3 is reported as
   unfixable, not silently skipped.
6. **Build invariant** (on the Windows stand): the target still compiles after the fix.

No step is AI-judged. The asserts are exact, mirroring Arm 2's scenario discipline.

---

## 5. What we build vs. wire

- **Wire (already exists):** `roslynator fix` and `dotnet format analyzers` as the T1/T2
  appliers. Config + invocation, no engine.
- **Build — the wrapper** (`§4`): the tier-gated, dry-run, diff, re-audit orchestrator.
  Build-free, develops and unit-tests on Linux against synthetic fixtures (Roslyn and
  both CLIs are cross-platform).
- **Build — the OWN fixer** (T4): `OWN001`/`OWN014`. Structural, build-free, reviewable
  patches — built in [`../fix/fixarm/own_fix.py`](../fix/fixarm/own_fix.py). First slice
  fixes the **named-handler subscription** shape by inserting a teardown detach
  (`Window` → `Closed`, `FrameworkElement` → `Unloaded`); fixtures are real STS sites
  (`AmountWindow` OWN001, `KTSGoods2` OWN014). The **inline-lambda** shape is classified
  **suggest-only** and never patched — own-check itself flags it has "no `-=` handle, so
  it could never be detached", so it needs lambda extraction first. Still to build:
  disposable-field/local shapes, lambda extraction, and folding into an existing
  `OnClosed`/`Dispose`. Every OWN result is queued-for-review (T4), never auto.

---

## 6. The build wall (honest caveat)

`roslynator fix` and `dotnet format` load the solution through **MSBuildWorkspace** — so
they hit the same wall as the analyzer arm: net472 · non-SDK · packages.config · x86 ·
private feed (`Cat.*`/`Sector.*`). Because `roslyn.sarif` (62k findings) was already
produced via a VS2022 build, the odds are good — but "emits diagnostics" does not
guarantee "`roslynator fix --dry-run` loads `Broker.sln`".

→ **fix-spike** (mirrors `spike/Invoke-BuildSpike.ps1`): on the Windows stand, run
`roslynator fix --dry-run Broker.sln` and count loadable projects + visible fixes. Green
→ scale by tier. This spike is **Windows-bound**; everything in `§5` that targets
fixtures is **CI/Linux-native** and does not wait on it.

---

## 7. Where it lives & the hard wall

This arm lives in `OwnAudit/` (the lift-out home), consuming `audit/`'s SARIF →
`findings.json`. It **names** the Own.NET checkout and reads its findings; it never
references core source — the same hard wall as `config/ownaudit.json`. The OWN fixer
consumes own-check's SARIF messages, not OwnSharp internals, so the wall holds.

Canonically the remediation logic would land in `Own.NET/audit/fix/` and lift out here,
mirroring how `audit/aggregate` + `audit/runtime` are canonical there today. Out of
scope this session (only `physshell/ownaudit` is reachable); built here for now.

---

## 8. Testing

- **Fixtures + golden** — one minimal `.cs` per rule reproducing the pattern; assert the
  applier/OWN-fixer produces the exact golden output. Standard `Microsoft.CodeAnalysis`
  testing, runs on Linux.
- **No-regression invariant** (`§4.4`) — re-running the audit on the patched fixture set
  yields **no new findings**. This is the same exact-assert, never-AI-judged contract the
  whole pipeline runs on.
- **Tier coverage ledger** — like OWN050: report what was auto-fixed, what was queued for
  review, and what is unfixable (T3). Never report a fixed count that hides skipped work.

---

## 9. First slice (CI/Linux-native, no STS) — DONE

Built in [`../fix/`](../fix/). The wrapper end-to-end on **one** rule (IDISP001): select
→ dry-run → diff → apply → re-audit assert-no-new-findings → tier gate, with golden
fixtures and bare-`python3` tests (`fix/tests/test_orchestrate.py`, 6/6). Proves the
safety contract on synthetic input — including the crux test: a fix that removes the
target but introduces a new finding is **rejected**, never committed.

The applier is pluggable (`fix/fixarm/appliers.py`): `Replay*` adapters drive recorded
fixtures here; `RoslynatorApplier` / `DotnetFormatApplier` / `ScriptReaudit` drive the
real tools on the Windows stand via the same `run_fix()` call. Still to do: the OWN T4
fixer on the same rig, promoting proven-mechanical rules to T1, and the Windows-bound
fix-spike (`§6`).
