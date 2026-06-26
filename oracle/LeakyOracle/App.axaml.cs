using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using LeakyOracle.Services;
using LeakyOracle.ViewModels;
using LeakyOracle.Views;

namespace LeakyOracle;

public partial class App : Application
{
    public override void Initialize() => AvaloniaXamlLoader.Load(this);

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            // one application-scoped service; the window's view-model subscribes to it and never
            // detaches — see WatchlistViewModel.
            var service = new MarketDataService();
            desktop.MainWindow = new MainWindow { DataContext = new WatchlistViewModel(service) };
        }

        base.OnFrameworkInitializationCompleted();
    }
}
