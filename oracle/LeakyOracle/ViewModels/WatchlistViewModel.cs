using System.Collections.Generic;
using LeakyOracle.Services;

namespace LeakyOracle.ViewModels;

/// <summary>
/// A per-screen view-model. DELIBERATELY LEAKY — two intentional smells:
///
///  • <b>Subscription leak (OWN001).</b> It subscribes to <see cref="MarketDataService.QuoteReceived"/>
///    in the constructor and never unsubscribes (no <c>IDisposable</c>, no <c>-=</c>). Because the
///    service is application-scoped, every WatchlistViewModel ever created stays rooted through the
///    service's delegate list — open-and-close a hundred screens and a hundred view-models (and their
///    row graphs) survive every GC. This is the heap-confirmable event-lifetime leak.
///
///  • <b>Duplicated strings.</b> It fills its rows with freshly-allocated copies of a tiny status
///    vocabulary (<c>new string(...)</c> never interns), so the heap holds thousands of distinct
///    <see cref="string"/> instances with identical content — the string-canonicalization target
///    (docs/string-canonicalization.md). Combined with the subscription leak, those duplicates never
///    get collected either.
/// </summary>
public sealed class WatchlistViewModel
{
    private static readonly string[] Vocabulary = { "ACTIVE", "HALTED", "CLOSED", "PENDING" };

    private readonly MarketDataService _service;

    public List<QuoteRow> Rows { get; } = new();

    public WatchlistViewModel(MarketDataService service)
    {
        _service = service;
        _service.QuoteReceived += OnQuoteReceived;   // LEAK: never removed -> roots `this` forever

        for (var i = 0; i < 5000; i++)
        {
            // new string each time: same bytes, distinct reference, all retained.
            var status = new string(Vocabulary[i % Vocabulary.Length].ToCharArray());
            Rows.Add(new QuoteRow(status));
        }
    }

    private void OnQuoteReceived(object? sender, string symbol)
    {
        // The handler body is irrelevant — its mere existence in the service's invocation list is
        // what keeps this view-model (and its 5000 rows) alive.
    }
}
