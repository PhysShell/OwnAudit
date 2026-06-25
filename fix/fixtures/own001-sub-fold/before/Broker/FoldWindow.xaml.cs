using System;
using System.ComponentModel;
using System.Windows;

namespace Sts.Broker
{
    public partial class FoldWindow : Window
    {
        private readonly Goods fGoods;

        public FoldWindow(Goods goods)
        {
            fGoods = goods;
            InitializeComponent();
            fGoods.PropertyChanged += new PropertyChangedEventHandler(GoodsPropertyChanged);
        }

        protected override void OnClosed(EventArgs e)
        {
            base.OnClosed(e);
        }

        private void GoodsPropertyChanged(object sender, PropertyChangedEventArgs e) { }
    }
}
