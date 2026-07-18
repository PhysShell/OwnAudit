using System.Text.Json;

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
        using var doc = JsonDocument.Parse(File.ReadAllText(path));
        var leakCategories = new HashSet<string>(LeakCategories, StringComparer.Ordinal);
        var suspects = new SortedSet<string>(StringComparer.Ordinal);

        foreach (var finding in doc.RootElement.GetProperty("findings").EnumerateArray())
        {
            if (finding.TryGetProperty("suppressed", out var sup) && sup.GetBoolean())
                continue;
            var category = finding.TryGetProperty("category_name", out var cat) ? cat.GetString() : null;
            if (category is null || !leakCategories.Contains(category))
                continue;

            // Decode before the space test: own-check also emits percent-encoded report
            // labels ("%D0%9E%D1%82%D1%87%D0%B5%D1%82%20…") whose raw form has no literal
            // space and would otherwise pass as a plausible type identifier.
            var resource = (finding.TryGetProperty("resource", out var res) ? res.GetString() : null)?.Trim();
            if (!string.IsNullOrEmpty(resource))
            {
                var decoded = Uri.UnescapeDataString(resource);
                if (!decoded.Contains(' ')
                    && !string.Equals(decoded, "none", StringComparison.OrdinalIgnoreCase))
                    suspects.Add(decoded);
            }

            var stem = Stem(finding.TryGetProperty("path", out var p) ? p.GetString() : null);
            if (!string.IsNullOrEmpty(stem))
                suspects.Add(stem);
        }
        return suspects.ToList();
    }

    /// Owning type guessed from a source path: AmountWindow.xaml.cs -> AmountWindow.
    private static string Stem(string? path)
    {
        var name = Path.GetFileName(path ?? "");
        foreach (var suffix in new[] { ".xaml.cs", ".cs", ".vb" })
            if (name.EndsWith(suffix, StringComparison.OrdinalIgnoreCase))
                return name[..^suffix.Length];
        var dot = name.LastIndexOf('.');
        return dot > 0 ? name[..dot] : name;
    }
}
