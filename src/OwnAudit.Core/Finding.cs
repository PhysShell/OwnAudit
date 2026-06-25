namespace OwnAudit.Core;

/// The family of resource/lifetime problem a finding belongs to. Drives ranking:
/// leak classes outrank generic quality findings, and subscription/timer leaks
/// (the dominant WPF retainers) outrank the rest.
public enum LeakClass
{
    Subscription, // event / Rx / WhenAnyValue handler never detached (#1 WPF retainer)
    Timer,        // DispatcherTimer / Timers.Timer never stopped
    Dispose,      // IDisposable not disposed, or used-after-dispose
    Pool,         // ArrayPool / MemoryPool buffer not returned, or used-after-return
    Async,        // async-lifetime smell
    Quality,      // general best-practice / correctness (no direct leak)
    Unknown
}

public enum Severity { Error, Warning, Note }

/// One normalized finding from any static tool (OwnSharp or a Roslyn analyzer),
/// reduced to a single site so findings from different tools at the same place can
/// be merged and counted (see <see cref="Corroboration"/>).
public sealed record Finding(
    string Tool,        // "ownsharp" | "idisposable-analyzers" | "wpf-analyzers" | ...
    string RuleId,      // "OWN002", "CA2000", "IDISP001", ...
    LeakClass LeakClass,
    Severity Severity,
    string File,        // target-repo-relative, forward slashes
    int? Line,
    string? Symbol,
    string Message)
{
    /// Number of DISTINCT tools that independently flagged this site. The normalizer
    /// sets it when it merges OwnSharp + analyzer findings; corroboration boosts rank.
    public int Corroboration { get; init; } = 1;

    /// Computed rank score (set by the ranker). Higher = more worth a human look and
    /// a runtime proof in Arm 2. See PLAN.md "Ranking".
    public double Rank { get; init; }
}
