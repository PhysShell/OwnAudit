using System.Net.Mail;

namespace Sts.Core
{
    public static class Mail
    {
        public static void Send(string to, string body)
        {
            SmtpClient client;
            using (client = new SmtpClient("smtp.local"))
            {
                client.Send("from@local", to, "subj", body);
            }
            client.Send("from@local", to, "subj-retry", body);  // use-after-dispose: IDISP005
        }
    }
}
