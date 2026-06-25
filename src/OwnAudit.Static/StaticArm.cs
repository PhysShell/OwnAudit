using OwnAudit.Core;

namespace OwnAudit.Static;

/// Arm 1 — static aggregation. Runs OwnSharp (backbone) + the injected Roslyn
/// analyzers (breadth, once the build spike is green), normalizes both SARIF streams
/// into one Finding set, merges co-located findings (corroboration), and ranks.
/// See PLAN.md "Arm 1".
public sealed class StaticArm
{
    private readonly AuditConfig _cfg;
    public StaticArm(AuditConfig cfg) => _cfg = cfg;

    /// Produce the ranked suspect set for the target.
    ///
    /// SCAFFOLD STATUS: only the OwnSharp invocation seam (<see cref="OwnSharpRunner"/>)
    /// is wired. SARIF normalization, analyzer injection (variant C) and ranking land
    /// in the Arm-1 build-out phase. Run spike/Invoke-OwnSharpOnSts.ps1 for the
    /// OwnSharp pass today.
    public IReadOnlyList<Finding> Aggregate()
    {
        // 1. OwnSharp over the whole target (no build) -> SARIF.
        // 2. Roslyn analyzers over the buildable projects (variant C) -> SARIF.
        // 3. Normalize(ownSharpSarif, analyzerSarif) -> Finding[]  (merge co-located).
        // 4. Rank: leakClassWeight * corroboration * blast(Window/VM, instance-heavy).
        // TODO(PLAN §"Arm 1 build-out"): implement 1-4.
        throw new NotImplementedException(
            "StaticArm.Aggregate is gated on the Arm-1 build-out phase (PLAN.md). " +
            "Use spike/Invoke-OwnSharpOnSts.ps1 for the OwnSharp backbone pass today.");
    }
}
