"""OwnAudit — Fix arm (Arm 3). Audit-grade safety wrapper around off-the-shelf
mass fix appliers. See ../docs/fix-arm.md. The applier engine is NOT ours
(roslynator fix / dotnet format); this package is the select -> dry-run -> diff
-> re-audit -> tier-gate contract that makes mass-apply honest."""
