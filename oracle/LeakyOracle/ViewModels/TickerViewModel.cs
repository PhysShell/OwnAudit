using System.Threading;

namespace LeakyOracle.ViewModels;

/// <summary>
/// A per-screen view-model that drives a live "ticker" off a <see cref="Timer"/>. DELIBERATELY LEAKY:
/// it starts a recurring <see cref="System.Threading.Timer"/> in the constructor and never disposes it.
///
/// An active timer is registered in the runtime's (static) TimerQueue, which holds the timer's callback
/// delegate — and the delegate's target is this view-model. So every TickerViewModel ever created stays
/// rooted by the timer queue until <see cref="Timer.Dispose()"/> is called: the timer-lifetime leak
/// (own-check small rule; docs/wpf-audit-coverage.md, "Timers": DispatcherTimer/Timers.Timer/
/// Threading.Timer with no Stop/Dispose). The framework-agnostic core: identical on WPF and Avalonia.
///
/// The `_timer` field is deliberate — without it the public Timer wrapper would be finalized and stop
/// the timer; holding it keeps the timer alive (and the leak real), exactly as leaky code does.
/// </summary>
public sealed class TickerViewModel
{
    private readonly Timer _timer;
    private int _ticks;

    public TickerViewModel()
    {
        // recurring + far-future due time: registered (so it roots `this`) but won't actually fire
        // during a sub-second scenario. Never disposed -> never unlinked from the TimerQueue.
        _timer = new Timer(OnTick, null, 300_000, 300_000);
    }

    private void OnTick(object? state) => _ticks++;
}
