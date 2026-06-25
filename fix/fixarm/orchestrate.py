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
    def revert(self, workdir: str) -> None: ...              # undo apply() — restore workdir


def _revert(applier: "Applier", workdir: str) -> bool:
    """Roll a rejected/ineffective apply back out of the tree. Returns whether a
    revert capability existed. The safety contract requires the worktree to be
    restored on every non-success path, so a non-revertable applier is a defect,
    not a silent no-op — surfaced via FixResult.reverted in the ledger."""
    fn = getattr(applier, "revert", None)
    if fn is None:
        return False
    fn(workdir)
    return True


Reaudit = Callable[[str], list[Finding]]   # re-run the audit over a tree -> findings


# ---- diffing two audit runs ------------------------------------------------

def diff_findings(before: Iterable[Finding], after: Iterable[Finding], line_tol: int = 0):
    """Returns (removed, introduced). 'introduced' = present after but not before —
    the regression set the safety contract rejects on. Within each (rule, basename)
    group, before/after findings are matched by ABSOLUTE line distance ≤ line_tol
    (nearest-first, greedy), so a fix that shifts a diagnostic by ≤ line_tol lines is
    treated as the same finding, not as one removed + one introduced. With line_tol=0
    this is exact-line matching. Multiplicity-aware: N copies need N matches."""
    from collections import defaultdict

    def group(findings) -> dict:
        g: dict = defaultdict(list)
        for f in findings:
            g[(f.rule, f.basename)].append(f)
        return g

    gb, ga = group(before), group(after)
    removed: list[Finding] = []
    introduced: list[Finding] = []
    for key in set(gb) | set(ga):
        bs = sorted(gb.get(key, []), key=lambda f: f.line)
        as_ = sorted(ga.get(key, []), key=lambda f: f.line)
        used = [False] * len(as_)
        for bf in bs:
            best, best_d = -1, None
            for i, af in enumerate(as_):
                if used[i]:
                    continue
                d = abs(af.line - bf.line)
                if d <= line_tol and (best_d is None or d < best_d):
                    best, best_d = i, d
            if best >= 0:
                used[best] = True          # matched — survives, neither side
            else:
                removed.append(bf)
        introduced.extend(af for i, af in enumerate(as_) if not used[i])
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
    reverted: bool = False   # was the tree rolled back on a non-success path?

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
            "reverted": self.reverted,
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

    # Everything after apply() must restore the tree on any non-success path — a
    # rejected/ineffective fix (or a re-audit that throws) must not leak into a
    # later rule run or a manual commit (docs/fix-arm.md §4).
    try:
        after = reaudit(workdir)
    except Exception:
        _revert(applier, workdir)
        raise

    removed, introduced = diff_findings(before, after, line_tol)
    targeted_removed = [f for f in removed if f.rule == rule]

    # Safety contract §4.4: a fix that introduces ANY new finding is rejected,
    # regardless of tier. Trading one finding for another is not a fix.
    if introduced:
        reverted = _revert(applier, workdir)
        return FixResult(rule, REJECTED, tier, gate, targeted_removed, introduced,
                         diff, len(selected), reverted)
    if not targeted_removed:
        reverted = _revert(applier, workdir)
        return FixResult(rule, NO_EFFECT, tier, gate, [], [], diff, len(selected), reverted)

    # OK: the fix stays in the tree — it is the deliverable (auto-commit or review).
    return FixResult(rule, OK, tier, gate, targeted_removed, [], diff, len(selected))
