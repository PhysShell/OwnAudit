<#
.SYNOPSIS
  Arm 1b — derisk headless analyzer SARIF on STS (PLAN.md "Task order" 1a). FIRST DRAFT.

.DESCRIPTION
  Proves the ANALYZER half of Arm 1 is viable on the legacy packages.config tree.
  Roslyn analyzers only emit during a successful compile, and STS is net472 / non-SDK /
  packages.config / x86 with private-feed packages (Cat.*/Sector.*) — so this is the
  load-bearing unknown. Steps:

    1. git worktree of STS (dev tree stays untouched, OUTSIDE both repos).
    2. restore ONE analyzer (IDisposableAnalyzers) to a temp cache.
    3. inject it via a root Directory.Build.targets using <Analyzer Include> — variant C,
       the only mechanism that flows analyzers into non-SDK/packages.config projects —
       plus ErrorLog (SARIF) + ReportAnalyzer.
    4. msbuild ONE leaf project headless; check a SARIF was emitted.
    5. tear the worktree down.

  GREEN -> analyzer SARIF works headless; scale step 2 to all analyzers + the whole sln.
  RED   -> Arm 1 leans on OwnSharp + the buildable subset (PLAN.md "Risks").

  PREREQUISITES (this is why it's a SPIKE — confirm as you go):
    * msbuild on PATH (Developer PowerShell, or VS Build Tools with net472 + WPF workloads).
    * nuget.exe on PATH (packages.config restore; dotnet restore won't cover non-SDK).
    * If restore needs the private feed, internal source is reachable via the ~/.claude
      AZDO helper:  & "C:\Repos\azr\scripts\azdo-fetch.ps1" -List -Collection next -Prefix Cat
#>
[CmdletBinding()]
param(
    [string]$StsRoot     = "C:\Repos\STS_new",
    [string]$Project     = "SectorTS\Core\Core.csproj",   # a leaf lib first, not the whole sln
    [string]$Analyzer    = "IDisposableAnalyzers",
    [string]$AnalyzerVer = "4.3.0",
    [string]$WorktreeDir = "C:\Repos\_ownaudit\STS_spike",
    [string]$Cache       = "C:\Repos\_ownaudit\analyzer-cache"
)
$ErrorActionPreference = "Stop"

$msbuild = (Get-Command msbuild -ErrorAction SilentlyContinue)?.Source
if (-not $msbuild) { throw "msbuild not on PATH — open a Developer PowerShell / install VS Build Tools (net472 + WPF)." }

# 1. worktree — STS dev copy untouched
if (Test-Path $WorktreeDir) { git -C $StsRoot worktree remove --force $WorktreeDir 2>$null }
New-Item -ItemType Directory -Force -Path (Split-Path $WorktreeDir) | Out-Null
git -C $StsRoot worktree add --detach $WorktreeDir HEAD

# 2. restore the analyzer to a temp cache, locate its C# analyzer dll(s)
New-Item -ItemType Directory -Force -Path $Cache | Out-Null
nuget install $Analyzer -Version $AnalyzerVer -OutputDirectory $Cache -DependencyVersion Ignore
$dlls = Get-ChildItem $Cache -Recurse -Filter *.dll | Where-Object { $_.FullName -match '[\\/]analyzers[\\/].*[\\/]cs[\\/]' }
if (-not $dlls) { throw "no analyzer dll under $Cache\...\analyzers\**\cs\ — check the package layout" }

# 3. inject via root Directory.Build.targets (variant C; non-SDK csproj import it too)
$sarifDir = Join-Path $WorktreeDir "artifacts\own-audit"
New-Item -ItemType Directory -Force -Path $sarifDir | Out-Null
$items = ($dlls | ForEach-Object { "    <Analyzer Include=`"$($_.FullName)`" />" }) -join "`n"
@"
<Project>
  <ItemGroup>
$items
  </ItemGroup>
  <PropertyGroup>
    <ErrorLog>$sarifDir\`$(MSBuildProjectName).sarif,version=2.1</ErrorLog>
    <ReportAnalyzer>true</ReportAnalyzer>
  </PropertyGroup>
</Project>
"@ | Set-Content -LiteralPath (Join-Path $WorktreeDir "Directory.Build.targets") -Encoding utf8

# 4. build ONE project headless (x86 — STS Platform)
& $msbuild (Join-Path $WorktreeDir $Project) /t:Rebuild /p:Configuration=Debug /p:Platform=x86 /m /v:m /bl:"$sarifDir\spike.binlog"
$rc = $LASTEXITCODE
$sarifs = @(Get-ChildItem $sarifDir -Filter *.sarif -ErrorAction SilentlyContinue)
Write-Host "msbuild rc=$rc; SARIF files emitted: $($sarifs.Count)"
if ($rc -eq 0 -and $sarifs.Count -gt 0) {
    Write-Host "SPIKE GREEN — analyzer SARIF emitted headless. Scale to all analyzers + Broker.sln."
} else {
    Write-Warning "SPIKE RED — inspect $sarifDir\spike.binlog (msbuild structured log). Fall back to OwnSharp-only on non-building projects."
}

# 5. teardown (comment out to inspect the worktree)
git -C $StsRoot worktree remove --force $WorktreeDir
exit $rc
