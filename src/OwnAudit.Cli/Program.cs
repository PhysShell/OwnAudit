using OwnAudit.Core;

// own-audit — one-shot STS audit orchestrator (PLAN.md).
// Verbs: static | runtime | report | config. This is the scaffold DISPATCHER: the
// arms are wired as seams (OwnAudit.Static / .Runtime / .Reporting) and built out in
// phases. Today's live entry points are the spike scripts under spike/.

if (args.Length == 0) { Usage(); return 1; }

var verb = args[0].ToLowerInvariant();
var configPath = GetOpt(args, "--config") ?? "config/ownaudit.json";

switch (verb)
{
    case "static":
        Console.WriteLine("own audit static — Arm 1 (OwnSharp backbone + Roslyn analyzers).");
        Console.WriteLine("  Not yet built out. First derisk + first findings:");
        Console.WriteLine("    spike/Invoke-OwnSharpOnSts.ps1   # OwnSharp over STS (no build) -> SARIF");
        Console.WriteLine("    spike/Invoke-BuildSpike.ps1      # prove headless msbuild + analyzer SARIF");
        Console.WriteLine("  See PLAN.md \"Arm 1\".");
        return 0;

    case "runtime":
        Console.WriteLine("own audit runtime — Arm 2 (FlaUI drive + ClrMD heap-diff, top suspects).");
        Console.WriteLine("  Gated on Arm 1 producing ranked suspects. See PLAN.md \"Arm 2\".");
        return 0;

    case "report":
        Console.WriteLine("own audit report — Arm 3 (ranked markdown + SARIF dossier).");
        Console.WriteLine("  See PLAN.md \"Reporting\".");
        return 0;

    case "config":
        if (!File.Exists(configPath)) { Console.Error.WriteLine($"no config at {configPath}"); return 2; }
        var cfg = AuditConfig.Load(configPath);
        Console.WriteLine($"OwnNetRoot     : {cfg.OwnNetRoot}");
        Console.WriteLine($"OwnCheckScript : {cfg.OwnCheckScript}");
        Console.WriteLine($"TargetSolution : {cfg.TargetSolution}");
        Console.WriteLine($"TargetRoot     : {cfg.TargetRoot}");
        Console.WriteLine($"Analyzers      : {string.Join(", ", cfg.Analyzers)}");
        return 0;

    default:
        Console.Error.WriteLine($"unknown verb: {verb}");
        Usage();
        return 2;
}

static void Usage()
{
    Console.WriteLine("own-audit <static|runtime|report|config> [--config <path>]");
    Console.WriteLine("  static   Arm 1: OwnSharp + Roslyn analyzers -> ranked suspects");
    Console.WriteLine("  runtime  Arm 2: FlaUI + ClrMD prove the top suspects");
    Console.WriteLine("  report   Arm 3: ranked dossier (markdown + SARIF)");
    Console.WriteLine("  config   print the resolved audit config");
    Console.WriteLine();
    Console.WriteLine("Scaffold: see PLAN.md for the phased build-out. Live entry points today are spike/*.ps1.");
}

static string? GetOpt(string[] argv, string name)
{
    var i = Array.IndexOf(argv, name);
    return (i >= 0 && i + 1 < argv.Length) ? argv[i + 1] : null;
}
