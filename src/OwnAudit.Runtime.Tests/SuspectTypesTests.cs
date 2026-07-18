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
}
