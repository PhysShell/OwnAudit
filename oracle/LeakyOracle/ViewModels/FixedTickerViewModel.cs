using System;
using System.Threading;

namespace LeakyOracle.ViewModels;

/// <summary>
/// The corrected counterpart of <see cref="TickerViewModel"/>: it owns the <see cref="Timer"/> and
/// disposes it. Disposing unlinks the timer from the runtime's TimerQueue, so once disposed this
/// view-model is no longer rooted and collects normally — the control case that keeps the timer-leak
/// proof honest (same WeakReference harness; correct code collects, leaky code doesn't).
/// </summary>
public sealed class FixedTickerViewModel : IDisposable
{
    private readonly Timer _timer;
    private int _ticks;

    public FixedTickerViewModel()
    {
        _timer = new Timer(OnTick, null, 300_000, 300_000);
    }

    private void OnTick(object? state) => _ticks++;

    public void Dispose() => _timer.Dispose();   // the fix: unlink from the TimerQueue
}
