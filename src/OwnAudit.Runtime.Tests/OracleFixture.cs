using System.Diagnostics;

namespace OwnAudit.Runtime.Tests;

/// Launches oracle/LeakyOracle in `--leak-scenario --hold` mode and hands the test its pid.
/// The scenario opens+drops 50 screens of each kind, self-validates (leaky alive, fixed
/// collected), prints SCENARIO-READY and blocks on stdin — the attach point. Disposing the
/// fixture releases the hold (writes a line) and reaps the process.
public sealed class OracleFixture : IDisposable
{
    public const int Screens = 50;

    private readonly Process _process;

    public int Pid => _process.Id;

    public OracleFixture()
    {
        var repoRoot = FindRepoRoot();
        var dll = Path.Combine(repoRoot, "oracle", "LeakyOracle", "bin", "Release", "net8.0", "LeakyOracle.dll");
        if (!File.Exists(dll))
        {
            RunDotnet(repoRoot, $"build -c Release \"{Path.Combine(repoRoot, "oracle", "LeakyOracle", "LeakyOracle.csproj")}\"");
            if (!File.Exists(dll))
                throw new InvalidOperationException($"LeakyOracle did not build: {dll} is missing");
        }

        _process = new Process
        {
            StartInfo = new ProcessStartInfo("dotnet", $"\"{dll}\" --leak-scenario --hold")
            {
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardInput = true,
                CreateNoWindow = true,
                WorkingDirectory = repoRoot,
            },
        };
        _process.Start();

        // Wait for the handshake; anything before it is the scenario's own verdict output.
        var deadline = DateTime.UtcNow + TimeSpan.FromSeconds(120);
        while (true)
        {
            if (DateTime.UtcNow > deadline)
            {
                try { _process.Kill(); } catch { /* already gone */ }
                throw new TimeoutException("LeakyOracle never printed SCENARIO-READY");
            }
            var line = _process.StandardOutput.ReadLine();
            if (line is null)
                throw new InvalidOperationException(
                    $"LeakyOracle exited before SCENARIO-READY (exit {(_process.HasExited ? _process.ExitCode : -1)}) — the oracle is broken, fix it, not the collector");
            if (line.Contains("SCENARIO-READY"))
                return;
        }
    }

    public void Dispose()
    {
        try
        {
            _process.StandardInput.WriteLine();
            if (!_process.WaitForExit(10_000))
                _process.Kill();
        }
        catch
        {
            try { _process.Kill(); } catch { /* already gone */ }
        }
        _process.Dispose();
    }

    private static string FindRepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "OwnAudit.slnx")))
            dir = dir.Parent;
        return dir?.FullName
            ?? throw new InvalidOperationException("OwnAudit.slnx not found above " + AppContext.BaseDirectory);
    }

    private static void RunDotnet(string workingDir, string args)
    {
        var psi = new ProcessStartInfo("dotnet", args)
        {
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            WorkingDirectory = workingDir,
        };
        using var p = Process.Start(psi)!;
        var stdout = p.StandardOutput.ReadToEndAsync();
        var stderr = p.StandardError.ReadToEndAsync();
        if (!p.WaitForExit(300_000))
        {
            try { p.Kill(); } catch { /* best effort */ }
            throw new TimeoutException($"dotnet {args} timed out");
        }
        Task.WaitAll(stdout, stderr);
        if (p.ExitCode != 0)
            throw new InvalidOperationException($"dotnet {args} failed (exit {p.ExitCode}):\n{stdout.Result}\n{stderr.Result}");
    }
}
