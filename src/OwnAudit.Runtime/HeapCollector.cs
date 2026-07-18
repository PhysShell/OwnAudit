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
        using var target = Attach(pid);
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
        //    Non-stack roots are drained to exhaustion FIRST: a suspect reachable both from
        //    a static handle and from a live stack slot must be attributed to the static —
        //    that is what still pins it after the current frame returns (and what a
        //    production leak looks like); a stack root is only the truth of last resort.
        // Full-name suspects match exactly; dotless suspects (findings.json file stems)
        // match the last segment of the full CLR name — exactly there too, so
        // FixedWatchlistViewModel never folds into WatchlistViewModel.
        var wantedFull = new HashSet<string>(suspectTypes.Where(t => t.Contains('.')), StringComparer.Ordinal);
        var wantedShort = new HashSet<string>(suspectTypes.Where(t => !t.Contains('.')), StringComparer.Ordinal);
        string? MatchSuspect(string name)
        {
            if (wantedFull.Contains(name)) return name;
            var last = LastSegment(name);
            return wantedShort.Contains(last) ? last : null;
        }

        var pred = new Dictionary<ulong, ulong>();      // child -> parent; 0 marks a root object
        var rootKind = new Dictionary<ulong, string>(); // root object -> its GC-root kind
        var queue = new Queue<ulong>();
        var stackRoots = new List<(ulong Addr, string Kind)>();
        foreach (var root in heap.EnumerateRoots())
        {
            var o = root.Object;
            if (!o.IsValid) continue;
            if (root.RootKind == ClrRootKind.Stack)
            {
                stackRoots.Add((o.Address, root.RootKind.ToString()));
                continue;
            }
            if (pred.ContainsKey(o.Address)) continue;
            pred[o.Address] = 0;
            rootKind[o.Address] = root.RootKind.ToString();
            queue.Enqueue(o.Address);
        }
        var rootCount = queue.Count;

        long liveObjs = 0, liveBytes = 0;
        var counts = suspectTypes.ToDictionary(t => t, _ => 0, StringComparer.Ordinal);
        var sizes = suspectTypes.ToDictionary(t => t, _ => 0L, StringComparer.Ordinal);
        var samples = suspectTypes.ToDictionary(t => t, _ => new List<ulong>(), StringComparer.Ordinal);

        void Drain()
        {
            while (queue.Count > 0)
            {
                var addr = queue.Dequeue();
                var obj = heap.GetObject(addr);
                if (!obj.IsValid || obj.Type is null) continue;
                liveObjs++;
                liveBytes += (long)obj.Size;

                var key = obj.Type.Name is { } name ? MatchSuspect(name) : null;
                if (key is not null)
                {
                    counts[key]++;
                    sizes[key] += (long)obj.Size;
                    var s = samples[key];
                    if (s.Count < maxChainsPerType) s.Add(addr);
                }

                foreach (var child in obj.EnumerateReferences())
                {
                    if (!child.IsValid || pred.ContainsKey(child.Address)) continue;
                    pred[child.Address] = addr;
                    queue.Enqueue(child.Address);
                }
            }
        }

        Drain();
        foreach (var (addr, kind) in stackRoots)
        {
            if (pred.ContainsKey(addr)) continue;
            pred[addr] = 0;
            rootKind[addr] = kind;
            queue.Enqueue(addr);
            rootCount++;
        }
        Drain();

        // 3. Reconstruct the sampled chains root→suspect (with the field on every
        //    parent→child edge) and classify what pins each suspect (collector-plan.md D4).
        var retained = new List<RetainedType>(suspectTypes.Count);
        foreach (var type in suspectTypes)
        {
            var chains = new List<RetentionChain>(samples[type].Count);
            var roots = new List<ClassifiedRoot>(samples[type].Count);
            foreach (var suspect in samples[type])
            {
                var addrs = new List<ulong>();
                for (var cur = suspect; cur != 0; cur = pred[cur])
                    addrs.Add(cur);
                addrs.Reverse();

                var hops = new List<ChainHop>(addrs.Count);
                var labels = new List<string>(addrs.Count);
                for (var i = 0; i < addrs.Count; i++)
                {
                    var obj = heap.GetObject(addrs[i]);
                    var name = obj.Type?.Name ?? "?";
                    var field = i == 0 ? null : FieldFor(heap.GetObject(addrs[i - 1]), addrs[i]);
                    hops.Add(new ChainHop(name, field, IsDelegateType(obj.Type)));
                    labels.Add(i == 0 ? $"[{rootKind[addrs[i]]}] {name}" : name);
                }

                var chain = new RetentionChain(labels);
                chains.Add(chain);
                roots.Add(Classify(rootKind[addrs[0]], hops, chain));
            }
            retained.Add(new RetainedType(type, counts[type], sizes[type], chains, roots));
        }

        return new CollectionResult(
            new HeapStats(heapObjs, heapBytes, liveObjs, liveBytes, rootCount), retained);
    }

    /// Hosted CI runners occasionally refuse the first attach (docs/collector-plan.md D9);
    /// three attempts with a settle delay, then let the real exception through.
    private static DataTarget Attach(int pid)
    {
        for (var attempt = 1; ; attempt++)
        {
            try
            {
                return DataTarget.AttachToProcess(pid, suspend: true);
            }
            catch when (attempt < 3)
            {
                Thread.Sleep(2000);
            }
        }
    }

    private sealed record ChainHop(string Type, string? FieldFromParent, bool IsDelegate);

    /// Which of `parent`'s reference fields holds `childAddr`? Names the edge — for the
    /// holder→delegate edge this is the event's backing field, i.e. the OWN001 member.
    private static string? FieldFor(ClrObject parent, ulong childAddr)
    {
        foreach (var reference in parent.EnumerateReferencesWithFields(carefully: true))
            if (reference.Object.Address == childAddr)
                return reference.Field?.Name;
        return null;
    }

    /// Last segment of a full CLR name, generic arguments kept out of the scope split:
    /// "A.B.Type" -> "Type"; "System.EventHandler&lt;System.String&gt;" stays one segment.
    private static string LastSegment(string name)
    {
        var generic = name.IndexOf('<');
        var scope = generic >= 0 ? name[..generic] : name;
        var dot = scope.LastIndexOf('.');
        return dot >= 0 ? name[(dot + 1)..] : name;
    }

    private static bool IsDelegateType(ClrType? type)
    {
        for (var t = type; t is not null; t = t.BaseType)
            if (t.Name == "System.MulticastDelegate")
                return true;
        return false;
    }

    private static ClassifiedRoot Classify(string rootKindName, IReadOnlyList<ChainHop> hops, RetentionChain chain)
    {
        // Statics live in pinned/strong handle tables; a Stack root is a live local, not a leak shape.
        var staticRoot = rootKindName is "PinnedHandle" or "StrongHandle" or "StrongPinnedHandle";

        // Timer first: a TimerQueue chain also contains the callback delegate, and the
        // queue — not the delegate's owner — is what actually pins the suspect.
        if (hops.Any(h => h.Type.StartsWith("System.Threading.TimerQueue", StringComparison.Ordinal)))
            return new ClassifiedRoot("timer", "System.Threading.TimerQueue", null, "timer-callback", chain);

        var delegateIdx = -1;
        for (var i = 0; i < hops.Count; i++)
            if (hops[i].IsDelegate) { delegateIdx = i; break; }
        if (delegateIdx > 0)
        {
            // The holder is the nearest non-infrastructure hop above the delegate (skip
            // multicast invocation lists and nested delegates).
            var holderIdx = delegateIdx - 1;
            while (holderIdx >= 0 && (hops[holderIdx].IsDelegate || hops[holderIdx].Type == "System.Object[]"))
                holderIdx--;
            var holder = holderIdx >= 0 ? hops[holderIdx].Type : null;
            var member = holderIdx >= 0 ? hops[holderIdx + 1].FieldFromParent : null;
            return new ClassifiedRoot(staticRoot ? "static-event" : "other", holder, member, "delegate", chain);
        }

        if (staticRoot)
        {
            // A static field holds the graph plainly: the holder is the first real object
            // under the statics table.
            var i = 0;
            while (i < hops.Count && hops[i].Type == "System.Object[]") i++;
            var holder = i < hops.Count ? hops[i].Type : null;
            var member = i + 1 < hops.Count ? hops[i + 1].FieldFromParent : null;
            return new ClassifiedRoot("static-field", holder, member, "field", chain);
        }

        return new ClassifiedRoot("other", null, null, rootKindName, chain);
    }
}
