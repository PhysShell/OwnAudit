using System.Net.Mail;

namespace Sts.Core
{
    public static class Mail
    {
        public static void Send(string to, string body)
        {
            var client = new SmtpClient("smtp.local");
            client.Send("from@local", to, "subj", body);
            // client.Dispose();   // IDISP001: SmtpClient created but never disposed
        }
    }
}
