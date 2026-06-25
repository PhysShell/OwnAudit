"""T4 — the OWN001/OWN014 fixer (docs/fix-arm.md §3/§5). The ONE fixer no
off-the-shelf tool covers: own-check's subscription / region-escape leaks.

It plugs into the same wrapper as every other applier (orchestrate.run_fix), so
it inherits dry-run, the no-new-findings regression gate, and rollback for free.
OWN rules are tier T4 → the wrapper always routes the result to REVIEW; nothing
here auto-commits, because lifetime-correct teardown placement is a judgement call.

Scope — conservative on purpose (T4: refuse rather than emit a wrong patch). For a WPF
owner we hang cleanup on a teardown event (Closed for a Window, Unloaded for a
FrameworkElement). Four shapes are fixed; anything ambiguous is left suggest-only.
  * named-handler subscription — `src.Event += Handler;` →
        `this.<teardown> += (s, e) => src.Event -= Handler;`
  * disposable field — never-disposed IDisposable field (Timer, CTS, …) →
        `this.<teardown> += (s, e) => field?.Dispose();`  (after InitializeComponent())
  * disposable local — a clean `T x = new T(...);` that does NOT escape its block →
        wrap it in a block `using (...) { … }`. Escapes (return/out/ref/store) → refuse.
  * inline-lambda subscription — extract the lambda to a named method, rewrite `+=` to
        the method group, then add the detach. ONLY for well-known events
        (PropertyChanged/ListChanged/CollectionChanged) with a 2-param expression lambda;
        block bodies, unknown delegates, multi-line subscriptions → refuse.
Every refusal is surfaced in `applier.skipped`, never patched with a fake fix.
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
    # bound the search to THIS class — a later class's InitializeComponent() must
    # not anchor the hook in the wrong class (would emit uncompilable code).
    end = _class_close(lines, cls_idx)
    for i in range(cls_idx, end + 1 if end is not None else len(lines)):
        if "InitializeComponent()" in lines[i]:
            return i
    return None


# ---- brace/scope helpers (char-level, ignoring strings + // comments) -------

def _code_skeleton(line: str) -> str:
    """`line` with string/char-literal contents and // comments blanked, so that
    only structural braces survive. Best-effort (no verbatim/interpolated strings),
    but the fixers refuse (suggest-only) whenever a block close can't be matched."""
    out, i, n = [], 0, len(line)
    while i < n:
        c = line[i]
        if c == "/" and i + 1 < n and line[i + 1] == "/":
            break
        if c in "\"'":
            q, i = c, i + 1
            while i < n:
                if line[i] == "\\":
                    i += 2
                    continue
                if line[i] == q:
                    i += 1
                    break
                i += 1
            out.append(" ")
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _enclosing_block_close(lines: list[str], decl_idx: int):
    """Line index of the `}` that closes the block directly containing decl_idx."""
    depth = 0
    for i in range(decl_idx + 1, len(lines)):
        for ch in _code_skeleton(lines[i]):
            if ch == "{":
                depth += 1
            elif ch == "}":
                if depth == 0:
                    return i
                depth -= 1
    return None


def _class_close(lines: list[str], cls_idx: int):
    """Line index of the `}` closing the class whose declaration is at cls_idx."""
    depth, started = 0, False
    for i in range(cls_idx, len(lines)):
        for ch in _code_skeleton(lines[i]):
            if ch == "{":
                depth, started = depth + 1, True
            elif ch == "}":
                depth -= 1
                if started and depth == 0:
                    return i
    return None


# ---- per-shape planners: each returns (edits, detail) or (None, skip_reason) -
# An edit is (start, end, repl_lines): `lines[start:end] = repl_lines` (insert when
# start == end). plan_file applies them bottom-up so indices stay valid.

def _enclosing_class_idx(lines, idx):
    """Line index of the nearest `class X` declaration at or above idx."""
    for i in range(idx, -1, -1):
        if re.search(r"\bclass\s+\w+", lines[i]):
            return i
    return None


def _fold_after_open_brace(lines, decl_idx, end):
    """For a method whose declaration is at decl_idx, return (brace_line, body_indent)
    if it has a clean BLOCK body (its `{` ends a line) — so a statement can be folded
    in right after it. Returns None for one-liner/expression bodies (don't fold)."""
    for i in range(decl_idx, end):
        sk = _code_skeleton(lines[i]).rstrip()
        if sk.endswith("{"):
            return i, re.match(r"\s*", lines[i]).group(0) + "    "
        if "{" in sk or sk.endswith(";") or "=>" in sk:   # one-liner / expr body -> skip
            return None
    return None


def _fold_target(lines, cls_idx, ev):
    """If the class already has a teardown method to fold cleanup into, return its
    block anchor. Today: a `protected override void OnClosed(...)` for ev == Closed —
    it runs exactly when the Window's Closed event would, so folding is equivalent and
    cleaner than stacking another lambda. Only a member-depth OnClosed of THIS class
    counts — a nested type's override (deeper brace depth) must not be folded into."""
    if ev != "Closed":
        return None
    end = _class_close(lines, cls_idx)
    end = end if end is not None else len(lines)
    depth, started = 0, False
    for i in range(cls_idx, end):
        if started and depth == 1 and re.search(r"\boverride\s+void\s+OnClosed\b", lines[i]):
            return _fold_after_open_brace(lines, i, end)
        for ch in _code_skeleton(lines[i]):
            if ch == "{":
                depth, started = depth + 1, True
            elif ch == "}":
                depth -= 1
    return None


_MODIFIER = r"(?:public|private|protected|internal|static|readonly|const|volatile|virtual|override|sealed|new|required)"


def _is_class_member(lines, cls_idx, root):
    """Is `root` a member (field/property) of the class — i.e. in scope inside a method
    body like OnClosed? `this` always is. Members carry an access/field modifier;
    constructor parameters and locals do not, so requiring a modifier separates them.
    Used to keep the fold sound: a ctor-local source must stay on the captured lambda."""
    if root == "this":
        return True
    end = _class_close(lines, cls_idx)
    end = end if end is not None else len(lines)
    decl = re.compile(rf"^\s*(\[[^\]]*\]\s*)?({_MODIFIER}\s+)+[\w<>\[\].,\s]*?\b{re.escape(root)}\b\s*(=|;|\{{|=>)")
    return any(decl.match(_code_skeleton(lines[i])) for i in range(cls_idx, end))


def _plan_teardown(lines, f, idx, stmt, anchor_missing="site-not-found", fold_root=None):
    """Subscription / disposable-field: run `stmt` on the owner's teardown. Folds into
    an existing OnClosed override when present AND the source is a class member (so it
    stays in scope there); otherwise adds a fresh teardown lambda at the call site,
    which captures whatever is in scope (incl. ctor locals). fold_root=None ⇒ always
    foldable (a disposable field is a member by construction)."""
    if idx is None:
        return None, anchor_missing
    if _in_unbraced_control_flow(lines, idx):
        return None, "unbraced-control-flow"
    _, decl = _enclosing_class(lines, idx)
    ev = _teardown_event(decl)
    if ev is None:
        return None, "no-safe-teardown"
    cls_idx = _enclosing_class_idx(lines, idx)
    fold = _fold_target(lines, cls_idx, ev) if cls_idx is not None else None
    if fold is not None and (fold_root is None or _is_class_member(lines, cls_idx, fold_root)):
        brace_idx, body_indent = fold
        return [(brace_idx + 1, brace_idx + 1, [f"{body_indent}{stmt};\n"])], f"{ev}/fold"
    indent = re.match(r"\s*", lines[idx]).group(0)
    hook = f"{indent}this.{ev} += (s, e) => {stmt};\n"
    return [(idx + 1, idx + 1, [hook])], ev


_LOCAL_NEW = r"^(\s*)((?:var|[A-Za-z_][\w.<>\[\]]*)\s+{name}\s*=\s*new\b[^;{{}}]*);\s*$"


def _plan_local(lines, f, name):
    """Disposable local: wrap a clean `T x = new T(...);` in a block `using`, but only
    when the local clearly doesn't escape its block (no return/out/ref/store of it)."""
    rx = re.compile(_LOCAL_NEW.format(name=re.escape(name)))
    target = f.line - 1
    hit = None
    for cand in [target] + [target + d for d in (1, -1, 2, -2, 3, -3)]:
        if 0 <= cand < len(lines):
            m = rx.match(lines[cand])
            if m:
                hit = (cand, m.group(1), m.group(2))
                break
    if hit is None:
        return None, "decl-not-simple-new"          # object initializers, multi-line, etc.
    idx, indent, core = hit
    close = _enclosing_block_close(lines, idx)
    if close is None:
        return None, "no-block-close"
    region = "".join(_code_skeleton(line) for line in lines[idx + 1:close])
    nm = re.escape(name)
    if (re.search(rf"\breturn\b[^;]*\b{nm}\b", region)         # returned
            or re.search(rf"\b(out|ref)\s+{nm}\b", region)      # passed out/ref
            or re.search(rf"=\s*{nm}\s*[;,)]", region)          # stored elsewhere
            or re.search(rf"[(,]\s*{nm}\s*[),]", region)        # passed as a call arg (may be retained)
            or "=>" in region                                   # a closure here may capture + outlive it
            or "yield" in region):
        return None, "local-escapes"                # disposing here would be use-after-dispose
    edits = [
        (idx, idx + 1, [f"{indent}using ({core})\n", f"{indent}{{\n"]),
        (close, close, [f"{indent}}}\n"]),
    ]
    return edits, "using"


# Events whose delegate's EventArgs type is UNAMBIGUOUS without a compiler — the
# INotify* family. Names like Click/TextChanged are deliberately excluded: the same
# name maps to different delegates across frameworks (RoutedEventArgs vs EventArgs),
# so extracting them blindly could emit a wrong signature → they stay suggest-only.
_EVENT_ARGS = {
    # fully qualified: the extracted method names the type explicitly, so it must
    # compile even if the file's lambda relied on type inference without the using.
    "PropertyChanged": "System.ComponentModel.PropertyChangedEventArgs",
    "PropertyChanging": "System.ComponentModel.PropertyChangingEventArgs",
    "ListChanged": "System.ComponentModel.ListChangedEventArgs",
    "CollectionChanged": "System.Collections.Specialized.NotifyCollectionChangedEventArgs",
    "ErrorsChanged": "System.ComponentModel.DataErrorsChangedEventArgs",
}
_LAMBDA2 = re.compile(r"^\(\s*(\w+)\s*,\s*(\w+)\s*\)\s*=>\s*(.+?)\s*$")


def _ident_exists(lines, name):
    rx = re.compile(rf"\b{re.escape(name)}\b")
    return any(rx.search(_code_skeleton(line)) for line in lines)


def _plan_lambda(lines, f, src_event, handler):
    """Inline-lambda subscription: extract the lambda to a named method, rewrite the
    `+=` to the method group, and add the teardown detach. Only for well-known events
    (known delegate args) with a two-param expression lambda — else suggest-only."""
    args_type = _EVENT_ARGS.get(src_event.rsplit(".", 1)[-1])
    if args_type is None:
        return None, "unknown-event-delegate"
    m = _LAMBDA2.match(handler.strip())
    if not m:
        return None, "lambda-shape-unsupported"      # arity != 2
    p1, p2, expr = m.group(1), m.group(2), m.group(3)
    if "{" in expr or ";" in expr:
        return None, "lambda-shape-unsupported"      # block body
    idx = _find_sub_line(lines, f.line, src_event)
    if idx is None:
        return None, "site-not-found"
    if not lines[idx].rstrip().endswith(";"):
        return None, "multiline-subscription"
    if _in_unbraced_control_flow(lines, idx):
        return None, "unbraced-control-flow"
    cls_idx = next((i for i in range(idx, -1, -1) if re.search(r"\bclass\s+\w+", lines[i])), None)
    if cls_idx is None:
        return None, "no-class"
    _, decl = _enclosing_class(lines, idx)
    ev = _teardown_event(decl)
    if ev is None:
        return None, "no-safe-teardown"
    close = _class_close(lines, cls_idx)
    if close is None:
        return None, "no-class-close"
    name = "On" + "".join(w[:1].upper() + w[1:] for w in re.split(r"\W+", src_event) if w)
    base, n = name, 2
    while _ident_exists(lines, name):
        name, n = f"{base}{n}", n + 1
    indent = re.match(r"\s*", lines[idx]).group(0)
    mindent = re.match(r"\s*", lines[cls_idx]).group(0) + "    "
    method = ["\n", f"{mindent}private void {name}(object {p1}, {args_type} {p2}) => {expr};\n"]
    edits = [
        (idx, idx + 1, [f"{indent}{src_event} += {name};\n"]),
        (idx + 1, idx + 1, [f"{indent}this.{ev} += (s, e) => {src_event} -= {name};\n"]),
        (close, close, method),
    ]
    return edits, "extract+detach"


def _plan_one(lines, f):
    """Dispatch a finding to its shape's planner."""
    shape, a, b = classify(f.message)
    if shape == NAMED_HANDLER_SUB:
        return _plan_teardown(lines, f, _find_sub_line(lines, f.line, a), f"{a} -= {b}",
                              fold_root=a.split(".")[0])   # source's root must be in scope to fold
    if shape == DISPOSABLE_FIELD:
        return _plan_teardown(lines, f, _find_ctor_anchor(lines, f.line),
                              f"{a}?.Dispose()", anchor_missing="no-ctor-anchor")
    if shape == DISPOSABLE_LOCAL:
        return _plan_local(lines, f, a)
    if shape == INLINE_LAMBDA_SUB:
        return _plan_lambda(lines, f, a, b)
    return None, shape                               # OTHER


def plan_file(path: str, findings):
    """Compute (new_content, applied, skipped) for one file. `applied`/`skipped`
    are (finding, detail) lists so the ledger reports exactly what was and wasn't
    fixed — no silent drops (docs/fix-arm.md §8)."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    planned, applied, skipped = [], [], []
    seen: set = set()        # identical edit-sets -> duplicate-site
    replaced: set = set()    # original line indices a REPLACEMENT consumes
    inserted_at: set = set() # anchors used by INSERTIONS (several may share one anchor)
    for f in findings:
        edits, detail = _plan_one(lines, f)
        if edits is None:
            skipped.append((f, detail))
            continue
        key = tuple((s, e, tuple(r)) for s, e, r in edits)
        if key in seen:
            skipped.append((f, "duplicate-site"))   # same fix already planned
            continue
        f_repl, f_ins = set(), set()
        for s, e, _ in edits:
            if e > s:
                f_repl.update(range(s, e))
            else:
                f_ins.add(s)
        # Replacements must not overlap anything; insertions may share an anchor with
        # other insertions (e.g. two disposable fields after one InitializeComponent())
        # but must not land inside a replaced range.
        if (f_repl & replaced) or (f_repl & inserted_at) or (f_ins & replaced):
            skipped.append((f, "overlapping-edit"))
            continue
        seen.add(key)
        replaced |= f_repl
        inserted_at |= f_ins
        planned.append(edits)
        applied.append((f, detail))
    # apply every edit bottom-up so earlier line indices stay valid
    for s, e, repl in sorted((ed for edits in planned for ed in edits),
                             key=lambda t: t[0], reverse=True):
        lines[s:e] = repl
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
