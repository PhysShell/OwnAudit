using System.Net.Mail;

namespace Sts.Core
{
    public static class Mail
    {
        public static void Send(string to, string body)
        {
            using (var client = new SmtpClient("smtp.local"))
            {
                client.Send("from@local", to, "subj", body);
            }
        }
    }
}
