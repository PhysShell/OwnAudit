<#
.SYNOPSIS
  Reproduce the STS health report through Own.NET's CANONICAL audit/ pipeline.

.DESCRIPTION
  OwnAudit does not analyze code itself — the audit lives in Own.NET/audit/. This
  runner drives it end-to-end over STS:
    1. ensure a worktree of Own.NET main (audit/ + scripts/ + ownlang live there);
    2. OwnSharp over the target (build-free, no MSBuild/feed) -> SARIF;
    3. audit/aggregate: normalize -> score -> report -> markdown + HTML + json.
  PYTHONUTF8=1 sidesteps the cp1251-console crash on Russian-locale Windows
  (the STS target environment).

.EXAMPLE
  pwsh ./Run-Audit.ps1
.EXAMPLE
  pwsh ./Run-Audit.ps1 -Target C:\Repos\STS_new\SectorTS\Broker
#>
[CmdletBinding()]
param(
    [string]$OwnNet   = "C:\Repos\Own.NET",
    [string]$Ref      = "origin/main",
    [string]$Target   = "C:\Repos\STS_new\SectorTS",
    [string]$Worktree = "C:\Repos\_ownaudit\ownnet-main",
    [string]$Out      = (Join-Path $PSScriptRoot "artifacts")
)
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"   # report.py prints '>=' / '·' — crashes on a cp1251 console
New-Item -ItemType Directory -Force -Path $Out | Out-Null

# 1. worktree of main — audit/ is on main; the dev checkout may sit on a feature branch.
git -C $OwnNet fetch origin main -q
if (Test-Path (Join-Path $Worktree ".git")) {
    git -C $Worktree fetch origin main -q 2>$null
    git -C $Worktree checkout --detach $Ref 2>&1 | Out-Null
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path $Worktree) | Out-Null
    git -C $OwnNet worktree add --detach $Worktree $Ref
}
if (-not (Test-Path (Join-Path $Worktree "audit\aggregate\normalize.py"))) {
    throw "audit/ not found in $Worktree — is '$Ref' the branch that has audit/?"
}
python -m pip install --quiet pyyaml 2>&1 | Out-Null

# 2. OwnSharp (build-free) over the target -> SARIF. Run from the target's PARENT so the
#    SARIF uris are <leaf>/... (e.g. SectorTS/Broker/...); strip <leaf> for clean modules.
$sarif = Join-Path $Out "ownsharp.sarif"
$leaf  = Split-Path $Target -Leaf
Push-Location (Split-Path $Target -Parent)
try {
    & "$Worktree\scripts\own-check.ps1" -Root $Worktree -Format sarif -Severity warning -Paths $Target `
        1> $sarif 2> (Join-Path $Out "own-check.err")
} finally { Pop-Location }
$rc = $LASTEXITCODE
if (-not (Test-Path $sarif) -or (Get-Item $sarif).Length -lt 2) {
    throw "OwnSharp produced no SARIF (rc=$rc) — see $Out\own-check.err"
}
Write-Host "OwnSharp SARIF: $sarif ($((Get-Item $sarif).Length) bytes; rc=$rc)"

# 3. audit/ aggregation -> report (markdown + html + json), all views over one scored model.
$findings = Join-Path $Out "findings.json"
$commit   = (git -C $Target rev-parse --short HEAD 2>$null)
python "$Worktree\audit\aggregate\normalize.py" --sarif "own-check=$sarif" --strip "$leaf/" --json $findings
foreach ($fmt in @(@{f='markdown';e='md'}, @{f='html';e='html'}, @{f='json';e='json'})) {
    python "$Worktree\audit\aggregate\report.py" --findings $findings --format $fmt.f --target $leaf --commit $commit |
        Set-Content -LiteralPath (Join-Path $Out "health-report.$($fmt.e)") -Encoding utf8
}
Write-Host "Report: $Out\health-report.md  (+ .html, .json)"
