using System.Timers;
using System.Windows;

namespace Sts.Broker
{
    public partial class ShareWindow : Window
    {
        private readonly Timer _timer;

        public ShareWindow()
        {
            InitializeComponent();
            _timer = new Timer(1000);
            _timer.Start();
        }
    }
}
