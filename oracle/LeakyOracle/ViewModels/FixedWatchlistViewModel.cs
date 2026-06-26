using System;
using System.Collections.Generic;
using LeakyOracle.Services;

namespace LeakyOracle.ViewModels;

/// <summary>
/// The corrected counterpart of <see cref="WatchlistViewModel"/> — what the OWN001 fix looks like:
/// it owns its subscription and detaches on <see cref="Dispose"/>. Once disposed it is no longer
/// rooted by the service and collects normally.
///
/// This exists so the leak proof is self-validating: the same WeakReference harness that shows the
/// leaky view-model surviving GC shows this one being collected. If the harness were rigged, BOTH
/// would look alive. (It also gives the future fix-arm a concrete before/after target.)
/// </summary>
public sealed class FixedWatchlistViewModel : IDisposable
{
    private static readonly string[] Vocabulary = { "ACTIVE", "HALTED", "CLOSED", "PENDING" };

    private readonly MarketDataService _service;

    public List<QuoteRow> Rows { get; } = new();

    public FixedWatchlistViewModel(MarketDataService service)
    {
        _service = service;
        _service.QuoteReceived += OnQuoteReceived;

        for (var i = 0; i < 5000; i++)
        {
            var status = new string(Vocabulary[i % Vocabulary.Length].ToCharArray());
            Rows.Add(new QuoteRow(status));
        }
    }

    private void OnQuoteReceived(object? sender, string symbol)
    {
    }

    public void Dispose() => _service.QuoteReceived -= OnQuoteReceived;   // the fix: detach
}
