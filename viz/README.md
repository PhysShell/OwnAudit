# viz — STS audit dashboard

An interactive, self-contained HTML dashboard built from the validated STS audit
artifacts in [`../sts_audit/`](../sts_audit). No server, no build step, works offline.

```bash
# one-time: vendor Plotly for an offline, single-file dashboard (else it falls back to CDN)
curl -fsSL https://cdn.plot.ly/plotly-2.35.2.min.js -o viz/plotly.min.js
python3 viz/build_dashboard.py          # -> viz/sts-dashboard.html  (open in any browser)
```

It reads `sts_audit/findings.json` (the 72,569 raw findings) and the module pain table
from `sts_audit/health-report.md`, and renders:

- **Where it hurts most** — a treemap of modules sized by pain index, coloured by
  high-confidence share (hover, click to zoom);
- findings **by category**, **by tool**, and the **top rules**;
- **by analyzer source**, coloured by whether it ships a CodeFixProvider (the 85%
  "wire, don't build" story behind the fix arm);
- **OWN fixer — shape coverage**: the leak shapes only own-check flags, and how the
  bespoke T4 fixer remediates each.

## Notes

- `build_dashboard.py` inlines `viz/plotly.min.js` when present (fully self-contained,
  ~4.5 MB), otherwise emits a `<script src=…cdn…>` tag (tiny file, needs internet).
- The generated `sts-dashboard.html`, `preview.png`, and the vendored `plotly.min.js`
  are git-ignored — they're large and reproducible from the command above.
- Verified headless (Playwright/Chromium): 6 charts render, zero console errors.
