namespace OwnAudit.Runtime;

/// Derives the collector's suspect-type list from a static `findings.json`
/// (docs/collector-plan.md D5) with the same heuristics `runtime/correlate.py` uses to
/// match findings back to retained types: the `resource` when it is a plausible type
/// identifier (no spaces), plus the source-file stem — own-check puts a *description*
/// in `resource`, but the code-behind file is named for its owning class. Only findings
/// in leak categories participate; the result is usually SHORT type names, which the
/// collector matches against the last segment of a full CLR name.
public static class SuspectTypes
{
    public static readonly IReadOnlyList<string> LeakCategories =
        new[] { "subscription-leak", "idisposable-leak", "region-escape" };

    public static IReadOnlyList<string> FromFindingsJson(string path)
    {
        throw new NotImplementedException("collector-plan.md step 5: derive suspects from findings.json");
    }
}
