# FP-judge — domain contract (Phase-0 input for the 007 `o7 judge`)

Owner: **OwnAudit (domain) agent.** Consumed by: **007** (produces `fp-verdicts.json`)
and OwnAudit reports (consume it). This file fixes the two things 007 asked the
domain for: **`finding_id` (linkage)** and the **required fields of
`fp-verdicts.json`**. The rubric (what a verdict *means*) is in `rubric.md`.

Seam: 007 owns the *mechanism* and the physical `fp-verdicts.json` file; the domain
owns *what a finding is* (identity) and *what fields a report needs*. Both sides
compute `finding_id` from the same recipe below.

---

## 1. `finding_id` — line-independent fingerprint

`findings.json` has **no id**, and `line` drifts between runs (own-check matches by
basename+line ±3; `oracle-fp-baseline.txt` deliberately keys on message, not line).
So identity must be line-independent.

```
finding_id = sha1( path + "\x1f" + rule + "\x1f" + message ).hexdigest()[:16]
```

- `path`, `rule`, `message` are the finding's fields verbatim (UTF-8). `\x1f` = unit
  separator (unambiguous join).
- **`line` is NOT part of identity** — it is drift. It travels as data (`lines` below)
  for locating, never for keying.
- The `message` is line-independent: it names the event/handler/type
  (`event 'X.PropertyChanged' … handler 'new H(M)' … keep 'T' alive`), no line numbers.

### Collisions are intentional (a pattern, not a line)
On the current audit, `(path,rule,message)` yields **198 unique ids for 210
findings**: 5 groups (17 findings) are the *same subscription pattern repeated* at
different lines in one file (identical `message`). Since the judge reads the
**whole file**, its input for every member of a group is identical → the verdict is
identical. So a `finding_id` may map to **≥1 physical findings**:

- **007** may dedupe by `finding_id` and judge each unique pattern **once** (fewer
  `claude -p` calls).
- **The report consumer** expands one verdict to **all** findings sharing the id
  (annotate every line).

No ordinal / tiebreaker — that would reintroduce line-order fragility for zero gain.

---

## 2. `fp-verdicts.json` — required fields

Separate **overlay** file (do NOT mutate `findings.json`). Envelope + per-id verdicts:

```jsonc
{
  "schema": 1,
  "tool": "own-check",
  "generated_from": "<sha256 of the findings.json this was judged against>",
  "model": "<claude model id>",          // 007 provenance; domain ignores
  "run_id": "<007 run id>",              // 007 provenance; domain ignores
  "verdicts": {
    "<finding_id>": {
      "class": "real | false_positive | uncertain",   // REQUIRED
      "confidence": 0.0,                               // REQUIRED, 0..1
      "reason": "one line, human-readable",            // REQUIRED
      "evidence": "optional: teardown site / why FP",  // optional but wanted
      "lines": [72, 130]                               // optional echo of covered lines
    }
  }
}
```

**Domain requires:** key = `finding_id`; per verdict `class` ∈ {real,
false_positive, uncertain}, `confidence` ∈ [0,1], `reason` (≤1 line). `evidence` is
optional but strongly wanted (it is what the human reviewer reads to trust/reject).

**`generated_from` is a hard requirement (report honesty):** the sha256 of the exact
`findings.json` judged. The report **refuses to merge** an overlay whose digest does
not match the current `findings.json` — a stale overlay (judged against an old audit)
must never be silently rendered as current truth. This is the same "don't report a
count that hides skipped work" discipline as the rest of the audit.

**Provenance (`model`, `run_id`)** is 007's to fill at the envelope level; the domain
does not depend on it but carries it through into the report footer.

---

## 3. What the domain does with it

`report.py` / the dashboard load `fp-verdicts.json`, verify `generated_from`, then
per finding: look up its `finding_id`, and render `class`/`confidence`/`reason`. A
`false_positive` (confidence ≥ threshold) is dropped from the triage count into a
"judged-FP" section (counted, not hidden — like suppressed DevExpress findings).
`uncertain` and `real` stay in triage; `real` sorts first. Threshold + exact
presentation = domain, tuned after the Phase-1 proof.
