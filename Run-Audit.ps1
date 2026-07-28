<#
.SYNOPSIS
  Reproduce the STS health report: Own.NET analyzes, OwnAudit aggregates and reports.

.DESCRIPTION
  Own.NET is the SAST engine (it emits SARIF); the audit pipeline is here. This
  runner drives the whole thing end-to-end over STS:
    1. ensure a worktree of Own.NET main (scripts/ + ownlang live there);
    2. OwnSharp over the target (build-free, no MSBuild/feed) -> SARIF;
    3. optionally CodeQL (--build-mode=none, also build-free) -> SARIF  [-Codeql];
    4. aggregate/normalize.py (LOCAL) -> findings.json, then score -> report.
  Normalization no longer runs out of the Own.NET worktree: it was ported into
  aggregate/ (Own.NET#266 slice 1A) and produces byte-identical findings.json.
  Scoring/reporting still run from the worktree until they are ported too.
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
    [switch]$Strict,                       # CodeQL: + security-experimental suite
    [string]$CodeqlExe = "C:\Repos\codeql-bundle-win64\codeql\codeql.exe",
    [string]$CodeqlDb  = "C:\Repos\_ownaudit\codeql-db\sectorts",
    [switch]$RebuildCodeqlDb,
    [int]$LineTol = 3                       # cluster window; use ~8 when folding Infer#
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
if (-not (Test-Path (Join-Path $Worktree "audit\aggregate\report.py"))) {
    throw "audit/ not found in $Worktree — is '$Ref' the branch that has audit/?"
}
# pyyaml is for the WORKTREE's report.py (it still reads the YAML taxonomy through
# its own normalize.py). The local aggregate/normalize.py is stdlib-only.
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
    # security-and-quality is the practical max for a desktop app; -Strict adds the
    # experimental suite (marginal here — mostly web-shaped queries — but complete).
    $suites = @("codeql/csharp-queries:codeql-suites/csharp-security-and-quality.qls")
    if ($Strict) { $suites += "codeql/csharp-queries:codeql-suites/csharp-security-experimental.qls" }
    & $CodeqlExe database analyze $CodeqlDb --format=sarifv2.1.0 --output=$cqsarif --threads=0 @suites
    Write-Host "CodeQL SARIF: $cqsarif  [$($suites.Count) suite(s)]"
    $sarifInputs += "codeql=$cqsarif"
}

# Infer# (build-required) — fold in if a SARIF is present. Produce it first with
# Run-Infersharp.ps1 (WSL). Infer# reports at the last-access line, so use -LineTol ~8.
if (Test-Path (Join-Path $Out "infersharp.sarif")) {
    Write-Host "Infer# SARIF: $Out\infersharp.sarif (folding in)"
    $sarifInputs += "infersharp=$(Join-Path $Out 'infersharp.sarif')"
}

# Roslyn analyzer packs (build-required) — fold in if a SARIF is present. Produce it
# first with Run-Roslyn.ps1 (VS2022 build). High volume; use -LineTol 8 with it.
if (Test-Path (Join-Path $Out "roslyn.sarif")) {
    Write-Host "Roslyn SARIF: $Out\roslyn.sarif (folding in)"
    $sarifInputs += "roslyn=$(Join-Path $Out 'roslyn.sarif')"
}

# 4. aggregation -> report (markdown + html + json). Cross-tool agreement happens
#    automatically when both own-check and codeql findings cluster at the same site.
#    normalize is LOCAL (aggregate/); report.py still comes from the worktree.
$findings = Join-Path $Out "findings.json"
$commit   = (git -C $Target rev-parse --short HEAD 2>$null)
$nargs = @()
foreach ($s in $sarifInputs) { $nargs += @("--sarif", $s) }
# Three tools, three path shapes: own-check '<leaf>/...', codeql '<leaf-relative>',
# Infer# absolute 'C:/.../<leaf>/...'. Strip both leaf prefixes so modules align in the
# heatmap (clustering itself is basename-based, so this only cleans the labels).
# norm_path strips file:// FIRST, so roslyn 'file:///C:/...' becomes '/C:/...'. Pass all
# three shapes ('<leaf>/...', 'C:/.../<leaf>', '/C:/.../<leaf>') so every tool's modules align.
$absStrip = ($Target -replace '\\', '/').TrimEnd('/')
python "$PSScriptRoot\aggregate\normalize.py" @nargs --strip "$leaf" --strip $absStrip --strip "/$absStrip" --json $findings
foreach ($fmt in @(@{f='markdown';e='md'}, @{f='html';e='html'}, @{f='json';e='json'})) {
    python "$Worktree\audit\aggregate\report.py" --findings $findings --format $fmt.f --target $leaf --commit $commit --line-tol $LineTol |
        Set-Content -LiteralPath (Join-Path $Out "health-report.$($fmt.e)") -Encoding utf8
}
Write-Host "Report: $Out\health-report.md  (+ .html, .json)  [tools: $($sarifInputs -join ', '); line-tol $LineTol]"
