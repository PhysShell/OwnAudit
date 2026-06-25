using System.Text.Json;

namespace OwnAudit.Core;

/// Static configuration for a one-shot audit run, loaded from config/ownaudit.json.
/// The HARD WALL lives here: OwnAudit only ever NAMES the Own.NET checkout and its
/// CLI script — it never references core source. Own.NET stays byte-for-byte unchanged.
public sealed class AuditConfig
{
    /// Own.NET checkout. Consumed only via its CLI artifacts; stays untouched.
    public string OwnNetRoot { get; set; } = "";

    /// own-check.ps1 inside OwnNetRoot — the OwnSharp + core SARIF seam.
    public string OwnCheckScript { get; set; } = "scripts/own-check.ps1";

    /// The .sln being audited (used by the build spike / analyzer arm).
    public string TargetSolution { get; set; } = "";

    /// The target repo root (OwnSharp walks this for *.cs; needs no build).
    public string TargetRoot { get; set; } = "";

    /// Roslyn analyzer packages injected (variant C) once the build spike is green.
    public string[] Analyzers { get; set; } = Array.Empty<string>();

    /// Where SARIF logs and the dossier are written (OwnAudit-relative).
    public string ArtifactsDir { get; set; } = "artifacts";

    private static readonly JsonSerializerOptions Opts = new()
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
    };

    public static AuditConfig Load(string path) =>
        JsonSerializer.Deserialize<AuditConfig>(File.ReadAllText(path), Opts)
        ?? throw new InvalidOperationException($"empty/invalid config: {path}");
}
