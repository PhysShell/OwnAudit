using System;
using System.Collections.Generic;
using LeakyOracle.Services;
using LeakyOracle.ViewModels;

namespace LeakyOracle;

/// <summary>
/// A headless, self-validating proof that the oracle leaks — no display, so it runs in CI. It mimics
/// the scenario the runtime audit drives ("open and close a screen N times") for TWO independent leak
/// kinds, each with its corrected counterpart run through the SAME WeakReference harness:
///
///  • subscription leak — leaky <see cref="WatchlistViewModel"/> (subscribes, never detaches) must ALL
///    survive GC; <see cref="FixedWatchlistViewModel"/> (detaches on Dispose) must ALL be collected;
///  • timer leak — leaky <see cref="TickerViewModel"/> (undisposed Timer) must ALL survive GC;
///    <see cref="FixedTickerViewModel"/> (disposes the Timer) must ALL be collected.
///
/// Checking the fixed batches too proves the harness isn't rigged: if it were, they'd look alive too.
/// Exit 0 means the oracle leaked exactly where it should and nowhere it shouldn't — this is a TARGET,
/// not a test of our auditor; if it stops behaving we fail loudly because the oracle is broken.
/// </summary>
public static class LeakScenario
{
    public static int Run(int screens = 50)
    {
        var service = new MarketDataService();

        var subLeaked = OpenAndDrop(screens, () => new WatchlistViewModel(service));
        var subFixed = OpenAndDrop(screens, () => new FixedWatchlistViewModel(service),
                                   dispose: vm => ((FixedWatchlistViewModel)vm).Dispose());
        var timerLeaked = OpenAndDrop(screens, () => new TickerViewModel());
        var timerFixed = OpenAndDrop(screens, () => new FixedTickerViewModel(),
                                     dispose: vm => ((FixedTickerViewModel)vm).Dispose());

        var ok = subLeaked == screens && subFixed == 0 && timerLeaked == screens && timerFixed == 0;

        Console.WriteLine($"screens opened+closed        : {screens}");
        Console.WriteLine($"subscription leaky alive (GC): {subLeaked,3}  (expect {screens} — rooted by MarketDataService.QuoteReceived)");
        Console.WriteLine($"subscription fixed alive (GC): {subFixed,3}  (expect 0 — detached on Dispose)");
        Console.WriteLine($"timer        leaky alive (GC): {timerLeaked,3}  (expect {screens} — rooted by the TimerQueue)");
        Console.WriteLine($"timer        fixed alive (GC): {timerFixed,3}  (expect 0 — Timer disposed)");
        Console.WriteLine($"verdict                      : {(ok ? "BOTH leaks confirmed, each isolated to its un-released resource" : "UNEXPECTED")}");
        Console.WriteLine(ok
            ? "ORACLE OK: leaks as designed — a valid target for the heap/lifetime audit."
            : "ORACLE BROKEN: leak signature is wrong; fix the oracle, not the auditor.");

        return ok ? 0 : 1;
    }

    // Create `screens` objects, optionally dispose each, drop all strong refs, force GC, and report
    // how many survive. Survival is only possible through a reference the scenario itself dropped —
    // i.e. an unintended root (the leak).
    private static int OpenAndDrop(int screens, Func<object> open, Action<object>? dispose = null)
    {
        // Allocate in a SEPARATE, non-inlined frame so the last `vm` local can't linger in a
        // register/stack slot across the GC below — otherwise the most-recently-created object
        // spuriously survives and a correct (fixed) batch looks like it leaked one.
        var weak = Allocate(screens, open, dispose);

        GC.Collect();
        GC.WaitForPendingFinalizers();
        GC.Collect();

        var alive = 0;
        foreach (var w in weak)
            if (w.IsAlive) alive++;
        return alive;
    }

    [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)]
    private static List<WeakReference> Allocate(int screens, Func<object> open, Action<object>? dispose)
    {
        var weak = new List<WeakReference>(screens);
        for (var i = 0; i < screens; i++)
        {
            var vm = open();
            dispose?.Invoke(vm);
            weak.Add(new WeakReference(vm));
        }
        return weak;
    }
}
