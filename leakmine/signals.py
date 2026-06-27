"""Patch-signal classifier + query packs — the cheap, deterministic first filter.

Before any LLM and before any tool run, a fix patch is scored by what it *adds* and
*removes*. A fix that adds `removeEventListener` / `-=` / `clearInterval` / `Dispose()`
on top of a leak-keyword title is almost certainly a lifetime fix, and we can say so for
free. This module is the "+3 title / +4 patch / +2 file" scorer from the plan, made
concrete and per-ecosystem.

The output is two things the rest of the pipeline consumes:
  - a `category` (the OwnAudit taxonomy: subscription-leak, idisposable-leak, …) so the
    corpus is sliced the same way `report/sarif.py` slices live findings;
  - a `score` + `evidence` so candidates can be ranked and the borderline ones sent to
    manual / LLM review instead of being trusted blindly.

Query packs live here too (as plain Python data — no YAML in stdlib): each ecosystem
carries its GitHub-search strings, changed-file extensions, and the patch signals that
map added/removed text to a category.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import diffparse

# Canonical leak categories — kept in lockstep with report/sarif.py's _LEVEL_BY_CATEGORY
# so a mined fix and a live finding share one taxonomy.
SUBSCRIPTION = "subscription-leak"
IDISPOSABLE = "idisposable-leak"
TIMER = "timer-leak"
TASK = "task-coroutine-leak"
DI_SCOPE = "di-scope-leak"
STATIC_RETENTION = "static-cache-retention"
UI_RETENTION = "ui-resource-retention"
UNKNOWN = "uncategorized"


@dataclass
class Signal:
    """One added/removed-text fingerprint mapping to a category, with a weight."""
    category: str
    added: tuple[str, ...] = ()       # substrings that should appear in ADDED lines
    removed: tuple[str, ...] = ()     # substrings that should appear in REMOVED lines
    weight: int = 4


@dataclass
class Ecosystem:
    key: str
    file_ext: tuple[str, ...]
    queries: tuple[str, ...]
    signals: tuple[Signal, ...]
    # keywords that, in a title/body, suggest a lifetime fix at all.
    keywords: tuple[str, ...] = (
        "memory leak", "leak", "leaks", "retain", "retained", "not disposed",
        "not released", "never released", "grows unbounded", "oom", "out of memory",
    )


# ---- ecosystem query packs -------------------------------------------------------

DOTNET_WPF = Ecosystem(
    key="dotnet_wpf",
    file_ext=(".cs", ".xaml", ".xaml.cs"),
    queries=(
        '"memory leak" WPF is:pr is:merged language:C#',
        '"event handler leak" C# is:pr is:merged',
        '"DispatcherTimer" "Stop" is:pr is:merged language:C#',
        '"DataContext" "memory leak" is:issue is:closed',
        '"ResourceDictionary" memory is:issue is:closed',
        '"weak event" leak is:pr is:merged language:C#',
        '"IDisposable" "Dispose" leak is:pr is:merged language:C#',
    ),
    signals=(
        Signal(SUBSCRIPTION, removed=("+=",), added=("-=",), weight=5),
        Signal(SUBSCRIPTION, added=("Unloaded", "-="), weight=4),
        Signal(SUBSCRIPTION, added=("WeakEventManager",), weight=4),
        Signal(TIMER, added=("Stop()",), weight=4),
        Signal(TIMER, added=("DispatcherTimer", "Stop"), weight=3),
        Signal(IDISPOSABLE, added=("using ",), weight=3),
        Signal(IDISPOSABLE, added=(".Dispose()",), weight=4),
        Signal(IDISPOSABLE, added=("await using",), weight=4),
        Signal(DI_SCOPE, added=("CreateScope", "Dispose"), weight=3),
        Signal(STATIC_RETENTION, added=("WeakReference",), weight=3),
        Signal(UI_RETENTION, added=("StaticResource",), removed=("DynamicResource",), weight=3),
        Signal(UI_RETENTION, added=("ResourceDictionary",), weight=2),
    ),
)

REACT_TS = Ecosystem(
    key="react_ts",
    file_ext=(".ts", ".tsx", ".js", ".jsx"),
    queries=(
        '"useEffect" "memory leak" is:pr is:merged',
        '"addEventListener" "removeEventListener" is:pr is:merged language:TypeScript',
        '"setInterval" "clearInterval" is:pr is:merged language:TypeScript',
        '"AbortController" leak is:pr is:merged',
        '"unsubscribe" "memory leak" is:pr is:merged language:TypeScript',
        '"cleanup" useEffect leak is:pr is:merged',
    ),
    signals=(
        Signal(SUBSCRIPTION, added=("removeEventListener",), weight=5),
        Signal(SUBSCRIPTION, added=(".unsubscribe(",), weight=5),
        Signal(SUBSCRIPTION, added=("return () =>",), weight=3),  # effect cleanup added
        Signal(TIMER, added=("clearInterval",), weight=5),
        Signal(TIMER, added=("clearTimeout",), weight=4),
        Signal(TASK, added=("AbortController",), weight=4),
        Signal(TASK, added=(".abort()",), weight=4),
        # effect-storm fixes add EITHER memo helper — keep them as independent signals so
        # one alone still scores (a combined ("useMemo","useCallback") tuple is AND-matched).
        Signal(SUBSCRIPTION, added=("useMemo",), weight=2),
        Signal(SUBSCRIPTION, added=("useCallback",), weight=2),
    ),
)

ANDROID_KOTLIN = Ecosystem(
    key="android_kotlin",
    file_ext=(".kt", ".java", ".xml"),
    queries=(
        '"Fragment" "memory leak" Android is:pr is:merged language:Kotlin',
        '"unregisterReceiver" is:pr is:merged language:Kotlin',
        '"viewLifecycleOwner" leak is:pr is:merged',
        '"lifecycleScope" GlobalScope is:pr is:merged language:Kotlin',
        '"job.cancel" leak is:pr is:merged language:Kotlin',
    ),
    signals=(
        Signal(SUBSCRIPTION, added=("removeListener",), weight=4),
        Signal(SUBSCRIPTION, added=("unregisterReceiver",), weight=5),
        Signal(TASK, added=(".cancel()",), weight=4),
        Signal(TASK, added=("viewLifecycleOwner",), weight=3),
        Signal(TASK, added=("lifecycleScope",), removed=("GlobalScope",), weight=5),
        Signal(UI_RETENTION, added=("onDestroyView",), weight=3),
    ),
)

JAVA_SPRING = Ecosystem(
    key="java_spring",
    file_ext=(".java",),
    queries=(
        '"ThreadLocal" "memory leak" is:pr is:merged language:Java',
        '"ExecutorService" shutdown leak is:pr is:merged language:Java',
        '"Closeable" leak is:pr is:merged language:Java',
        '"try-with-resources" leak is:pr is:merged language:Java',
    ),
    signals=(
        Signal(IDISPOSABLE, added=("try (",), weight=4),         # try-with-resources
        Signal(IDISPOSABLE, added=(".close()",), weight=4),
        # most executor leak fixes add ONE of these, not both — independent signals so a
        # single-form cleanup still clears the candidate threshold.
        Signal(TASK, added=(".shutdown()",), weight=4),
        Signal(TASK, added=(".shutdownNow()",), weight=4),
        Signal(STATIC_RETENTION, added=(".remove()",), removed=("ThreadLocal",), weight=3),
        Signal(STATIC_RETENTION, added=("ThreadLocal", "remove"), weight=3),
    ),
)

# "Novel languages" appendix — small samples, proves OwnIR carries to RC/allocator worlds.
ZIG = Ecosystem(
    key="zig",
    file_ext=(".zig",),
    queries=('"memory leak" is:pr is:merged language:Zig', 'defer free is:pr is:merged language:Zig'),
    signals=(
        Signal(IDISPOSABLE, added=("defer ", ".free("), weight=5),
        Signal(IDISPOSABLE, added=("errdefer",), weight=5),
        Signal(IDISPOSABLE, added=(".deinit()",), weight=4),
        Signal(IDISPOSABLE, added=("arena.deinit",), weight=4),
    ),
)

NIM = Ecosystem(
    key="nim",
    file_ext=(".nim",),
    queries=('"memory leak" is:pr is:merged language:Nim', '"--mm:orc" cycle is:pr is:merged'),
    signals=(
        Signal(STATIC_RETENTION, added=("--mm:orc",), removed=("--mm:arc",), weight=5),
        Signal(IDISPOSABLE, added=(".close()", "=destroy"), weight=3),
        Signal(STATIC_RETENTION, added=("= nil",), weight=2),  # break ref cycle
    ),
)

ECOSYSTEMS: dict[str, Ecosystem] = {
    e.key: e for e in (DOTNET_WPF, REACT_TS, ANDROID_KOTLIN, JAVA_SPRING, ZIG, NIM)
}


@dataclass
class Classification:
    category: str
    score: int
    evidence: list[str] = field(default_factory=list)
    # per-category breakdown for transparency / multi-label inspection.
    by_category: dict[str, int] = field(default_factory=dict)

    @property
    def is_candidate(self) -> bool:
        return self.score >= 7      # plan threshold: >=7 candidate, >=10 likely fix

    @property
    def is_likely_fix(self) -> bool:
        return self.score >= 10


def _matches(text_lines: list[str], needles: tuple[str, ...]) -> bool:
    """All needles must each appear in at least one of the lines."""
    if not needles:
        return True
    joined = "\n".join(text_lines)
    return all(n in joined for n in needles)


def classify(
    eco_key: str,
    *,
    title: str = "",
    body: str = "",
    patch: str = "",
) -> Classification:
    """Score a candidate fix the way the plan prescribes (§10):
        +3 leak keyword in title, +2 in body
        +weight per matched patch signal (the real evidence)
        +2 a changed file has a relevant extension
        -3 only docs changed, -4 only a dependency bump
    Returns the best-scoring category plus the full per-category breakdown.
    """
    eco = ECOSYSTEMS[eco_key]
    score = 0
    evidence: list[str] = []
    by_cat: dict[str, int] = {}

    tl, bl = title.lower(), body.lower()
    if any(k in tl for k in eco.keywords):
        score += 3
        evidence.append("title:leak-keyword")
    if any(k in bl for k in eco.keywords):
        score += 2
        evidence.append("body:leak-keyword")

    added = diffparse.added_text(patch)
    removed = diffparse.removed_text(patch)
    paths = diffparse.changed_paths(patch)

    for sig in eco.signals:
        if _matches(added, sig.added) and _matches(removed, sig.removed):
            score += sig.weight
            by_cat[sig.category] = by_cat.get(sig.category, 0) + sig.weight
            tag = sig.category
            shown = (sig.added or sig.removed)
            evidence.append(f"patch:{tag}:{'+'.join(shown) if shown else '*'}")

    if any(p.endswith(eco.file_ext) for p in paths):
        score += 2
        evidence.append("file:relevant-ext")

    # penalties — docs-only / dependency bumps masquerading as fixes.
    code_paths = [p for p in paths if p.endswith(eco.file_ext)]
    if paths and not code_paths and all(
        p.endswith((".md", ".rst", ".txt")) for p in paths
    ):
        score -= 3
        evidence.append("penalty:docs-only")
    if any(p.endswith(("package.json", "package-lock.json", "yarn.lock",
                        ".csproj", "packages.lock.json")) for p in paths) and not code_paths:
        score -= 4
        evidence.append("penalty:dependency-bump")

    category = max(by_cat, key=by_cat.get) if by_cat else UNKNOWN
    return Classification(category=category, score=score, evidence=evidence, by_category=by_cat)
