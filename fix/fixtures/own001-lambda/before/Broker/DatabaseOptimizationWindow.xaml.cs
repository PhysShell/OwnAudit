using System.Windows;

namespace Sts.Broker
{
    public partial class DatabaseOptimizationWindow : Window
    {
        public DatabaseOptimizationWindow(Stage stage)
        {
            InitializeComponent();
            stage.PropertyChanged += (s2, e2) => OnPropertyChanged("Stages");
        }
    }
}
