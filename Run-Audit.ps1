<#
.SYNOPSIS
  Reproduce the STS health report through Own.NET's CANONICAL audit/ pipeline.

.DESCRIPTION
  OwnAudit does not analyze code itself — the audit lives in Own.NET/audit/. This
  runner drives it end-to-end over STS:
    1. ensure a worktree of Own.NET main (audit/ + scripts/ + ownlang live there);
    2. OwnSharp over the target (build-free, no MSBuild/feed) -> SARIF;
    3. optionally CodeQL (--build-mode=none, also build-free) -> SARIF  [-Codeql];
    4. audit/aggregate: normalize -> score -> report -> markdown + HTML + json.
  Two build-free tools means cross-tool AGREEMENT: a site both flag becomes a
  high-confidence cluster (audit/ §3.5). PYTHONUTF8=1 dodges the cp1251 console crash.

.EXAMPLE
  pwsh ./Run-Audit.ps1                 # OwnSharp only (fast)
.EXAMPLE
  pwsh ./Run-Audit.ps1 -Codeql         # + CodeQL corroboration (reuses the DB if built)
.EXAMPLE
  pwsh ./Run-Audit.ps1 -Codeql -RebuildCodeqlDb -Target C:\Repos\STS_new\SectorTS\Broker
#>
[CmdletBinding()]
param(
    [string]$OwnNet    = "C:\Repos\Own.NET",
    [string]$Ref       = "origin/main",
    [string]$Target    = "C:\Repos\STS_new\SectorTS",
    [string]$Worktree  = "C:\Repos\_ownaudit\ownnet-main",
    [string]$Out       = (Join-Path $PSScriptRoot "artifacts"),
    [switch]$Codeql,
    [string]$CodeqlExe = "C:\Repos\codeql-bundle-win64\codeql\codeql.exe",
    [string]$CodeqlDb  = "C:\Repos\_ownaudit\codeql-db\sectorts",
    [switch]$RebuildCodeqlDb
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

$leaf = Split-Path $Target -Leaf
$sarifInputs = @()   # "tool=path" for normalize

# 2. OwnSharp (build-free) over the target -> SARIF. Run from the target's PARENT so the
#    SARIF uris are <leaf>/... ; audit/ matches by basename+line, so the prefix is moot.
$ownsarif = Join-Path $Out "ownsharp.sarif"
Push-Location (Split-Path $Target -Parent)
try {
    & "$Worktree\scripts\own-check.ps1" -Root $Worktree -Format sarif -Severity warning -Paths $Target `
        1> $ownsarif 2> (Join-Path $Out "own-check.err")
} finally { Pop-Location }
if (-not (Test-Path $ownsarif) -or (Get-Item $ownsarif).Length -lt 2) {
    throw "OwnSharp produced no SARIF — see $Out\own-check.err"
}
Write-Host "OwnSharp SARIF: $ownsarif ($((Get-Item $ownsarif).Length) bytes)"
$sarifInputs += "own-check=$ownsarif"

# 3. CodeQL (build-free, --build-mode=none) -> SARIF. The DB build is the slow step, so
#    reuse an existing DB unless -RebuildCodeqlDb. security-and-quality carries the
#    dispose/leak queries (the default 'security' suite returns zero leak findings).
if ($Codeql) {
    if (-not (Test-Path $CodeqlExe)) { throw "codeql.exe not found at $CodeqlExe (pass -CodeqlExe)" }
    if ($RebuildCodeqlDb -or -not (Test-Path (Join-Path $CodeqlDb "codeql-database.yml"))) {
        New-Item -ItemType Directory -Force -Path (Split-Path $CodeqlDb) | Out-Null
        Write-Host "CodeQL: building DB (build-free) over $Target — this is the slow step…"
        & $CodeqlExe database create $CodeqlDb --language=csharp --build-mode=none --source-root=$Target --overwrite
    } else {
        Write-Host "CodeQL: reusing DB at $CodeqlDb (-RebuildCodeqlDb to force)"
    }
    $cqsarif = Join-Path $Out "codeql.sarif"
    & $CodeqlExe database analyze $CodeqlDb --format=sarifv2.1.0 --output=$cqsarif --threads=0 `
        codeql/csharp-queries:codeql-suites/csharp-security-and-quality.qls
    Write-Host "CodeQL SARIF: $cqsarif"
    $sarifInputs += "codeql=$cqsarif"
}

# 4. audit/ aggregation -> report (markdown + html + json). Cross-tool agreement happens
#    automatically when both own-check and codeql findings cluster at the same site.
$findings = Join-Path $Out "findings.json"
$commit   = (git -C $Target rev-parse --short HEAD 2>$null)
$nargs = @()
foreach ($s in $sarifInputs) { $nargs += @("--sarif", $s) }
python "$Worktree\audit\aggregate\normalize.py" @nargs --strip "$leaf/" --json $findings
foreach ($fmt in @(@{f='markdown';e='md'}, @{f='html';e='html'}, @{f='json';e='json'})) {
    python "$Worktree\audit\aggregate\report.py" --findings $findings --format $fmt.f --target $leaf --commit $commit |
        Set-Content -LiteralPath (Join-Path $Out "health-report.$($fmt.e)") -Encoding utf8
}
Write-Host "Report: $Out\health-report.md  (+ .html, .json)  [tools: $($sarifInputs -join ', ')]"
