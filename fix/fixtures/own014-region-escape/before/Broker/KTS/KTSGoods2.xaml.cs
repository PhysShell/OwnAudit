using System.ComponentModel;
using System.Windows.Controls;

namespace Sts.Broker.KTS
{
    public partial class KTSGoods2 : UserControl
    {
        public KTSGoods2()
        {
            InitializeComponent();
            fThis.PropertyChanged += data_PropertyChanged;
        }

        private void data_PropertyChanged(object sender, PropertyChangedEventArgs e) { }
    }
}
