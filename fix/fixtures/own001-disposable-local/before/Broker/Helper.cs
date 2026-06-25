using System.Diagnostics;

namespace Sts.Broker
{
    public static class Helper
    {
        public static void Run()
        {
            var myProcess = new Process();
            myProcess.StartInfo.FileName = "x.exe";
            myProcess.Start();
        }
    }
}
