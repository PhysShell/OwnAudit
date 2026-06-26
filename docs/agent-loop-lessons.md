# Agent-loop lessons for the fix-arm (from COMPILOT)

Notes mined from *Agentic Auto-Scheduling: An Experimental Study of LLM-Guided Loop
Optimization* (COMPILOT, Merouani et al., PACT 2025). COMPILOT puts an off-the-shelf LLM in a
closed loop with a compiler: the model proposes loop transformations, the compiler checks
legality + measures speedup, the typed outcome is fed back, repeat. Different domain, but the
*agent-loop mechanics* map directly onto our fix-arm (LLM proposes a fix → re-audit verifies →
typed feedback → revise). This captures what transfers so it isn't lost.

## Where COMPILOT validates what we already do

- **Delegate correctness to a deterministic verifier, never the LLM (RQ7).** COMPILOT has the LLM
  emit a *transformation*, and the compiler's polyhedral analysis guarantees legality. When they
  instead let the LLM rewrite code directly and verified by output-comparison, **17.6% of
  "passing" schedules were actually wrong** under random inputs, at **5.3× the tokens**. Our
  fix-arm does exactly the safe thing: the LLM rewrites a window, but the **real analyzers
  re-audit** and we **reject any fix that introduces a new finding** — formal-ish verification,
  not eyeballing. Strong external validation of the tier+re-audit design (`docs/fix-arm.md §4`).
- **The feedback loop is the whole game (RQ6).** With feedback, +23–40% over open-loop, and the
  gap *widens* with iterations. Our `AiFixApplier` already runs a verify→revise loop.
- **Stopping + give-up.** COMPILOT caps iterations and records premature stops; we cap
  `max_rounds` and record `ai-gave-up`.

## Adopted now (this change)

- **Accumulated attempt history, not just the last rejection.** Our LLM client is *stateless*
  (`complete(system, user)` — no chat history), so across revise rounds the model only ever saw
  the **most recent** rejection reason and could re-propose an identical failed fix. COMPILOT's
  loop works because *every* prior outcome stays in the dialogue (illegal-rate drops from ~60% at
  T=1 as negative feedback accumulates — RQ3). Fix: `_revise` now threads the full history of
  rejected candidates + their specific reasons into each prompt ("do NOT repeat them; try a
  DIFFERENT fix").
- **Specific typed feedback.** "it introduced new findings" → now lists *which* (`rule@file:line`),
  giving the model something to act on, like COMPILOT's per-failure reasons.

## Menu for later (documented, not built)

- **Best-of-K restarts (RQ1/RQ9).** Beyond the sequential revise chain, restart the dialogue from
  scratch K times and keep the best — COMPILOT uses K=5 to escape local optima. For hard T4/OWN
  findings, K independent attempts (fresh context) → take the first that re-audits clean. A
  quality/cost knob; diminishing returns measured (their T=30/K=5).
- **Reasoning-first / analysis step (RQ10).** COMPILOT forces a CoT analysis before proposing and
  a reasoning section per turn — "tangible benefits". We currently suppress reasoning ("Return
  ONLY the corrected replacement") for clean parsing. Tradeoff: a `<reasoning>…</reasoning>`
  preamble (our fence regex already ignores anything outside the ```csharp block) would add the
  benefit *and* seed the deferred AI-explanation layer — at some token + parse-robustness cost.
- **Two-stage check: cheap pre-filter before the expensive re-audit.** COMPILOT runs a
  compiler-independent validity check (syntax, valid identifiers, preconditions) *before* the
  costly compiler. Our re-audit (a full analyzer pass on the stand) is the expensive step; a
  lightweight pre-check on the candidate (parses? actually different? brace-balanced? sane line
  delta?) could skip a re-audit round for obviously-bad candidates.
- **Measured iteration budget.** COMPILOT charted tokens vs iterations and chose T/K at the
  diminishing-returns knee. Our `max_rounds=3` is a guess; worth measuring once we run against a
  real local model + real re-audit cost.
