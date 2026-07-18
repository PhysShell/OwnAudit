using Xunit;

namespace OwnAudit.Runtime.Tests;

/// The collector's contract (docs/collector-plan.md D8), asserted against a real heap:
/// LeakyOracle's planted leaks must be seen as retained, the Fixed* controls must not.
/// One attach per class — the fixture holds the oracle for all assertions.
public sealed class HeapCollectorContractTests : IClassFixture<OracleFixture>
{
    private const string Watchlist = "LeakyOracle.ViewModels.WatchlistViewModel";
    private const string FixedWatchlist = "LeakyOracle.ViewModels.FixedWatchlistViewModel";
    private const string Ticker = "LeakyOracle.ViewModels.TickerViewModel";
    private const string FixedTicker = "LeakyOracle.ViewModels.FixedTickerViewModel";

    private readonly OracleFixture _oracle;

    public HeapCollectorContractTests(OracleFixture oracle) => _oracle = oracle;

    [Fact]
    public void Collect_sees_the_planted_leaks_and_only_them()
    {
        var result = new HeapCollector().Collect(
            _oracle.Pid, new[] { Watchlist, FixedWatchlist, Ticker, FixedTicker });

        // heapStats: the reachable subset is non-empty and cannot exceed the heap census.
        Assert.True(result.HeapStats.ReachableObjects > 0, "no objects reachable from GC roots");
        Assert.True(result.HeapStats.ReachableObjects <= result.HeapStats.Objects,
            $"reachable {result.HeapStats.ReachableObjects} > heap {result.HeapStats.Objects}");
        Assert.True(result.HeapStats.RootCount > 0, "no GC roots enumerated");

        var byType = result.Retained.ToDictionary(r => r.Type);

        // The planted leaks: every dropped screen is still reachable.
        Assert.Equal(OracleFixture.Screens, byType[Watchlist].Count);
        Assert.Equal(OracleFixture.Screens, byType[Ticker].Count);

        // The FP controls: the fixed counterparts were collected — exact-name matching means
        // FixedWatchlistViewModel must never be folded into WatchlistViewModel's count.
        Assert.Equal(0, byType[FixedWatchlist].Count);
        Assert.Equal(0, byType[FixedTicker].Count);

        // Chains: each leaky survivor comes with at least one root→object path, and the
        // subscription leak's path runs through the service that pins it.
        Assert.NotEmpty(byType[Watchlist].Chains);
        Assert.Contains(byType[Watchlist].Chains,
            c => c.Hops.Any(h => h.Contains("MarketDataService")));
        Assert.NotEmpty(byType[Ticker].Chains);

        // Collected types carry no chains — nothing roots them.
        Assert.Empty(byType[FixedWatchlist].Chains);
        Assert.Empty(byType[FixedTicker].Chains);

        // Classification (collector-plan.md D4). The subscription leak is the OWN001 smoking
        // gun: a delegate on a statically-rooted publisher, named down to the event member.
        Assert.Contains(byType[Watchlist].Roots, r =>
            r.Kind == "static-event"
            && r.Holder is not null && r.Holder.Contains("MarketDataService")
            && r.Member == "QuoteReceived");

        // The timer leak pins through the runtime's TimerQueue.
        Assert.Contains(byType[Ticker].Roots, r => r.Kind == "timer");

        // Nothing retained → nothing to classify.
        Assert.Empty(byType[FixedWatchlist].Roots);
        Assert.Empty(byType[FixedTicker].Roots);
    }
}
