"""T4 — the OWN001/OWN014 fixer (docs/fix-arm.md §3/§5). The ONE fixer no
off-the-shelf tool covers: own-check's subscription / region-escape leaks.

It plugs into the same wrapper as every other applier (orchestrate.run_fix), so
it inherits dry-run, the no-new-findings regression gate, and rollback for free.
OWN rules are tier T4 → the wrapper always routes the result to REVIEW; nothing
here auto-commits, because lifetime-correct teardown placement is a judgement call.

Scope of THIS slice — honest about the boundary:
  * FIXES the named-handler subscription shape
        src.Event += Handler;   (Handler a method group or `new D(M)`)
    by inserting a teardown detach next to it:
        this.<Closed|Unloaded> += (s, e) => src.Event -= Handler;
    Closed for a Window, Unloaded for a FrameworkElement; anything else is left
    for review (we can't pick a safe teardown blind).
  * REFUSES the inline-lambda shape
        src.Event += (s, e) => ...;
    own-check itself says it "has no '-=' handle, so it could never be detached".
    A lambda must be extracted to a named handler FIRST, which is a real refactor —
    so we classify it suggest-only and never emit a patch that pretends to fix it.
"""
from __future__ import annotations

import difflib
import os
import re

# event '<src.event>' is subscribed (handler '<handler>')
_SUB_RE = re.compile(r"event '([^']+)' is subscribed \(handler '(.+?)'\)", re.S)

NAMED_HANDLER_SUB = "named-handler-sub"   # fixable: insert a detach
INLINE_LAMBDA_SUB = "inline-lambda-sub"   # suggest-only: needs extraction first
OTHER = "other"                           # not a subscription shape we handle here


def classify(message: str):
    """(shape, src_event, handler). Inline lambdas (handler contains `=>`, or the
    message flags 'inline lambda') are suggest-only — they have no detach handle."""
    m = _SUB_RE.search(message or "")
    if not m:
        return OTHER, None, None
    src_event, handler = m.group(1), m.group(2)
    if "=>" in handler or "inline lambda" in (message or ""):
        return INLINE_LAMBDA_SUB, src_event, handler
    return NAMED_HANDLER_SUB, src_event, handler


def _teardown_event(decl_tail: str):
    """Pick the conventional teardown for the owner's base type, or None if we
    can't choose one safely (then the site is left for manual review)."""
    if re.search(r"\bWindow\b", decl_tail):
        return "Closed"
    if re.search(r"\b(UserControl|FrameworkElement|Control|Page)\b", decl_tail):
        return "Unloaded"
    return None


def _enclosing_class(lines: list[str], idx: int):
    """Nearest `class X : Base...` at or above line idx → (name, decl-tail)."""
    for i in range(idx, -1, -1):
        m = re.search(r"\bclass\s+(\w+)([^{]*)", lines[i])
        if m:
            return m.group(1), m.group(2)
    return None, ""


def _find_sub_line(lines: list[str], line_1based: int, src_event: str):
    """Locate the `src_event += ...` statement near the reported line (±3 for drift)."""
    target = line_1based - 1
    for idx in [target] + [target + d for d in (1, -1, 2, -2, 3, -3)]:
        if 0 <= idx < len(lines) and src_event in lines[idx] and "+=" in lines[idx]:
            return idx
    return None


def plan_file(path: str, findings):
    """Compute (new_content, applied, skipped) for one file. `applied`/`skipped`
    are (finding, detail) lists so the ledger can report exactly what was and
    wasn't fixed — no silent drops (docs/fix-arm.md §8)."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    inserts: list[tuple[int, str]] = []
    applied, skipped = [], []
    for f in findings:
        shape, src_event, handler = classify(f.message)
        if shape != NAMED_HANDLER_SUB:
            skipped.append((f, shape))
            continue
        idx = _find_sub_line(lines, f.line, src_event)
        if idx is None:
            skipped.append((f, "site-not-found"))
            continue
        _, decl = _enclosing_class(lines, idx)
        ev = _teardown_event(decl)
        if ev is None:
            skipped.append((f, "no-safe-teardown"))
            continue
        indent = re.match(r"\s*", lines[idx]).group(0)
        inserts.append((idx, f"{indent}this.{ev} += (s, e) => {src_event} -= {handler};\n"))
        applied.append((f, ev))
    # insert bottom-up so earlier indices stay valid
    for idx, text in sorted(inserts, key=lambda t: t[0], reverse=True):
        lines.insert(idx + 1, text)
    return "".join(lines), applied, skipped


class OwnFixApplier:
    """Applier for OWN001/OWN014. Constructed with the findings to fix (the wrapper
    selects them by rule). Snapshots originals on apply so `revert` can roll back a
    rejected fix, satisfying the wrapper's safety contract."""
    name = "own-fix"

    def __init__(self, findings):
        self.findings = list(findings)
        self._orig: dict[str, str] = {}
        self.skipped: list = []   # populated on the last plan — suggest-only / unfixable

    def _by_file(self):
        byf: dict[str, list] = {}
        for f in self.findings:
            byf.setdefault(f.path, []).append(f)
        return byf

    def _plan(self, workdir: str):
        out, skipped = {}, []
        for rel, fs in self._by_file().items():
            new, _applied, sk = plan_file(os.path.join(workdir, rel), fs)
            out[rel] = new
            skipped.extend(sk)
        self.skipped = skipped
        return out

    def dry_run(self, workdir: str, rule: str) -> str:
        chunks = []
        for rel, new in self._plan(workdir).items():
            with open(os.path.join(workdir, rel), encoding="utf-8") as fh:
                old = fh.readlines()
            chunks.extend(difflib.unified_diff(
                old, new.splitlines(keepends=True), fromfile=f"a/{rel}", tofile=f"b/{rel}"))
        return "".join(chunks)

    def apply(self, workdir: str, rule: str) -> None:
        for rel, new in self._plan(workdir).items():
            p = os.path.join(workdir, rel)
            if rel not in self._orig:
                with open(p, encoding="utf-8") as fh:
                    self._orig[rel] = fh.read()
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(new)

    def revert(self, workdir: str) -> None:
        for rel, orig in self._orig.items():
            with open(os.path.join(workdir, rel), "w", encoding="utf-8") as fh:
                fh.write(orig)
        self._orig.clear()
