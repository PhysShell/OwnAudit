using System.Collections.Generic;

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

/// One secondary, structured location that explains a finding — a single step in its
/// reachability slice (where a resource was acquired, where a borrow escapes, where the
/// missing release should go, what consumed it). The structured successor to a message
/// that merely *mentions* another site: a place a SARIF consumer can point at. The
/// unordered <see cref="Finding.Evidence"/> rides along as SARIF relatedLocations; the
/// ordered <see cref="Finding.Flow"/> rides as a codeFlows reachability slice (P-015).
public sealed record EvidenceSpan(
    string File,    // target-repo-relative, forward slashes; "" = same file as the finding
    int Line,
    string Label,   // human description of what happens at this step
    string Role = "related"); // related | acquired | released | escaped | consumed | step

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

    /// Unordered secondary locations that explain this finding (acquire site,
    /// missing-release point, consuming ctor) — emitted as SARIF relatedLocations.
    /// Empty for a single-site finding.
    public IReadOnlyList<EvidenceSpan> Evidence { get; init; } = System.Array.Empty<EvidenceSpan>();

    /// The ORDERED reachability slice that leads to this finding (e.g. a DI captive's
    /// singleton -> transient -> scoped retention path) — emitted as a SARIF codeFlows.
    /// Empty when the finding is a single point with no path to show.
    public IReadOnlyList<EvidenceSpan> Flow { get; init; } = System.Array.Empty<EvidenceSpan>();
}
