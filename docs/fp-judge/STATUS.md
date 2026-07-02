# FP-judge — status & resume note (OwnAudit domain side)

The FP-judge triages own-check's residual findings (real leak / false positive /
uncertain). Harness = 007's private `o7 judge` (`claude -p`, read-only, whole-file);
domain (this repo) owns the rubric, the finding identity, and consuming the overlay.
Contract to sync across the seam: **the overlay file + `verdict-contract.md`** — nothing else.

## Done

- **Phase 0 — contracts.** `verdict-contract.md` (`finding_id` = sha1(path\x1f rule\x1f
  message)[:16], line-independent; `fp-verdicts.json` fields; `generated_from` = sha256 of
  the raw findings.json bytes — staleness key) + `rubric.md` (subscription / idisposable /
  region-escape → real|false_positive|uncertain, with the rebind-setter case pinned to
  `uncertain`).
- **Phase 1 — proof (gate PASSED both directions).**
  - `real`: oracle's 2 intentional leaks (`WatchlistViewModel` subscription, `TickerViewModel`
    timer) → both `real`, grounded reasoning.
  - `false_positive`: `oracle/fixtures/findings-fp-control.json` (own-check-shaped findings
    aimed at the `Fixed*ViewModel` counterparts, which detach/dispose) → both `false_positive`.
    So the judge discriminates, not just rubber-stamps `real`.
- **Consumer** — `viz/apply_verdicts.py`: loads the overlay, **verifies `generated_from`
  vs the current findings.json (refuses stale)**, joins verdicts by `finding_id`, splits into
  real / uncertain / unjudged / judged-FP (confident FP retired, counted not hidden). Has a
  `--selftest` (guard: match→merge, mismatch→reject; + finding_id + classify + merge).
  `viz/build_dashboard.py` repointed `sts_audit/` → `artifacts/` so the dashboard reflects the
  de-noised audit.

## Next (Phase 2 — the real STS run)

1. 007 runs the judge over the real 156 (source must be **local** for whole-file context):
   ```
   o7 judge --repo C:\Repos\STS_new\SectorTS \
            --findings C:\Repos\OwnAudit\artifacts\findings.json \
            --rubric  C:\Repos\OwnAudit\docs\fp-judge\rubric.md \
            --out     C:\Repos\OwnAudit\artifacts\fp-verdicts.json
   ```
   (findings.json paths are `Broker/…` relative to `SectorTS`, so `--repo` = the SectorTS root.)
2. Domain merges + renders:
   ```
   python viz/apply_verdicts.py --out artifacts/findings-triaged.json   # guard now PASSES (digest = STS-210)
   python viz/build_dashboard.py
   ```
   Human-review the `real`/`uncertain` before trusting; `judged-FP` drops out of the triage count.

## Parallel / deferred (domain, independent of the judge)

- **thread 2** — canonical `Run-Audit.ps1` refresh: DONE (reproduces 210 from merged `main`).
- **thread 3** — own-check rebind soundness (flow-sensitive release). Decision: **defer** the
  real analysis; the rebind-setter class is surfaced as `uncertain` by the rubric, so it is
  best done as a distinct signal **after** the judge can triage it (else ~100+ uncertain findings
  flood the report with no triage path). Revisit post-Phase-2.
