"""leakmine — the LeakFixMine research pipeline (docs/leakfix-mine.md).

Mines real managed-lifetime / resource-leak *fixes* across ecosystems, proves each
one was actually a leak fix (and not a lucky coincidence) by historical attribution,
then runs OwnAudit vs baseline linters over the before/after revisions and scores the
result. It is deliberately the *honest* arm of the data story (docs/audit-data-leverage.md
§3): a fixed-bug corpus is a regression set, not a recall denominator, so the heavy
lifting here is separating signal from luck.

Three independent experiment designs share these modules (see the doc):
  - fixed-bug corpus  — `collect` + `signals` + `szz` + `confirm`  (regression tests)
  - prospective sweep — `sweep`                                    (precision in the wild)
  - time-travel       — `szz.lead_time`                           (would-have-caught-earlier)

Pure stdlib, no network in the testable core: `diffparse`/`signals`/`confirm`/`metrics`
are pure transforms; `szz` shells out to the local `git`; only `collect`/`sweep` reach
the network, and even they generate their queries deterministically so they unit-test
offline.
"""

__all__ = [
    "diffparse",
    "signals",
    "szz",
    "confirm",
    "metrics",
    "sweep",
    "collect",
    "schema",
    "mine",
    "bigquery",
]
