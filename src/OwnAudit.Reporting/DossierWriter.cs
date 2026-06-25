using System.Text;
using OwnAudit.Core;

namespace OwnAudit.Reporting;

/// Arm 3 — the dossier. Renders ranked findings (and, later, Arm-2 retention proofs)
/// into one markdown report (a SARIF summary follows in the reporting build-out).
/// The north-star artifact correlates static suspect + runtime proof + GC root —
/// see PLAN.md "Reporting".
public sealed class DossierWriter
{
    /// Write a ranked markdown dossier. Minimal at scaffold time: header + ranked
    /// finding table. Per-suspect dossiers and runtime-proof folding come in build-out.
    public void WriteMarkdown(string outPath, IReadOnlyList<Finding> ranked)
    {
        var sb = new StringBuilder();
        sb.AppendLine("# OwnAudit — STS suspect report");
        sb.AppendLine();
        sb.AppendLine($"_Generated {DateTime.Now:yyyy-MM-dd HH:mm}_ · {ranked.Count} findings");
        sb.AppendLine();
        sb.AppendLine("| Rank | Class | Rule | Tools | File:Line | Symbol | Message |");
        sb.AppendLine("|--:|---|---|--:|---|---|---|");
        foreach (var f in ranked)
            sb.AppendLine($"| {f.Rank:0.0} | {f.LeakClass} | {f.RuleId} | {f.Corroboration} | " +
                          $"{f.File}:{f.Line} | {f.Symbol} | {Escape(f.Message)} |");
        File.WriteAllText(outPath, sb.ToString());
    }

    private static string Escape(string s) => s.Replace("|", "\\|").ReplaceLineEndings(" ");
}
