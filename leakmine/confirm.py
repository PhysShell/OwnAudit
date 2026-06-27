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
    """Same (rule, file) present BOTH before and after, on a file the fix touched →
    precision smell (a likely false positive, or an incomplete fix). Matching the full
    (rule, file) pair — not just "any finding on a touched file" — keeps an unrelated rule
    on the same file from inflating fp_after."""
    before_pairs = {(f.rule, f.file) for f in cand.before.get(tool, [])}
    after_pairs = {(f.rule, f.file) for f in cand.after.get(tool, [])}
    touched = {p for fd in diffparse.parse_patch(cand.patch)
               for p in (fd.old_path, fd.new_path, fd.path) if p}
    return any(pair in after_pairs and pair[1] in touched for pair in before_pairs)


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

    # Ground truth = the PATCH signal, never a tool catch. Deriving "real fix" from
    # caught_by would be circular — it biases the corpus toward what the tools already
    # find and inflates their apparent recall. Borderline patches (candidate but not
    # likely_fix) are routed to review below, not auto-promoted by a catch.
    is_real = cls.is_likely_fix
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
