using System.ComponentModel;
using System.Windows;

namespace Sts.Broker
{
    public partial class AmountWindow : Window
    {
        private readonly Goods fGoods;

        public AmountWindow(Goods goods)
        {
            fGoods = goods;
            InitializeComponent();
            fGoods.PropertyChanged += new PropertyChangedEventHandler(GoodsPropertyChanged);
        }

        private void GoodsPropertyChanged(object sender, PropertyChangedEventArgs e) { }
    }
}
