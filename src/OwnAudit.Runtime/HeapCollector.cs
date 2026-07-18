namespace OwnAudit.Runtime;

/// Whole-heap census vs the root-reachable subset — the "is it even a leak" gate
/// (docs/collector-plan.md D7). Reachable ≈ heap → genuinely retained; reachable ≪ heap
/// → the GC simply has not collected yet.
public sealed record HeapStats(
    long Objects, long Bytes, long ReachableObjects, long ReachableBytes, int RootCount);

/// One root→object retention path. Hops are type names from the GC root (index 0,
/// prefixed with its root kind, e.g. "[Pinned] System.Object[]") down to the suspect.
public sealed record RetentionChain(IReadOnlyList<string> Hops);

/// A suspect type's retention evidence: how many instances are reachable from GC roots
/// (not merely on the heap) and sample chains proving who holds them.
public sealed record RetainedType(
    string Type, int Count, long Bytes, IReadOnlyList<RetentionChain> Chains);

public sealed record CollectionResult(HeapStats HeapStats, IReadOnlyList<RetainedType> Retained);

/// The stand-side heap collector (docs/collector-plan.md, port of broker/stackpeek):
/// live-attaches to a process AFTER a scenario ran (suspend, no dumps), marks the heap
/// from the GC roots, counts reachable instances of the suspect types, and walks sample
/// root→object chains for each. Suspect names match exactly (full type name) so that
/// e.g. FixedWatchlistViewModel never counts as WatchlistViewModel.
public sealed class HeapCollector
{
    public CollectionResult Collect(int pid, IReadOnlyList<string> suspectTypes, int maxChainsPerType = 3)
    {
        throw new NotImplementedException("collector-plan.md step 2: port the stackpeek core");
    }
}
