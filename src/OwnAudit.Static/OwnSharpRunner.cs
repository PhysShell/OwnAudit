using System.Diagnostics;
using OwnAudit.Core;

namespace OwnAudit.Static;

/// Arm 1a — the OwnSharp seam. Shells out to Own.NET's own-check.ps1 (-Format sarif)
/// over the target; needs NO build of the target (OwnSharp builds its own Roslyn
/// CSharpCompilation from source and honestly skips what it can't resolve, OWN050).
/// This is the leak BACKBONE: it runs even if the build spike fails, and doubles as
/// OwnSharp's biggest dogfood test (PLAN.md "OwnSharp role").
public sealed class OwnSharpRunner
{
    private readonly AuditConfig _cfg;
    public OwnSharpRunner(AuditConfig cfg) => _cfg = cfg;

    /// Run OwnSharp over <paramref name="targetPath"/>; write a SARIF 2.1 log to
    /// <paramref name="sarifOut"/>. Returns own-check's exit code:
    /// 0 = clean, 1 = findings, >= 2 = hard error (bad facts / drifted contract).
    public int Run(string targetPath, string sarifOut)
    {
        var script = Path.Combine(_cfg.OwnNetRoot, _cfg.OwnCheckScript);
        if (!File.Exists(script))
            throw new FileNotFoundException($"own-check.ps1 not found: {script}");

        // own-check.ps1 -Format sarif writes the SARIF to stdout (the GitHub Action
        // redirects it to a file the same way); -Format has no ValidateSet, so it
        // passes straight through to `python -m ownlang ownir --format sarif`.
        var psi = new ProcessStartInfo("pwsh") { RedirectStandardOutput = true, UseShellExecute = false };
        foreach (var a in new[] { "-NoProfile", "-File", script, "-Root", _cfg.OwnNetRoot,
                                  "-Format", "sarif", "-Severity", "warning", "--", targetPath })
            psi.ArgumentList.Add(a);

        using var p = Process.Start(psi)!;
        var sarif = p.StandardOutput.ReadToEnd();
        p.WaitForExit();
        File.WriteAllText(sarifOut, sarif);
        return p.ExitCode;
    }
}
