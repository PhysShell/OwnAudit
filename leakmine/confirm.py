"""Verdict combiner — turn raw before/after tool runs + a patch into one honest judgement.

`signals` says *this PR looks like a leak fix*; `szz` says *whether each tool's finding is
causally tied to it*. This module fuses them per candidate into a `Verdict` the metrics
stage can aggregate:

  - is_real_fix       — is this genuinely a lifetime/resource fix? Judged from the PATCH
                        (signal evidence), NOT from whether a tool caught it — a real fix
                        no tool saw is exactly the interesting case we must not discard.
  - caught_by         — tools whose finding is a *confirmed catch* (flagged before, gone
                        after, causally on the fixed lines).
  - missed_by         — tools that should have caught it (real fix) but didn't.
  - unique_to_ownaudit — OwnAudit caught it and no baseline did. The headline number.
  - fp_after          — tools still firing the same rule on the fixed file after the fix
                        (precision smell: likely a false positive, or an incomplete fix).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import diffparse
from . import signals as sig
from . import szz


@dataclass
class Candidate:
    """One mined fix, fully materialised for judging."""
    id: str
    ecosystem: str
    title: str
    body: str
    patch: str
    # tool -> findings on the pre-fix / post-fix revision (szz.Finding).
    before: dict[str, list[szz.Finding]] = field(default_factory=dict)
    after: dict[str, list[szz.Finding]] = field(default_factory=dict)


@dataclass
class Verdict:
    candidate_id: str
    ecosystem: str
    category: str
    signal_score: int
    is_real_fix: bool
    caught_by: list[str] = field(default_factory=list)
    missed_by: list[str] = field(default_factory=list)
    unique_to_ownaudit: bool = False
    fp_after: list[str] = field(default_factory=list)
    # analysis tier of the OwnAudit catch, if any (syntactic|semantic|interproc).
    own_resolution: str = ""
    notes: list[str] = field(default_factory=list)


def _confirmed_catches(cand: Candidate, tool: str, window: int) -> list[szz.Finding]:
    """Findings from `tool` that are confirmed catches on this candidate."""
    before = cand.before.get(tool, [])
    after = cand.after.get(tool, [])
    out = []
    for f in before:
        corr = szz.correspond(before, after, cand.patch, f, window=window)
        if corr.confirmed_catch:
            out.append(f)
    return out


def _fp_after(cand: Candidate, tool: str) -> bool:
    """Same (rule, file) still present after the fix touched that file → precision smell."""
    after = cand.after.get(tool, [])
    touched = {fd.path for fd in diffparse.parse_patch(cand.patch)}
    return any(f.file in touched for f in after)


def judge(
    cand: Candidate,
    *,
    ownaudit_tool: str = "ownaudit",
    baseline_tools: tuple[str, ...] = (),
    window: int = 2,
) -> Verdict:
    cls = sig.classify(cand.ecosystem, title=cand.title, body=cand.body, patch=cand.patch)

    caught_by: list[str] = []
    own_res = ""
    all_tools = (ownaudit_tool, *baseline_tools)
    for tool in all_tools:
        catches = _confirmed_catches(cand, tool, window)
        if catches:
            caught_by.append(tool)
            if tool == ownaudit_tool:
                # report the deepest resolution tier among OwnAudit's catches.
                order = {"syntactic": 0, "semantic": 1, "interproc": 2, "": -1}
                own_res = max((c.resolution for c in catches), key=lambda r: order.get(r, -1))

    is_real = cls.is_likely_fix or bool(caught_by)
    missed_by = [t for t in all_tools if t not in caught_by] if is_real else []
    unique = (ownaudit_tool in caught_by) and not any(b in caught_by for b in baseline_tools)
    fp_after = [t for t in all_tools if _fp_after(cand, t)]

    notes: list[str] = []
    if is_real and not caught_by:
        notes.append("real-fix-no-tool-caught")  # the precious unique-miss bucket
    if cls.is_candidate and not cls.is_likely_fix:
        notes.append("borderline-send-to-review")

    return Verdict(
        candidate_id=cand.id,
        ecosystem=cand.ecosystem,
        category=cls.category,
        signal_score=cls.score,
        is_real_fix=is_real,
        caught_by=caught_by,
        missed_by=missed_by,
        unique_to_ownaudit=unique,
        fp_after=fp_after,
        own_resolution=own_res,
        notes=notes,
    )
