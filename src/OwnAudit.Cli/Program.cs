using OwnAudit.Core;

// own-audit — orientation + config for the OwnAudit repo.
//
// OwnAudit is the designated LIFT-OUT HOME for Own.NET's audit/ (Own.NET Plan.md §7).
// The CANONICAL audit — static aggregation, taxonomy, scoring, the md/json/SARIF/HTML
// reporters, and the runtime LeakHarness/storm-profiler — lives in Own.NET/audit/
// (Python + a C# harness). Do NOT reimplement it here.
//
// To RUN the audit over STS, use Run-Audit.ps1 (it drives Own.NET/audit/ end-to-end).
// This .NET solution is reserved for audit/'s C# on lift-out + the deferred ClrMD work.

if (args.Length == 0) { Usage(); return 1; }

switch (args[0].ToLowerInvariant())
{
    case "config":
        var cp = GetOpt(args, "--config") ?? "config/ownaudit.json";
        if (!File.Exists(cp)) { Console.Error.WriteLine($"no config at {cp}"); return 2; }
        var cfg = AuditConfig.Load(cp);
        Console.WriteLine($"OwnNetRoot     : {cfg.OwnNetRoot}   (audit/ is canonical there)");
        Console.WriteLine($"OwnCheckScript : {cfg.OwnCheckScript}");
        Console.WriteLine($"TargetSolution : {cfg.TargetSolution}");
        Console.WriteLine($"TargetRoot     : {cfg.TargetRoot}");
        return 0;

    case "run":
        Console.WriteLine("Run the audit over STS with:  pwsh ./Run-Audit.ps1");
        Console.WriteLine("It drives Own.NET/audit/ (own-check -> SARIF -> normalize -> report).");
        return 0;

    default:
        Usage();
        return 2;
}

static void Usage()
{
    Console.WriteLine("OwnAudit — lift-out home for Own.NET/audit/ (the audit impl is canonical THERE).");
    Console.WriteLine("  own-audit config [--config <path>]   print the resolved audit config");
    Console.WriteLine("  own-audit run                        how to run the audit over STS");
    Console.WriteLine();
    Console.WriteLine("Static analysis + aggregation + reporting are canonical in Own.NET/audit/.");
    Console.WriteLine("Run them via Run-Audit.ps1. See PLAN.md for this repo's role.");
}

static string? GetOpt(string[] argv, string name)
{
    var i = Array.IndexOf(argv, name);
    return (i >= 0 && i + 1 < argv.Length) ? argv[i + 1] : null;
}
