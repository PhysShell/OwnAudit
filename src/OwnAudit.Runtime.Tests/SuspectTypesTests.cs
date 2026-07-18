using Xunit;

namespace OwnAudit.Runtime.Tests;

public sealed class SuspectTypesTests
{
    [Fact]
    public void Derives_leak_suspects_from_the_oracle_findings_fixture()
    {
        var repoRoot = new DirectoryInfo(AppContext.BaseDirectory);
        while (repoRoot is not null && !File.Exists(Path.Combine(repoRoot.FullName, "OwnAudit.slnx")))
            repoRoot = repoRoot.Parent!;
        var findings = Path.Combine(repoRoot!.FullName, "oracle", "fixtures", "findings.json");

        var suspects = SuspectTypes.FromFindingsJson(findings);

        // The file stems of the two leak findings; the descriptions in `resource`
        // ("QuoteReceived subscription") must NOT come through as types.
        Assert.Contains("WatchlistViewModel", suspects);
        Assert.Contains("TickerViewModel", suspects);
        Assert.DoesNotContain(suspects, s => s.Contains(' '));
    }

    [Fact]
    public void Rejects_url_encoded_labels_the_space_filter_would_miss()
    {
        // Real own-check output carries percent-encoded report labels in `resource`
        // ("%D0%9E%D1%82%D1%87%D0%B5%D1%82%20…" = "Отчет УН …") — no literal space, so a
        // naive filter admits them as suspect types (seen in the STS acceptance run).
        var path = Path.Combine(Path.GetTempPath(), $"suspects-{Guid.NewGuid():N}.json");
        File.WriteAllText(path, """
            {
              "findings": [
                { "category_name": "subscription-leak",
                  "resource": "%D0%9E%D1%82%D1%87%D0%B5%D1%82%20%D0%A3%D0%9D",
                  "path": "Broker/AmountWindow.xaml.cs", "line": 1, "suppressed": false },
                { "category_name": "subscription-leak",
                  "resource": "subscription token",
                  "path": "BrokerDataClasses/KDT/KDT.cs", "line": 88, "suppressed": false }
              ]
            }
            """);
        try
        {
            var suspects = SuspectTypes.FromFindingsJson(path);

            Assert.Contains("AmountWindow", suspects);
            Assert.Contains("KDT", suspects);
            Assert.DoesNotContain(suspects, s => s.Contains('%') || Uri.UnescapeDataString(s).Contains(' '));
        }
        finally
        {
            File.Delete(path);
        }
    }
}
