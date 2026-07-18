using System.Text.Json;
using System.Text.Json.Nodes;

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
        var doc = new JsonObject
        {
            ["schema"] = "ownAudit/runtime/v1",
            ["scenario"] = scenario,
        };
        if (iterations is not null)
            doc["iterations"] = iterations.Value;

        doc["heapStats"] = new JsonObject
        {
            ["objects"] = result.HeapStats.Objects,
            ["bytes"] = result.HeapStats.Bytes,
            ["reachableObjects"] = result.HeapStats.ReachableObjects,
            ["reachableBytes"] = result.HeapStats.ReachableBytes,
            ["rootCount"] = result.HeapStats.RootCount,
        };

        var retained = new JsonArray();
        foreach (var rt in result.Retained)
        {
            var roots = new JsonArray();
            foreach (var root in rt.Roots)
            {
                var entry = new JsonObject
                {
                    ["kind"] = root.Kind,
                    ["holder"] = root.Holder,
                };
                if (root.Member is not null)
                    entry["member"] = root.Member;
                entry["via"] = root.Via;
                entry["chain"] = new JsonArray(root.Chain.Hops.Select(h => (JsonNode?)h).ToArray());
                roots.Add(entry);
            }

            var record = new JsonObject
            {
                ["type"] = rt.Type,
                ["count"] = rt.Count,
            };
            if (expected is not null && expected.TryGetValue(rt.Type, out var exp))
                record["expected"] = exp;
            record["bytes"] = rt.Bytes;
            record["roots"] = roots;
            retained.Add(record);
        }
        doc["retained"] = retained;

        return doc.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
    }
}
