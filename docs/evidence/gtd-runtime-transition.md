# Evidence: the GTD blind spot's runtime-only → confirmed transition

Member-aware static-event correlation (this repo) × Own.NET #278 release-path
soundness, proven on real STS heap evidence. One heap artifact, three analyzer
snapshots — the analyzer version is the only variable. Run: 2026-07-19.

## Why type-level correlation could not prove this

The pre-fix `runtime/correlate.py` matched findings to retention by CLR type / file
stem alone. `GTD.cs` carries many unrelated `OWN001` event findings, so the GTD
retention (pinned by the static `GBProperty.PropertyChanged` delegate) was attributed
to whichever of them matched first — while the actual leak site, `GTD.cs:5192`, was
not flagged at all (its `-=` hides behind a flagged parameter / uncalled method; see
the broker research `runner/LEAK.md`). A repeat run saying "GTD confirmed again"
would have re-used the attribution error, not proven the fix.

The member-aware contract (this branch): a subscription-leak finding confirms only
when its canonical event identity — `event 'AppData.Properties.GBProperty.PropertyChanged'`
→ key `(GBProperty, PropertyChanged)` — equals a static-event root's
`(short(holder), member)`. Identity is never guessed; non-event categories and
retentions without root identity keep the type-level fallback.

## Producers and consumers

| Role | SHA |
|---|---|
| OwnAudit branch base (main, merge #52) | `d43f575617e6589a518cbe20b88fef636e265813` |
| Own.NET pre-#278 | `366bbf93a6c07d9055a3070050d2dfe202a4ea83` |
| Own.NET exact #278 merged (PR #293) | `a7d8499362b91512d3f86c041f02d5263891717d` |
| Own.NET current main (merge #302) | `2c30c5690a010c2b3257e0f337edb45f91137abb` |
| STS shipping build under test | `d753747b` (develop), built into `STS_shipping\Setup` |
| STS source tree scanned | `C:\Repos\STS_new` @ `dsector_optimization` |

Note on line numbers: the static scans ran over the working tree
(`dsector_optimization`), where the KDT subscription sits at `KDT.cs:60/61`
(historically `:87/88` on the shipping branch — same sites, branch line drift).
`GTD.cs:5192` is the same on both.

## Commands

```powershell
# heap artifact — SerializerSim (shipping Setup) held after the leaky pass:
$env:SERIALIZERSIM_SETUP = "<STS_shipping>\Setup"
.\bin\SerializerSimDbg.exe leaktest --limit 60 --tables GTD,KDT --hold
own-audit collect --pid <pid> --findings sts_audit/findings.json --max-chains 40 `
    --iterations 94 --out artifacts/runtime-sts-accept.json
```

```bash
# three static snapshots (WSL/nix; own-check needs python3 + dotnet):
for tag in pre278 exact278 curmain; do
  bash <ownnet-$tag>/scripts/own-check.sh --root <ownnet-$tag> \
      --format sarif --severity warning SectorTS > own-$tag.sarif
  python3 <ownnet-curmain>/audit/aggregate/normalize.py \
      --sarif own-check=own-$tag.sarif --strip SectorTS --json findings-$tag.json
  python3 -m runtime.cli --findings findings-$tag.json \
      --runtime artifacts/runtime-sts-accept.json --out-dir rt-$tag
done
```

## Full local artifacts (gitignored; SHA-256, bytes)

| File | SHA-256 | Size |
|---|---|---:|
| `artifacts/runtime-sts-accept.json` | `aebb0646dad4e82d3373b1df8177e1718dd1ba83d082b41a97badcf9072b5309` | 944 546 |
| `artifacts/own-pre278.sarif` | `7a2fbac6bb5562185d730ce9ba5c11474d349aa85dec1bec8f9783f6b48d7a57` | 415 602 |
| `artifacts/own-exact278.sarif` | `b28c80bf9ad1af2816317c630a2e9d580f06c9bc69747cfeb7db116d4496d7cb` | 661 912 |
| `artifacts/own-curmain.sarif` | `744d65d91d0fcf8b3e73fab4c600516dd630b63af5ac72528768d8196dcae56b` | 666 532 |
| `artifacts/findings-pre278.json` | `f690fc4527f3509eb54b0aec5e46550e9ba5ef709ff4b75b67331f53de83728d` | 123 622 |
| `artifacts/findings-exact278.json` | `64e8e06a97961d9e66694cd258ac724e37eefab2f1d93230e065c978e1953371` | 272 176 |
| `artifacts/findings-curmain.json` | `deba01dc15ab056da345f8064ad0853e7483b29f2f7ea4f618787bc5b390dd3e` | 274 695 |

## Static excerpts

pre-#278 (`findings-pre278.json`): **zero** mentions of `GBProperty.PropertyChanged`
anywhere (203 other OWN001 findings, several inside `GTD.cs`).

exact #278 (`findings-exact278.json`), the target site:

```
BrokerDataClasses/GTD.cs:5192  OWN001  subscription-leak
  event 'AppData.Properties.GBProperty.PropertyChanged' is subscribed
  (handler 'GBProperty_PropertyChanged') but never unsubscribed …
```

## Runtime record (one artifact for all three)

```
type BrokerDataClasses.GTD   count 76   expected 0
root: static-event  holder BrokerDataClasses.Property.GBProperty  member PropertyChanged
chain: [PinnedHandle] Object[] → KernelProperty → GBProperty
       → PropertyChangedEventHandler → Object[] → PropertyChangedEventHandler → GTD
```

(KDT: 3 reachable prototype instances, static-field roots — no event identity, so it
correlates through the unchanged type-level fallback.)

## Correlation results

| Snapshot | confirmed / static-only / runtime-only | GTD verdict |
|---|---|---|
| pre-#278 | 42 / 168 / 36 | **runtime-only**: `76 retained GTD … held by static BrokerDataClasses.Property.GBProperty.PropertyChanged — static blind spot`; **0** confirmed lines against `GTD.cs` (the unrelated GTD OWN001s stayed static-only) |
| exact #278 | 132 / 326 / 19 | **confirmed, high**, exactly one `GTD.cs` line: `[confirms static OWN001 at BrokerDataClasses/GTD.cs:5192]`, matched root `GBProperty.PropertyChanged` |
| current main | 132 / 326 / 19 | identical to exact #278 — no late drift |

KDT (`KDT.cs:60/61`, the `:88` site under its dsector line number) is confirmed
(medium) in both post snapshots via the type-level fallback.

## Verdict

The retention did not move; the analyzer did. Under member-aware correlation the
same heap record classifies **runtime-only before #278 and confirmed (high, at the
exact 5192 site) after** — the transition is attributable to the analyzer change and
nothing else. The collector-plan step-7 follow-up ("member-aware matching") is closed.

Committed reduced fixtures reproducing this transition synthetically:
`runtime/fixtures/gtd-transition-{pre,post,runtime}.json`
(`runtime/tests/test_member_aware.py`).
