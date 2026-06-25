"""Risk tiers — the gate that makes mass-apply honest (docs/fix-arm.md §3).

Every finding routes to a tier; the tier decides auto vs review vs unfixable.
The map is intentionally CONSERVATIVE: anything fixable-but-not-known-mechanical
defaults to T2 (apply-then-review), never to unattended auto. Per-rule refinement
(promoting proven-mechanical rules to T1) is a deliberate, reviewed step.
"""

T1 = "T1"  # mechanical / behavior-preserving      -> batch-auto
T2 = "T2"  # semantic / structure-changing          -> apply, diff on review
T3 = "T3"  # detect-only, no fix exists             -> annotate, never "fixed"
T4 = "T4"  # bespoke (ours: OWN rules)              -> suggested patch, always reviewed

# Tools that only DETECT — no CodeFixProvider exists anywhere for their rules.
DETECT_ONLY_TOOLS = frozenset({"codeql", "infersharp"})

# Rules proven mechanical enough for unattended auto-apply (T1). Start tiny and
# grow this list only after a rule's fix is reviewed on real diffs. Everything
# else fixable stays T2. These are Roslynator style/formatting rules.
_T1_RULES = frozenset({
    "RCS1001",  # add braces
    "RCS1003",  # add braces to if-else
    "RCS1037",  # remove trailing whitespace
    "RCS1163",  # unused parameter (rename to _)
    "RCS1207",  # use anonymous method / lambda
})

# Prefix -> tier for the fixable families (docs/fix-arm.md §1 table). Order matters;
# first matching prefix wins, so list the specific ("AsyncFixer") before short ones.
_PREFIX_TIERS = (
    ("OWN", T4),          # own-check: subscription / region-escape — we build the fixer
    ("IDISP", T2),        # IDisposableAnalyzers
    ("INPC", T2),         # PropertyChangedAnalyzers
    ("WPF", T2),          # WpfAnalyzers (freezable)
    ("CA", T2),           # NetAnalyzers
    ("AsyncFixer", T2),
    ("MA", T2),           # Meziantou: mixed; conservative default = review
    ("RCS", T2),          # Roslynator: T2 unless explicitly promoted in _T1_RULES
)


def tier_of(rule: str, tool: str = "") -> str:
    """Tier for a (rule, tool). Detect-only tools and cs/* queries are T3 — no
    applier can fix them, so they are reported as unfixable, never auto-skipped."""
    if tool and tool.lower() in DETECT_ONLY_TOOLS:
        return T3
    r = rule or ""
    if r.startswith("cs/"):           # CodeQL csharp query id form
        return T3
    if r in _T1_RULES:
        return T1
    for prefix, tier in _PREFIX_TIERS:
        if r.startswith(prefix):
            return tier
    # Unknown rule: not detect-only, not in our families. Be conservative — route
    # to review rather than pretend we can auto-fix it.
    return T2


# Gate decision per tier (docs/fix-arm.md §3/§4).
AUTO = "auto-commit"
REVIEW = "queued-for-review"
UNFIXABLE = "unfixable"


def gate_for_tier(tier: str) -> str:
    if tier == T1:
        return AUTO
    if tier == T3:
        return UNFIXABLE
    return REVIEW  # T2, T4
