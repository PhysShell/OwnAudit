namespace LeakyOracle.ViewModels;

/// <summary>One row in the watchlist. Trivial by design — the point is that there are many of them
/// and that each holds a duplicated status string (see <see cref="WatchlistViewModel"/>).</summary>
public sealed class QuoteRow
{
    public QuoteRow(string status) => Status = status;

    public string Status { get; }
}
