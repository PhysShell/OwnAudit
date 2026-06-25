"""T4 — the OWN001/OWN014 fixer (docs/fix-arm.md §3/§5). The ONE fixer no
off-the-shelf tool covers: own-check's subscription / region-escape leaks.

It plugs into the same wrapper as every other applier (orchestrate.run_fix), so
it inherits dry-run, the no-new-findings regression gate, and rollback for free.
OWN rules are tier T4 → the wrapper always routes the result to REVIEW; nothing
here auto-commits, because lifetime-correct teardown placement is a judgement call.

Scope of THIS slice — honest about the boundary. For a WPF owner we hang the cleanup
on a teardown event (Closed for a Window, Unloaded for a FrameworkElement); anything
else is left for review (we can't pick a safe teardown blind).
  * FIXES the named-handler subscription shape — `src.Event += Handler;` (method group
    or `new D(M)`) → `this.<teardown> += (s, e) => src.Event -= Handler;`
  * FIXES the disposable-field shape — an IDisposable field never disposed (a Timer,
    CancellationTokenSource, …) → `this.<teardown> += (s, e) => field?.Dispose();`,
    anchored after the ctor's InitializeComponent().
  * REFUSES the inline-lambda subscription — own-check says it "has no '-=' handle, so
    it could never be detached"; a lambda needs extraction to a named handler first.
  * REFUSES the disposable-local shape — wrapping a local needs a scoped `using`, not a
    teardown hook. Both refusals are classified suggest-only, never a fake patch.
"""
from __future__ import annotations

import difflib
import os
import re

# event '<src.event>' is subscribed (handler '<handler>')
_SUB_RE = re.compile(r"event '([^']+)' is subscribed \(handler '(.+?)'\)", re.S)
_FIELD_RE = re.compile(r"IDisposable field '([^']+)'")     # ... is never disposed
_LOCAL_RE = re.compile(r"IDisposable local '([^']+)'")

NAMED_HANDLER_SUB = "named-handler-sub"   # fixable: insert a detach
DISPOSABLE_FIELD = "disposable-field"     # fixable on a WPF owner: dispose on teardown
INLINE_LAMBDA_SUB = "inline-lambda-sub"   # suggest-only: needs lambda extraction first
DISPOSABLE_LOCAL = "disposable-local"     # suggest-only: needs a scoped `using`
OTHER = "other"                           # not a shape we handle here


def _safe_join(workdir: str, rel: str) -> str:
    """Join `rel` onto `workdir`, rejecting absolute paths and `..` escapes.
    Finding.path is loaded verbatim from external findings JSON, so it must be
    confirmed to stay inside the worktree before any open()/write()."""
    base = os.path.abspath(workdir)
    full = os.path.abspath(os.path.join(base, rel))
    if os.path.isabs(rel) or (full != base and not full.startswith(base + os.sep)):
        raise ValueError(f"unsafe finding path escapes workdir: {rel!r}")
    return full


def classify(message: str):
    """(shape, a, b). For subscriptions a=src.event, b=handler; for a disposable
    field a=field name, b=None. Inline lambdas (handler has `=>`) and disposable
    locals are suggest-only — they have no detach handle / need a scoped `using`."""
    msg = message or ""
    m = _SUB_RE.search(msg)
    if m:
        src_event, handler = m.group(1), m.group(2)
        if "=>" in handler or "inline lambda" in msg:
            return INLINE_LAMBDA_SUB, src_event, handler
        return NAMED_HANDLER_SUB, src_event, handler
    m = _FIELD_RE.search(msg)
    if m:
        return DISPOSABLE_FIELD, m.group(1), None
    m = _LOCAL_RE.search(msg)
    if m:
        return DISPOSABLE_LOCAL, m.group(1), None
    return OTHER, None, None


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


_CF_KW = r"if|else|while|for|foreach|using|lock"


def _in_unbraced_control_flow(lines: list[str], idx: int) -> bool:
    """True if the subscription at `idx` is the single statement of an unbraced
    control-flow body — e.g. `if (x != null) src.Event += H;` or an `if (...)`
    header on the line above with no `{`. Inserting an unconditional teardown next
    to it would register the detach even when the guarded subscription was skipped,
    or split an `if`/`else`. Such sites are left for review, never auto-patched."""
    # (a) inline guard on the same line, before the '+=' (e.g. `if (x != null) a.E += h;`)
    pre = lines[idx].split("+=", 1)[0]
    if re.search(rf"\b({_CF_KW})\b", pre):
        return True
    # (b) previous meaningful line is an unbraced control-flow header / else / do
    j = idx - 1
    while j >= 0 and (not lines[j].strip() or lines[j].lstrip().startswith("//")):
        j -= 1
    if j >= 0:
        prev = lines[j].rstrip()
        if not prev.endswith("{") and (
            (re.match(rf"^\s*(\}}\s*)?({_CF_KW})\b", prev) and prev.endswith(")"))
            or re.match(r"^\s*(else|do)\s*$", prev)
        ):
            return True
    # (c) next meaningful line is `else` — our insertion would split the if/else
    k = idx + 1
    while k < len(lines) and not lines[k].strip():
        k += 1
    if k < len(lines) and re.match(r"^\s*else\b", lines[k]):
        return True
    return False


def _find_sub_line(lines: list[str], line_1based: int, src_event: str):
    """Locate the `src_event += ...` statement near the reported line (±3 for drift)."""
    target = line_1based - 1
    for idx in [target] + [target + d for d in (1, -1, 2, -2, 3, -3)]:
        if 0 <= idx < len(lines) and src_event in lines[idx] and "+=" in lines[idx]:
            return idx
    return None


def _find_ctor_anchor(lines: list[str], field_line_1based: int):
    """For a disposable field (reported at its declaration), find an in-ctor anchor to
    hang the teardown on: the `InitializeComponent()` call of the field's enclosing
    class. WPF code-behind reliably has one, and a statement after it is in scope for
    `this.<teardown> += ...`. Returns None (→ suggest-only) if there's no such anchor."""
    start = field_line_1based - 1
    cls_idx = None
    for i in range(min(start, len(lines) - 1), -1, -1):
        if re.search(r"\bclass\s+\w+", lines[i]):
            cls_idx = i
            break
    if cls_idx is None:
        return None
    for i in range(cls_idx, len(lines)):
        if "InitializeComponent()" in lines[i]:
            return i
    return None


def plan_file(path: str, findings):
    """Compute (new_content, applied, skipped) for one file. `applied`/`skipped`
    are (finding, detail) lists so the ledger can report exactly what was and
    wasn't fixed — no silent drops (docs/fix-arm.md §8)."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    inserts: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    applied, skipped = [], []
    for f in findings:
        shape, a, b = classify(f.message)
        # Per shape: find the in-scope anchor line and the statement to run on teardown.
        if shape == NAMED_HANDLER_SUB:                  # a=src.event, b=handler
            idx = _find_sub_line(lines, f.line, a)
            stmt = None if idx is None else f"{a} -= {b}"
        elif shape == DISPOSABLE_FIELD:                 # a=field name
            idx = _find_ctor_anchor(lines, f.line)
            stmt = None if idx is None else f"{a}?.Dispose()"
        else:                                           # lambda / local / other -> suggest-only
            skipped.append((f, shape))
            continue
        if idx is None:
            skipped.append((f, "site-not-found" if shape == NAMED_HANDLER_SUB else "no-ctor-anchor"))
            continue
        if _in_unbraced_control_flow(lines, idx):
            skipped.append((f, "unbraced-control-flow"))
            continue
        _, decl = _enclosing_class(lines, idx)
        ev = _teardown_event(decl)
        if ev is None:
            skipped.append((f, "no-safe-teardown"))
            continue
        indent = re.match(r"\s*", lines[idx]).group(0)
        ins = (idx, f"{indent}this.{ev} += (s, e) => {stmt};\n")
        if ins in seen:
            skipped.append((f, "duplicate-site"))   # detach already planned; keep the ledger complete
            continue
        seen.add(ins)
        inserts.append(ins)
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
        """`findings` are the OWN findings to fix (the wrapper selects them by rule)."""
        self.findings = list(findings)
        self._orig: dict[str, str] = {}
        self.skipped: list = []   # populated on the last plan — suggest-only / unfixable

    def _by_file(self):
        """Group this applier's findings by their (relative) source path."""
        byf: dict[str, list] = {}
        for f in self.findings:
            byf.setdefault(f.path, []).append(f)
        return byf

    def _plan(self, workdir: str):
        """Compute fixed content per file and record suggest-only/unfixable skips."""
        out, skipped = {}, []
        for rel, fs in self._by_file().items():
            new, _applied, sk = plan_file(_safe_join(workdir, rel), fs)
            out[rel] = new
            skipped.extend(sk)
        self.skipped = skipped
        return out

    def dry_run(self, workdir: str, rule: str) -> str:
        """Reviewable unified diff of the planned detach insertions (no writes)."""
        chunks = []
        for rel, new in self._plan(workdir).items():
            with open(_safe_join(workdir, rel), encoding="utf-8") as fh:
                old = fh.readlines()
            chunks.extend(difflib.unified_diff(
                old, new.splitlines(keepends=True), fromfile=f"a/{rel}", tofile=f"b/{rel}"))
        return "".join(chunks)

    def apply(self, workdir: str, rule: str) -> None:
        """Write the fixes, snapshotting originals first so revert() can roll back."""
        for rel, new in self._plan(workdir).items():
            p = _safe_join(workdir, rel)
            if rel not in self._orig:
                with open(p, encoding="utf-8") as fh:
                    self._orig[rel] = fh.read()
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(new)

    def revert(self, workdir: str) -> None:
        """Restore the snapshotted originals — the wrapper calls this on rejection."""
        for rel, orig in self._orig.items():
            with open(_safe_join(workdir, rel), "w", encoding="utf-8") as fh:
                fh.write(orig)
        self._orig.clear()
