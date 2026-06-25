<#
.SYNOPSIS
  Arm 1a — run OwnSharp (Own.NET) over STS and capture SARIF. Needs NO build of STS.

.DESCRIPTION
  Shells out to Own.NET's own-check.ps1 (-Format sarif) over the target repo. OwnSharp
  builds its OWN Roslyn compilation from source and honestly skips what it can't resolve
  (OWN050), so this runs even if the build spike fails. It is the leak BACKBONE and the
  first concrete audit task (PLAN.md "Task order" 1b) — and doubles as OwnSharp's biggest
  dogfood test: every false positive / miss on 600k real lines is an Own.NET issue.

.EXAMPLE
  spike\Invoke-OwnSharpOnSts.ps1
.EXAMPLE
  spike\Invoke-OwnSharpOnSts.ps1 -Target C:\Repos\STS_new\SectorTS\Broker
#>
[CmdletBinding()]
param(
    [string]$OwnNetRoot = "C:\Repos\Own.NET",
    [string]$Target     = "C:\Repos\STS_new",
    [ValidateSet("error", "warning")] [string]$Severity = "warning",
    [string]$OutDir     = (Join-Path $PSScriptRoot "..\artifacts")
)
$ErrorActionPreference = "Stop"

$check = Join-Path $OwnNetRoot "scripts\own-check.ps1"
if (-not (Test-Path $check))  { throw "own-check.ps1 not found at $check" }
if (-not (Test-Path $Target)) { throw "target not found at $Target" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$sarif = Join-Path $OutDir "ownsharp-sts.sarif"

Write-Host "OwnSharp -> $Target  (builds OwnSharp's own compilation; no STS build needed)"
# own-check.ps1 writes the SARIF to stdout when -Format sarif; capture it to a file.
# NB: pass the target via -Paths, NOT a `--` separator — under PowerShell's parameter
# binder a `--` mis-binds the path onto -Severity (own-check rc=2). -Paths is exact.
& $check -Root $OwnNetRoot -Format sarif -Severity $Severity -Paths $Target | Set-Content -LiteralPath $sarif -Encoding utf8
$rc = $LASTEXITCODE

$bytes = (Get-Item $sarif).Length
Write-Host "wrote $sarif ($bytes bytes; own-check rc=$rc — 0 clean / 1 findings / >=2 hard error)"
if ($rc -ge 2) { Write-Warning "own-check hard error — inspect the SARIF / drifted contract"; exit $rc }
Write-Host "Next: normalize this SARIF into the ranked suspect set (PLAN.md 'Arm 1 build-out')."
exit 0
