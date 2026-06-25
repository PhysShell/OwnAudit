<#
.SYNOPSIS
  Run the NuGet Roslyn analyzer packs (build-required tier) over STS via VS2022 and
  write artifacts/roslyn.sarif for the audit to fold in.

.DESCRIPTION
  Roslyn analyzers run DURING compilation, so this rebuilds the target with the packs
  injected (canonical inject props, gated on /p:OwnAudit=true) plus an is_global config
  that downgrades every analyzer diagnostic to 'warning' (so an error-default rule like
  Meziantou MA0037 is COLLECTED, not build-breaking — real CS#### errors still fail).

  Needs VS2022 BuildTools (Roslyn 4.x): the modern packs no-load on VS2019/Roslyn 3.x
  (Gu.Roslyn.Extensions version conflict). Each pack is cached in its OWN subdir so it
  resolves its own Gu version (flattening them into one dir is what caused 67k AD0001).
  Continue-on-error: a project that fails still leaves the SARIFs built before it.
  NOTE: does a Debug rebuild into the target's Setup\ output.

.EXAMPLE
  pwsh ./Run-Roslyn.ps1                 # reuse the analyzer cache
.EXAMPLE
  pwsh ./Run-Roslyn.ps1 -RestorePacks   # (re)restore the packs first
#>
[CmdletBinding()]
param(
    [string]$Solution = "C:\Repos\STS_new\Broker.sln",
    [string]$Cache    = "C:\Repos\_ownaudit\ac2022",
    [string]$Inject   = (Join-Path $PSScriptRoot "roslyn-inject"),
    [string]$Out      = (Join-Path $PSScriptRoot "artifacts"),
    [string[]]$Packs  = @('IDisposableAnalyzers', 'PropertyChangedAnalyzers', 'WpfAnalyzers',
                          'Roslynator.Analyzers', 'Meziantou.Analyzer', 'AsyncFixer',
                          'Microsoft.CodeAnalysis.NetAnalyzers'),
    [switch]$RestorePacks
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$msbuild = (& $vswhere -products * -version "[17.0,18.0)" -latest -find "MSBuild\**\Bin\MSBuild.exe" 2>$null | Select-Object -First 1)
if (-not $msbuild) { throw "VS2022 msbuild not found — BuildTools 17.x (Roslyn 4.x) is required for the modern packs." }
$nuget = 'C:\Repos\_ownaudit\tools\nuget.exe'

# 1. per-pack analyzer cache (each pack in its OWN subdir -> its own Gu.Roslyn.Extensions)
if ($RestorePacks -or -not (Test-Path $Cache)) {
    $raw = "$Cache-raw"; New-Item -ItemType Directory -Force $raw, $Cache | Out-Null
    if (-not (Test-Path $nuget)) { Invoke-WebRequest 'https://dist.nuget.org/win-x86-commandline/latest/nuget.exe' -OutFile $nuget }
    foreach ($id in $Packs) { & $nuget install $id -OutputDirectory $raw -DependencyVersion Ignore -NonInteractive *> $null }
    foreach ($id in $Packs) {
        $pkg = Get-ChildItem $raw -Directory -Filter "$id.*" | Sort-Object Name -Descending | Select-Object -First 1
        if ($pkg) {
            $cs = Get-ChildItem $pkg.FullName -Recurse -Directory | Where-Object { $_.Name -eq 'cs' -and $_.FullName -match '\\analyzers\\' } | Select-Object -First 1
            if ($cs) { $d = Join-Path $Cache $id; New-Item -ItemType Directory -Force $d | Out-Null; Copy-Item "$($cs.FullName)\*.dll" $d -Force }
        }
    }
    Write-Host "Analyzer cache built: $((@(Get-ChildItem $Cache -Directory)).Count) packs in $Cache"
}

# 2. build the sln with analyzers injected (one SARIF per project under $Out\rsln\roslyn)
$rsln = Join-Path $Out "rsln"; New-Item -ItemType Directory -Force "$rsln\roslyn" | Out-Null
& $msbuild $Solution /t:Rebuild /p:Configuration=Debug /p:OwnAudit=true /p:OwnAuditAnalyzers=$Cache /p:OwnAuditOutDir=$rsln `
    /p:DirectoryBuildPropsPath="$Inject\OwnAudit.Directory.Build.props" /p:DirectoryBuildTargetsPath="$Inject\OwnAudit.Directory.Build.targets" `
    /m /v:q /nologo /clp:ErrorsOnly
Write-Host "msbuild rc=$LASTEXITCODE (continue-on-error: partial SARIF is still folded)"

# 3. merge the non-_wpftmp per-project SARIFs into one roslyn.sarif
python -c @"
import json,glob,os
files=[f for f in glob.glob(os.path.join(r'$rsln','roslyn','*.sarif')) if '_wpftmp' not in f]
res=[]
for f in files:
    d=json.load(open(f,encoding='utf-8'))
    for r in d.get('runs',[]): res+=r.get('results',[])
json.dump({'version':'2.1.0','runs':[{'tool':{'driver':{'name':'roslyn'}},'results':res}]},
          open(os.path.join(r'$Out','roslyn.sarif'),'w',encoding='utf-8'))
print('merged',len(files),'projects ->',len(res),'findings into roslyn.sarif')
"@
Write-Host "Roslyn SARIF: $Out\roslyn.sarif  (Run-Audit.ps1 folds it; use -LineTol 8)"
