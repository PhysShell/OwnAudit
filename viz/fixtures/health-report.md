# Acme (synthetic) — health report

> GOLDEN smoke fixture for `viz/build_dashboard.py`. Fully synthetic; not a real
> project. Mirrors the shape `build_dashboard.py` parses (the summary line below and
> the module pain table) so the dashboard renders in CI without the stand-only
> `sts_audit` corpus. Numbers are illustrative, not a real audit.

## Summary

**14 findings** (5 high-confidence, 9 candidate). High-confidence = flagged by ≥2 independent tools at the same spot.

## Module pain

| module | pain | findings | high-conf | top category |
|---|---:|---:|---:|---|
| `Acme.Portfolio` | 128.0 | 6 | 3 | subscription-leak |
| `Acme.Portfolio/Reports` | 74.0 | 3 | 1 | architecture |
| `Acme.Market` | 63.0 | 3 | 1 | general-quality |
| `Acme.UI` | 21.0 | 2 | 0 | wpf-freezable |
