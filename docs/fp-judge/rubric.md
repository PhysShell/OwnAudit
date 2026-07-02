# FP-judge rubric v0 (fills `{{rubric}}` in the `o7 judge` prompt)

Owner: **OwnAudit (domain) agent.** This is *what a verdict means*. 007 injects this
verbatim into the per-file judge prompt; it does not interpret it. Tuned in the
Phase-1 manual-proof loop.

## The judge's job
For each own-check finding in a file, given the **whole file**, classify it:
`real` (a genuine defect), `false_positive` (own-check is wrong here), or
`uncertain` (the file alone is insufficient). Always give a one-line `reason` and,
when possible, `evidence` (a line number or the specific fact).

## Standing rules (all classes)
1. **Judge only from the provided file.** Do not invent teardown you cannot see.
   *Exception:* if teardown would plausibly live in an unseen base class / partial,
   that is **`uncertain`**, not `false_positive`.
2. **Do not rubber-stamp.** own-check over-reports this residual, but a
   `false_positive` needs a concrete, citable reason. When in doubt → `uncertain`.
3. **Confidence:** high only when the deciding fact is explicit in the file; low when
   you infer object lifetime/ownership.
4. **Evidence:** for `false_positive`, cite the teardown site (`:line`) or the fact
   (static handler / owned source). For `real`, state what makes it a leak
   ("no teardown in type; instance handler roots the subscriber").

---

## Class: `subscription-leak` (OWN001) — the bulk (156)
own-check flags `event += handler` on a source of injected/unknown/static lifetime
with no matching release. After the delegate-normalization fix, the residual is
subscriptions with an **instance/capturing** handler and **no `-=` anywhere** the
checker could see.

**`real` when ALL hold:**
- the source can outlive the subscriber — an injected/parameter/DI dependency, a
  `static`/`App`-level event, or a shared bus/aggregator; AND
- the handler roots the subscriber — an **instance method**, or a lambda that
  captures `this`/an instance member/an enclosing local; AND
- **no teardown** in the type: no `-=` for this source+handler in any form, no
  `Dispose`/`Unloaded`/`Closed`/`OnClosed` that detaches, no `using`, no handoff.

**`false_positive` when ANY hold (name which):**
- **teardown exists, own-check missed the spelling** — a `-=` via an aliased/differently-
  spelled receiver, a detach inside `Closed`/`Unloaded`/a dispatcher callback, a detach
  folded into a base teardown you *can* see, source set to `null`, etc.
- **handler retains no instance** — a `static` method, or a non-capturing / static-call
  lambda (null target → roots nothing).
- **source is owned / short-lived** — constructed by this type (`_x = new …`), a local,
  or a child control the type disposes; a self-owned cycle is GC-collectable.
- **subscriber is process-lived** (the WPF `App` singleton) — the "escape" pins nothing new.

**`uncertain` when:**
- **rebinding setter** — the source is reassigned in a setter that detaches the *old*
  value each time, but the *last-assigned* source is never torn down; a leak only if
  that last source outlives the subscriber and is not owned — undecidable from the file.
  (This is the known non-flow-sensitive gap; the checker calls it released.)
- an injected source whose lifetime truly needs cross-file knowledge; or ambiguous capture.

---

## Class: `idisposable-leak` (OWN001, category 1) — 47
own-check flags a disposable field/local that is never disposed.

- **`real`:** a value of an `IDisposable` type created here (`new X()` / a factory)
  and not disposed on some path — no `Dispose`/`using`/`Close`, not handed off.
- **`false_positive`:** disposed via `using` / `Dispose()` / `Close()` / a teardown;
  **ownership transferred** (returned, added to a collection/owner that disposes it —
  e.g. `Controls.Add`, passed to a wrapper that owns it); or it wraps **managed-only
  memory** with no unmanaged handle (`MemoryStream`, `DataTable`, `Task`) where a
  missing `Dispose` is benign.
- **`uncertain`:** dispose via a helper/indirection you cannot confirm; conditional
  dispose on one path only.

---

## Class: `region-escape` (OWN014) — 7
own-check flags a subscription/capture escaping to a longer-lived (static/App) region.

- **`real`:** the capture escapes to a `static`/`App`/process-lived region and pins
  the instance, with no teardown.
- **`false_positive`:** an **intended process-lifetime hook** — `AppDomain`
  `ProcessExit`/`DomainUnload`/`UnhandledException`/`FirstChanceException`; the captured
  target is itself process-lived; or it is torn down.
- **`uncertain`:** the escape target's lifetime is unclear from the file.

---

## Output (per finding)
`class`, `confidence` (0..1), `reason` (≤1 line), `evidence` (line/fact when available)
— exactly the fields in `verdict-contract.md`. Nothing else.
