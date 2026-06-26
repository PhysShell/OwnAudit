using System;
using System.Collections.Generic;
using LeakyOracle.Services;
using LeakyOracle.ViewModels;

namespace LeakyOracle;

/// <summary>
/// A headless, self-validating proof that the oracle leaks — no display, so it runs in CI. It mimics
/// the scenario the runtime audit drives ("open and close a screen N times") for BOTH view-models:
///
///  • the leaky <see cref="WatchlistViewModel"/> (subscribes, never detaches) must ALL survive GC;
///  • the corrected <see cref="FixedWatchlistViewModel"/> (detaches on Dispose) must ALL be collected.
///
/// Checking both with the same WeakReference harness proves the harness isn't rigged: if it were,
/// the fixed batch would look alive too. Exit code 0 means the oracle leaked exactly where it should
/// and nowhere it shouldn't — this is a TARGET, not a test of our auditor; if it stops behaving we
/// fail loudly because the oracle (not the auditor) is broken.
/// </summary>
public static class LeakScenario
{
    public static int Run(int screens = 50)
    {
        var service = new MarketDataService();

        var leakedAlive = OpenAndDrop(screens, () => new WatchlistViewModel(service));
        var fixedAlive = OpenAndDrop(screens, () =>
        {
            var vm = new FixedWatchlistViewModel(service);
            return vm;
        }, dispose: vm => ((FixedWatchlistViewModel)vm).Dispose());

        var leaksWhereItShould = leakedAlive == screens;
        var cleanWhereItShould = fixedAlive == 0;
        var ok = leaksWhereItShould && cleanWhereItShould;

        Console.WriteLine($"screens opened+closed   : {screens}");
        Console.WriteLine($"leaky  still alive (GC) : {leakedAlive,3}  (expect {screens} — rooted by MarketDataService.QuoteReceived)");
        Console.WriteLine($"fixed  still alive (GC) : {fixedAlive,3}  (expect 0 — detached on Dispose)");
        Console.WriteLine($"verdict                 : {(ok ? "LEAK confirmed and isolated to the un-detached subscription" : "UNEXPECTED")}");
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
