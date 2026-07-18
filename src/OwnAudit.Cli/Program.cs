using OwnAudit.Core;
using OwnAudit.Runtime;

// own-audit — CLI for the OwnAudit repo (the CANONICAL audit repo since 2026-07-18;
// Own.NET stays a pure SAST engine and emits findings).
//
// `collect` is the stand-side heap collector (docs/collector-plan.md): run your scenario
// against the live app, then attach once and emit the runtime.json that
// runtime/correlate.py folds into confirmed / static-only / runtime-only.
//
// To RUN the static audit over STS, use Run-Audit.ps1.

if (args.Length == 0) { Usage(); return 1; }

switch (args[0].ToLowerInvariant())
{
    case "config":
        var cp = GetOpt(args, "--config") ?? "config/ownaudit.json";
        if (!File.Exists(cp)) { Console.Error.WriteLine($"no config at {cp}"); return 2; }
        var cfg = AuditConfig.Load(cp);
        Console.WriteLine($"OwnNetRoot     : {cfg.OwnNetRoot}");
        Console.WriteLine($"OwnCheckScript : {cfg.OwnCheckScript}");
        Console.WriteLine($"TargetSolution : {cfg.TargetSolution}");
        Console.WriteLine($"TargetRoot     : {cfg.TargetRoot}");
        return 0;

    case "run":
        Console.WriteLine("Run the static audit over STS with:  pwsh ./Run-Audit.ps1");
        Console.WriteLine("(own-check -> SARIF -> normalize -> report; see PLAN.md)");
        return 0;

    case "collect":
        return Collect(args);

    default:
        Usage();
        return 2;
}

static int Collect(string[] args)
{
    if (GetOpt(args, "--pid") is not { } pidOpt || !int.TryParse(pidOpt, out var pid))
    {
        Console.Error.WriteLine("collect: --pid <pid> is required (attach AFTER your scenario ran)");
        return 2;
    }

    IReadOnlyList<string> suspects;
    if (GetOpt(args, "--types") is { } types)
    {
        suspects = types.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
    }
    else if (GetOpt(args, "--findings") is { } findings)
    {
        if (!File.Exists(findings)) { Console.Error.WriteLine($"collect: no findings at {findings}"); return 2; }
        suspects = SuspectTypes.FromFindingsJson(findings);
        Console.WriteLine($"suspects from {findings}: {string.Join(", ", suspects)}");
    }
    else
    {
        Console.Error.WriteLine("collect: pass --findings findings.json (default mode) or --types A,B");
        return 2;
    }
    if (suspects.Count == 0)
    {
        Console.Error.WriteLine("collect: no leak suspects derived — nothing to look for");
        return 2;
    }

    var maxChains = GetOpt(args, "--max-chains") is { } mc && int.TryParse(mc, out var m) ? m : 3;
    var result = new HeapCollector().Collect(pid, suspects, maxChains);

    var stats = result.HeapStats;
    var share = stats.Bytes == 0 ? 0 : 100.0 * stats.ReachableBytes / stats.Bytes;
    Console.WriteLine($"heap {stats.Objects:N0} objects / {stats.Bytes / 1048576.0:N0} MB; " +
                      $"reachable {stats.ReachableObjects:N0} / {stats.ReachableBytes / 1048576.0:N0} MB " +
                      $"({share:N1}% genuinely retained) from {stats.RootCount:N0} roots");
    foreach (var rt in result.Retained)
    {
        Console.WriteLine($"  {rt.Type}: {rt.Count} reachable instance(s), {rt.Bytes / 1024.0:N0} KB");
        foreach (var root in rt.Roots.Take(1))
            Console.WriteLine($"    pinned by {root.Kind}: {root.Holder}{(root.Member is null ? "" : "." + root.Member)}");
    }

    var scenario = GetOpt(args, "--scenario") ?? "unlabelled scenario";
    int? iterations = GetOpt(args, "--iterations") is { } it && int.TryParse(it, out var n) ? n : null;
    var expected = suspects.ToDictionary(s => s, _ => 0);   // scenario objects should not survive
    var json = RuntimeReport.ToJson(result, scenario, iterations, expected);

    var outPath = GetOpt(args, "--out") ?? "runtime.json";
    File.WriteAllText(outPath, json);
    Console.WriteLine($"runtime.json written to {outPath} — fold it with:");
    Console.WriteLine("  python3 -m runtime.cli --findings <findings.json> --runtime " + outPath);
    return 0;
}

static void Usage()
{
    Console.WriteLine("own-audit — the OwnAudit CLI (this repo is the canonical audit home).");
    Console.WriteLine("  own-audit collect --pid <pid> [--findings findings.json | --types A,B]");
    Console.WriteLine("                    [--scenario \"label\"] [--iterations N] [--out runtime.json]");
    Console.WriteLine("                    [--max-chains N]");
    Console.WriteLine("      live-attach the ClrMD heap collector AFTER a scenario ran and emit the");
    Console.WriteLine("      runtime.json for runtime/correlate.py (docs/collector-plan.md)");
    Console.WriteLine("  own-audit config [--config <path>]   print the resolved audit config");
    Console.WriteLine("  own-audit run                        how to run the static audit over STS");
}

static string? GetOpt(string[] argv, string name)
{
    var i = Array.IndexOf(argv, name);
    return (i >= 0 && i + 1 < argv.Length) ? argv[i + 1] : null;
}
