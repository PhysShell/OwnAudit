using Microsoft.Diagnostics.Runtime;

namespace OwnAudit.Runtime;

/// Whole-heap census vs the root-reachable subset — the "is it even a leak" gate
/// (docs/collector-plan.md D7). Reachable ≈ heap → genuinely retained; reachable ≪ heap
/// → the GC simply has not collected yet.
public sealed record HeapStats(
    long Objects, long Bytes, long ReachableObjects, long ReachableBytes, int RootCount);

/// One root→object retention path. Hops are type names from the GC root (index 0,
/// prefixed with its root kind, e.g. "[Pinned] System.Object[]") down to the suspect.
public sealed record RetentionChain(IReadOnlyList<string> Hops);

/// A classified GC root (docs/runtime-contract.md `roots[]`, docs/collector-plan.md D4):
/// what kind of thing pins the suspect, who owns it and through which member.
///  • static-event — a delegate reachable from a static/pinned handle; Holder = the type
///    owning the delegate field, Member = that field (the smoking gun for OWN001);
///  • timer — the chain runs through the runtime's TimerQueue;
///  • static-field — a static/pinned handle holds the suspect with no delegate involved;
///  • other — anything else, with the verbatim chain for a human to read.
public sealed record ClassifiedRoot(
    string Kind, string? Holder, string? Member, string Via, RetentionChain Chain);

/// A suspect type's retention evidence: how many instances are reachable from GC roots
/// (not merely on the heap), sample chains proving who holds them, and the classified
/// root per chain.
public sealed record RetainedType(
    string Type, int Count, long Bytes, IReadOnlyList<RetentionChain> Chains,
    IReadOnlyList<ClassifiedRoot> Roots);

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
        using var target = DataTarget.AttachToProcess(pid, suspend: true);
        var clrInfo = target.ClrVersions.FirstOrDefault()
            ?? throw new InvalidOperationException($"no CLR found in process {pid} — is it managed?");
        using var runtime = clrInfo.CreateRuntime();
        var heap = runtime.Heap;

        // 1. Whole-heap census. EnumerateObjects walks the segments linearly and returns
        //    everything allocated, INCLUDING garbage the GC has not collected yet — so this
        //    number alone proves nothing; it is the denominator of the reachability gate.
        long heapObjs = 0, heapBytes = 0;
        foreach (var o in heap.EnumerateObjects())
        {
            if (!o.IsValid || o.Type is null) continue;
            heapObjs++;
            heapBytes += (long)o.Size;
        }

        // 2. Mark from the GC roots, breadth-first, recording each object's predecessor —
        //    one traversal yields the retained census AND shortest root→suspect chains.
        var wanted = new HashSet<string>(suspectTypes, StringComparer.Ordinal);
        var pred = new Dictionary<ulong, ulong>();      // child -> parent; 0 marks a root object
        var rootKind = new Dictionary<ulong, string>(); // root object -> its GC-root kind
        var queue = new Queue<ulong>();
        foreach (var root in heap.EnumerateRoots())
        {
            var o = root.Object;
            if (!o.IsValid || pred.ContainsKey(o.Address)) continue;
            pred[o.Address] = 0;
            rootKind[o.Address] = root.RootKind.ToString();
            queue.Enqueue(o.Address);
        }
        var rootCount = queue.Count;

        long liveObjs = 0, liveBytes = 0;
        var counts = suspectTypes.ToDictionary(t => t, _ => 0, StringComparer.Ordinal);
        var sizes = suspectTypes.ToDictionary(t => t, _ => 0L, StringComparer.Ordinal);
        var samples = suspectTypes.ToDictionary(t => t, _ => new List<ulong>(), StringComparer.Ordinal);

        while (queue.Count > 0)
        {
            var addr = queue.Dequeue();
            var obj = heap.GetObject(addr);
            if (!obj.IsValid || obj.Type is null) continue;
            liveObjs++;
            liveBytes += (long)obj.Size;

            var name = obj.Type.Name;
            if (name is not null && wanted.Contains(name))
            {
                counts[name]++;
                sizes[name] += (long)obj.Size;
                var s = samples[name];
                if (s.Count < maxChainsPerType) s.Add(addr);
            }

            foreach (var child in obj.EnumerateReferences())
            {
                if (!child.IsValid || pred.ContainsKey(child.Address)) continue;
                pred[child.Address] = addr;
                queue.Enqueue(child.Address);
            }
        }

        // 3. Reconstruct the sampled chains by walking predecessors back to a root.
        var retained = new List<RetainedType>(suspectTypes.Count);
        foreach (var type in suspectTypes)
        {
            var chains = new List<RetentionChain>(samples[type].Count);
            foreach (var suspect in samples[type])
            {
                var hops = new List<string>();
                for (var cur = suspect; cur != 0; cur = pred[cur])
                {
                    var name = heap.GetObject(cur).Type?.Name ?? "?";
                    hops.Add(pred[cur] == 0 ? $"[{rootKind[cur]}] {name}" : name);
                }
                hops.Reverse();
                chains.Add(new RetentionChain(hops));
            }
            retained.Add(new RetainedType(type, counts[type], sizes[type], chains,
                Array.Empty<ClassifiedRoot>()));
        }

        return new CollectionResult(
            new HeapStats(heapObjs, heapBytes, liveObjs, liveBytes, rootCount), retained);
    }
}
