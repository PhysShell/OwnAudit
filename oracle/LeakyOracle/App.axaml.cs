using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using LeakyOracle.Services;
using LeakyOracle.ViewModels;
using LeakyOracle.Views;

namespace LeakyOracle;

public partial class App : Application
{
    // App-scoped and rooted for the whole process: the App instance is held by Avalonia
    // (Application.Current), so this service is too. That root is what makes the subscription leak
    // REAL in the GUI heap — a closed window's view-model stays rooted through this service's event
    // (without it, VM->service->delegate->VM is an unrooted cycle the GC would just collect, and the
    // oracle would produce no OWN001 heap evidence). This is the GUI analog of the long-lived
    // `service` local in LeakScenario.
    private readonly MarketDataService _service = new();

    public override void Initialize() => AvaloniaXamlLoader.Load(this);

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            // the window's view-model subscribes to the app-scoped service and never detaches —
            // see WatchlistViewModel.
            desktop.MainWindow = new MainWindow { DataContext = new WatchlistViewModel(_service) };
        }

        base.OnFrameworkInitializationCompleted();
    }
}
