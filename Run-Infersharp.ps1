<#
.SYNOPSIS
  Run Infer# (build-required) over STS's own built binaries via the WSL2 infersharp
  distro, and write artifacts/infersharp.sarif for the audit to fold in.

.DESCRIPTION
  Infer# analyzes COMPILED binaries (.dll + .pdb) — build-required (audit/ §3.2). It
  copies the source-mappable STS assemblies (those with a .pdb — which skips the
  DevExpress / 3rd-party DLLs that ship no PDB and couldn't be source-mapped anyway)
  out of the build output, runs Infer# inside the WSL distro, and drops the SARIF where
  Run-Audit.ps1 folds it in. Infer#'s Pulse analysis is SLOW (minutes to hours,
  dominated by the big assemblies — Broker, BrokerDataClasses).

  Infer# reports a leak at the LAST-ACCESS line (the alloc line is in the message), so
  fold with a wider Run-Audit.ps1 -LineTol (e.g. 8) to cluster it with own-check/codeql.

.EXAMPLE
  pwsh ./Run-Infersharp.ps1
#>
[CmdletBinding()]
param(
    [string]$Setup  = "C:\Repos\STS_new\Setup",   # STS build output (.dll + .pdb)
    [string]$BinDir = "C:\Repos\_ownaudit\infer-bin",
    [string]$Distro = "infersharp1.4",
    [string]$Out    = (Join-Path $PSScriptRoot "artifacts")
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $Out | Out-Null

# Source-mappable STS assemblies = those with a matching PDB.
Remove-Item $BinDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
Get-ChildItem $Setup -Filter *.pdb | ForEach-Object {
    $dll = Join-Path $Setup ($_.BaseName + ".dll")
    if (Test-Path $dll) { Copy-Item $dll, $_.FullName $BinDir -Force }
}
$n = @(Get-ChildItem $BinDir -Filter *.dll).Count
Write-Host "Infer#: $n source-mappable assemblies -> $BinDir"

# Windows path -> WSL /mnt/c path (this env is on C:).
$toWsl   = { param($p) "/mnt/c/" + ($p -replace '^[A-Za-z]:\\', '' -replace '\\', '/') }
$wslBin  = & $toWsl $BinDir
$wslSarif = & $toWsl (Join-Path $Out "infersharp.sarif")

# Infer# writes infer-out/report.sarif relative to ~/infersharp; copy it to the artifacts.
wsl -d $Distro -- bash -lc "cd ~/infersharp && rm -rf infer-out && ./run_infersharp.sh $wslBin && cp infer-out/report.sarif $wslSarif && echo OK"
if (-not (Test-Path "$Out\infersharp.sarif")) { throw "Infer# produced no SARIF (wsl exit $LASTEXITCODE)" }
# Drop findings in third-party assemblies Infer# pulled in via their PDBs (paths like
# 'file:/_/BASE/src/...') and any generated files — keep STS code only.
$env:PYTHONUTF8 = '1'
python -c @"
import json,re
P=r'$Out\infersharp.sarif'
BAD=re.compile(r'(^|/)_/BASE/|/obj/|/bin/|\.g\.cs$|\.Designer\.cs$', re.I)
d=json.load(open(P,encoding='utf-8')); res=[]; drop=0
for r in d['runs']:
    for x in r.get('results',[]):
        try: u=x['locations'][0]['physicalLocation']['artifactLocation']['uri'].replace('\\','/')
        except Exception: u=''
        if BAD.search(u): drop+=1; continue
        res.append(x)
json.dump({'version':'2.1.0','runs':[{'tool':{'driver':{'name':'infersharp'}},'results':res}]}, open(P,'w',encoding='utf-8'))
print('infersharp: kept',len(res),'dropped',drop,'(third-party/generated)')
"@
Write-Host "Infer# SARIF: $Out\infersharp.sarif"
