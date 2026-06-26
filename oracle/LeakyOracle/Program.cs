using System;
using System.Linq;
using Avalonia;

namespace LeakyOracle;

internal static class Program
{
    // Dual-mode entry: `--leak-scenario` runs the headless leak proof (no display, CI-friendly);
    // otherwise it launches the real GUI (needs a desktop session).
    [STAThread]
    public static int Main(string[] args)
    {
        if (args.Contains("--leak-scenario"))
            return LeakScenario.Run();

        BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
        return 0;
    }

    public static AppBuilder BuildAvaloniaApp() =>
        AppBuilder.Configure<App>()
                  .UsePlatformDetect()
                  .WithInterFont()
                  .LogToTrace();
}
