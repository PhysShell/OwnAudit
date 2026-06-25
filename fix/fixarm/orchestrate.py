"""The Fix-arm wrapper: select -> dry-run -> apply -> re-audit -> assert-no-new
-> tier gate (docs/fix-arm.md §4). The applier and the re-audit are pluggable
(appliers.py): real adapters drive roslynator/dotnet-format + Run-Audit.ps1 on a
.NET stand; replay adapters drive recorded fixtures in CI/Linux. The logic here —
selection, the no-new-findings regression check, the gate, the coverage ledger —
is identical in both and is what these tests exercise.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol

from . import tiers


# ---- model -----------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int
    tool: str = ""
    message: str = ""

    @property
    def basename(self) -> str:
        return os.path.basename(self.path.replace("\\", "/"))

    def key(self, line_tol: int = 0) -> tuple:
        """Identity for set-diffing two audit runs. Mirrors the audit's own
        matching: same rule + same basename + line within tolerance. With
        line_tol>0 the line is bucketed so a fix that shifts lines still matches."""
        ln = self.line if line_tol <= 0 else self.line // (line_tol + 1)
        return (self.rule, self.basename, ln)


def load_findings(path: str) -> list[Finding]:
    with open(path, encoding="utf-8") as fh:
        return findings_from_obj(json.load(fh))


def findings_from_obj(obj: dict) -> list[Finding]:
    out = []
    for f in obj.get("findings", []):
        out.append(Finding(
            rule=f.get("rule", ""),
            path=f.get("path", ""),
            line=int(f.get("line", 0) or 0),
            tool=f.get("tool", ""),
            message=f.get("message", ""),
        ))
    return out


# ---- pluggable applier + re-audit ------------------------------------------

class Applier(Protocol):
    name: str
    def dry_run(self, workdir: str, rule: str) -> str: ...   # reviewable patch text
    def apply(self, workdir: str, rule: str) -> None: ...     # mutate workdir in place


Reaudit = Callable[[str], list[Finding]]   # re-run the audit over a tree -> findings


# ---- diffing two audit runs ------------------------------------------------

def diff_findings(before: Iterable[Finding], after: Iterable[Finding], line_tol: int = 0):
    """Returns (removed, introduced). 'introduced' = present after but not before —
    the regression set the safety contract rejects on. Multiplicity-aware so two
    findings of the same key don't collapse."""
    from collections import Counter
    b = Counter(f.key(line_tol) for f in before)
    a = Counter(f.key(line_tol) for f in after)
    before_by_key: dict = {}
    after_by_key: dict = {}
    for f in before:
        before_by_key.setdefault(f.key(line_tol), []).append(f)
    for f in after:
        after_by_key.setdefault(f.key(line_tol), []).append(f)
    removed, introduced = [], []
    for key in (b - a).elements():
        removed.append(before_by_key[key].pop())
    for key in (a - b).elements():
        introduced.append(after_by_key[key].pop())
    return removed, introduced


# ---- result + ledger -------------------------------------------------------

OK = "ok"               # fix applied, no regression; gate decides commit vs review
REJECTED = "rejected"   # fix introduced new findings -> reverted, never committed
NO_EFFECT = "no-effect" # applier ran but the targeted finding survived
NO_OP = "no-op"         # nothing selected for this rule
UNFIXABLE = "unfixable" # detect-only (T3) — no applier can fix it


@dataclass
class FixResult:
    rule: str
    status: str
    tier: str
    gate: str
    targeted_removed: list = field(default_factory=list)
    introduced: list = field(default_factory=list)
    diff: str = ""
    selected: int = 0

    @property
    def committable(self) -> bool:
        return self.status == OK and self.gate == tiers.AUTO

    def ledger(self) -> dict:
        """Coverage ledger (docs/fix-arm.md §8): never report a 'fixed' count that
        hides queued/rejected/unfixable work."""
        return {
            "rule": self.rule, "tier": self.tier, "status": self.status,
            "gate": self.gate, "selected": self.selected,
            "fixed_sites": len(self.targeted_removed),
            "introduced": len(self.introduced),
        }


# ---- the wrapper -----------------------------------------------------------

def run_fix(
    before: list[Finding],
    workdir: str,
    rule: str,
    applier: Applier,
    reaudit: Reaudit,
    line_tol: int = 0,
    tier_of: Callable[[str, str], str] = tiers.tier_of,
) -> FixResult:
    selected = [f for f in before if f.rule == rule]
    tool = selected[0].tool if selected else ""
    tier = tier_of(rule, tool)
    gate = tiers.gate_for_tier(tier)

    # T3: detect-only. No applier can fix it — report honestly, do not touch the tree.
    if tier == tiers.T3:
        return FixResult(rule, UNFIXABLE, tier, tiers.UNFIXABLE, selected=len(selected))
    if not selected:
        return FixResult(rule, NO_OP, tier, gate, selected=0)

    diff = applier.dry_run(workdir, rule)
    applier.apply(workdir, rule)
    after = reaudit(workdir)

    removed, introduced = diff_findings(before, after, line_tol)
    targeted_removed = [f for f in removed if f.rule == rule]

    # Safety contract §4.4: a fix that introduces ANY new finding is rejected,
    # regardless of tier. Trading one finding for another is not a fix.
    if introduced:
        return FixResult(rule, REJECTED, tier, gate, targeted_removed, introduced,
                         diff, len(selected))
    if not targeted_removed:
        return FixResult(rule, NO_EFFECT, tier, gate, [], [], diff, len(selected))

    return FixResult(rule, OK, tier, gate, targeted_removed, [], diff, len(selected))
