using OwnAudit.Core;

namespace OwnAudit.Runtime;

/// A deterministic UI scenario for Arm 2 (authored as YAML, drafted by AI, asserts
/// are EXACT — never AI-judged). Mirrors PLAN.md "Arm 2 scenario format".
public sealed record Scenario(string Name, int Repeat, IReadOnlyList<string> Steps)
{
    /// Suspect type name -> max retained instances allowed after the scenario + forced GC.
    public IReadOnlyDictionary<string, int> RetainedBudget { get; init; }
        = new Dictionary<string, int>();
}

/// Proof that a suspect leaks (or doesn't): the retained-instance delta across the
/// scenario, plus the GC root path ClrMD found for any survivor.
public sealed record RetentionProof(string TypeName, int RetainedDelta, string? GcRootPath, bool Leaks);

/// Arm 2 — runtime proof of the TOP suspects only (minimal-touch: FlaUI drives the
/// built STS exe, ClrMD counts retained instances + gcroots the survivors). At most
/// SemantixTrace's AutoAutomationId is added if FlaUI can't navigate; breadcrumbs +
/// the Rust oracle are deferred. FlaUI.UIA3 + Microsoft.Diagnostics.Runtime package
/// refs are added in the Arm-2 build-out phase, not at scaffold time. See PLAN.md "Arm 2".
public sealed class RuntimeArm
{
    private readonly AuditConfig _cfg;
    public RuntimeArm(AuditConfig cfg) => _cfg = cfg;

    public IReadOnlyList<RetentionProof> Prove(Scenario scenario, IEnumerable<string> suspectTypes)
    {
        // FlaUI: launch the STS WinExe (x86), run scenario.Steps x Repeat, ForceGC.
        // ClrMD: snapshot before/after (x64 runner reads the x86 dump), count instances
        //        of suspectTypes, gcroot the survivors.
        // TODO(PLAN §"Arm 2 build-out"): add FlaUI.UIA3 + Microsoft.Diagnostics.Runtime
        // and implement the drive + heap-diff loop.
        throw new NotImplementedException("RuntimeArm.Prove is gated on the Arm-2 build-out phase (PLAN.md).");
    }
}
