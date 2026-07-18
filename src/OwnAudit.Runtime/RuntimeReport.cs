namespace OwnAudit.Runtime;

/// Serializes a collection into the `runtime.json` heap-retention artifact
/// (docs/runtime-contract.md schema v1) that `runtime/correlate.py` consumes, plus the
/// optional `heapStats` reachability-gate block and per-root `chain` evidence
/// (docs/collector-plan.md D7) — unknown fields are ignored by the correlation pass.
public static class RuntimeReport
{
    public static string ToJson(
        CollectionResult result, string scenario, int? iterations = null,
        IReadOnlyDictionary<string, int>? expected = null)
    {
        throw new NotImplementedException("collector-plan.md step 4: emit runtime.json");
    }
}
