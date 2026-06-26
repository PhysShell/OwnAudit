using System;

namespace LeakyOracle.Services;

/// <summary>
/// A long-lived (application-scoped) service that publishes quote ticks. It outlives the views and
/// view-models that subscribe to it, so any subscriber that fails to detach is rooted here for the
/// life of the process. This is the classic WPF/Avalonia event-lifetime leak — the framework-agnostic
/// core of own-check OWN001 (<c>+=</c> without a matching <c>-=</c>), confirmed at runtime by the
/// phase-5 heap walk (docs/wpf-audit-coverage.md, "Event leaks").
/// </summary>
public sealed class MarketDataService
{
    /// <summary>Raised on every market tick. Subscribers MUST detach or they leak.</summary>
    public event EventHandler<string>? QuoteReceived;

    public void Tick(string symbol) => QuoteReceived?.Invoke(this, symbol);
}
