#Requires -Version 7
# PowerShell 7+ only, and stated where the ENGINE can act on it. Windows PowerShell
# 5.1 reads a BOM-less file as ANSI, so a non-ASCII byte used to surface as a syntax
# error in whatever word happened to contain it. This file is ASCII so 5.1 can read
# it, and this line is what 5.1 then reports instead: a refusal about versions.
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
  high-confidence cluster (audit/ section 3.5). PYTHONUTF8=1 dodges the cp1251 console crash.

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
    [int]$LineTol = 3                       # cluster window; raised to 8 automatically when
                                            # Infer#/Roslyn are folded in (scripts/LineTolPolicy.ps1).
                                            # Passing it explicitly always wins, including a lower value.
)
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"   # report.py prints '>=' and U+00B7 MIDDLE DOT - both crash a cp1251 console
New-Item -ItemType Directory -Force -Path $Out | Out-Null

# Read HERE, in this script's own scope: $PSBoundParameters describes this
# invocation and nothing further down can recover it. An explicitly passed
# -LineTol 3 is indistinguishable from the default by value, and the whole point
# of the policy below is that those two are not the same request.
$lineTolExplicit = $PSBoundParameters.ContainsKey('LineTol')
. (Join-Path (Join-Path $PSScriptRoot "scripts") "LineTolPolicy.ps1")

# 1. worktree of main - audit/ is on main; the dev checkout may sit on a feature branch.
git -C $OwnNet fetch origin main -q
if (Test-Path (Join-Path $Worktree ".git")) {
    git -C $Worktree fetch origin main -q 2>$null
    git -C $Worktree checkout --detach $Ref 2>&1 | Out-Null
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path $Worktree) | Out-Null
    git -C $OwnNet worktree add --detach $Worktree $Ref
}
if (-not (Test-Path (Join-Path $Worktree "audit\aggregate\report.py"))) {
    throw "audit/ not found in $Worktree - is '$Ref' the branch that has audit/?"
}
# pyyaml is for the WORKTREE's report.py (it still reads the YAML taxonomy through
# its own normalize.py). The local aggregate/normalize.py is stdlib-only.
python -m pip install --quiet pyyaml 2>&1 | Out-Null

$leaf = Split-Path $Target -Leaf
$sarifInputs = @()   # "tool=path" for normalize

# ---- provenance (producer-provenance/v1, Own.NET#266 slice 1B) ---------------
# SARIF carries no run identity, so occurrence identity has to come from outside
# it. The run id is stamped HERE, before any producer starts, so it names the
# ANALYSIS rather than the normalization - re-normalizing this same recorded run
# later reuses this manifest and reproduces the same occurrence ids. The
# normalizer never invents one: no manifest entry means occurrence_id: null, and
# the record says why.
#
# A GUID, not just a timestamp: two audits started in the same second would
# otherwise share producer run ids, and "rare" is not a property an identity
# contract may have. Determinism survives - the id is written to the manifest and
# read back from it, never recomputed.
$auditRunId   = "audit-{0}-{1}" -f [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ"),
                                   [Guid]::NewGuid().ToString("N")
$sourceCommit = (git -C $Target rev-parse HEAD 2>$null)
if ([string]::IsNullOrWhiteSpace($sourceCommit)) { $sourceCommit = $null }

# The analyzers read the WORKING TREE, not HEAD. On a dirty target `git rev-parse
# HEAD` still answers, and recording that answer would attribute findings to a
# commit that does not contain the analyzed bytes - the same fabrication as
# stamping a reused CodeQL database with today's commit, just harder to notice.
# Unknown is a value this schema carries, so it is recorded as unknown.
#
# Repo-wide rather than scoped to $Target: over-nulling costs a nullable field
# that blocks nothing, while under-nulling asserts something false, and a change
# outside the analyzed subtree can still be what the analyzed code depends on.
$dirty = @(git -C $Target status --porcelain 2>$null)
if ($sourceCommit -and $dirty.Count -gt 0) {
    # One string, one -f: the format operator binds tighter than '+', so a
    # concatenation of two format strings would silently format only the second one
    # and leave the first one's placeholders as literal text.
    $msg = "Target tree is dirty ({0} changed/untracked path(s)) - recording source_commit as null: the analyzed bytes are not the ones in {1}." -f $dirty.Count, $sourceCommit.Substring(0, 8)
    Write-Host $msg
    $sourceCommit = $null
}
$provenanceInputs = [ordered]@{}

function Add-Provenance {
    <#
      Record one producer. THIS SCRIPT ONLY VOUCHES FOR WHAT IT WATCHED HAPPEN.

      `-RunId` and `-SourceCommit` are passed explicitly, and are $null for SARIF
      the script merely FOUND in $Out. Infer# and Roslyn are produced by separate
      runners (Run-Infersharp.ps1 / Run-Roslyn.ps1), possibly yesterday, possibly
      against another commit and another configuration. Stamping them with this
      run's id and this checkout's HEAD would be provenance about an analysis
      nobody observed - precisely the fabricated identity the contract exists to
      prevent. So they get producer_name and input_digest, which are facts about
      the bytes on disk, and nothing else. Their occurrence ids stay null until
      those runners emit their own provenance sidecars.
    #>
    param(
        [Parameter(Mandatory)][string]$Tool,
        [Parameter(Mandatory)][string]$SarifPath,
        $RunId        = $null,
        $SourceCommit = $null,
        $Version      = $null,             # null, not "" - unknown must read as unknown
        $ConfigDigest = $null
    )
    # Lower-cased on purpose: Get-FileHash returns upper-case hex and the normalizer
    # compares the digest string verbatim, rejecting a mismatch outright. A case
    # difference would fail the whole run rather than degrade quietly - correct, but
    # a needless way to find out.
    $sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $SarifPath).Hash.ToLowerInvariant()
    $nz  = { param($v) if ([string]::IsNullOrWhiteSpace([string]$v)) { $null } else { [string]$v } }
    $script:provenanceInputs[$Tool] = [ordered]@{
        producer_run_id  = & $nz $RunId
        producer_name    = $Tool
        producer_version = & $nz $Version
        input_digest     = "sha256:$sha"
        config_digest    = & $nz $ConfigDigest
        source_commit    = & $nz $SourceCommit
    }
}

# 2. OwnSharp (build-free) over the target -> SARIF. Run from the target's PARENT so the
#    SARIF uris are <leaf>/... ; audit/ matches by basename+line, so the prefix is moot.
$ownsarif = Join-Path $Out "ownsharp.sarif"
Push-Location (Split-Path $Target -Parent)
try {
    & "$Worktree\scripts\own-check.ps1" -Root $Worktree -Format sarif -Severity warning -Paths $Target `
        1> $ownsarif 2> (Join-Path $Out "own-check.err")
} finally { Pop-Location }
if (-not (Test-Path $ownsarif) -or (Get-Item $ownsarif).Length -lt 2) {
    throw "OwnSharp produced no SARIF - see $Out\own-check.err"
}
Write-Host "OwnSharp SARIF: $ownsarif ($((Get-Item $ownsarif).Length) bytes)"
$sarifInputs += "own-check=$ownsarif"
# Produced by THIS run, right here: the run id and the target HEAD are both observed.
Add-Provenance -Tool "own-check" -SarifPath $ownsarif -RunId "$auditRunId/own-check" -SourceCommit $sourceCommit

# 3. CodeQL (build-free, --build-mode=none) -> SARIF. The DB build is the slow step, so
#    reuse an existing DB unless -RebuildCodeqlDb. security-and-quality carries the
#    dispose/leak queries (the default 'security' suite returns zero leak findings).
if ($Codeql) {
    if (-not (Test-Path $CodeqlExe)) { throw "codeql.exe not found at $CodeqlExe (pass -CodeqlExe)" }
    # Tracked because it decides whether this run may claim the target's commit for
    # the CodeQL results: a reused DB was built from a tree this script never saw.
    $codeqlDbBuiltNow = $false
    if ($RebuildCodeqlDb -or -not (Test-Path (Join-Path $CodeqlDb "codeql-database.yml"))) {
        New-Item -ItemType Directory -Force -Path (Split-Path $CodeqlDb) | Out-Null
        Write-Host "CodeQL: building DB (build-free) over $Target - this is the slow step..."
        & $CodeqlExe database create $CodeqlDb --language=csharp --build-mode=none --source-root=$Target --overwrite
        $codeqlDbBuiltNow = $true
    } else {
        Write-Host "CodeQL: reusing DB at $CodeqlDb (-RebuildCodeqlDb to force) - its source commit is unknown to this run"
    }
    $cqsarif = Join-Path $Out "codeql.sarif"
    # security-and-quality is the practical max for a desktop app; -Strict adds the
    # experimental suite (marginal here - mostly web-shaped queries - but complete).
    $suites = @("codeql/csharp-queries:codeql-suites/csharp-security-and-quality.qls")
    if ($Strict) { $suites += "codeql/csharp-queries:codeql-suites/csharp-security-experimental.qls" }
    & $CodeqlExe database analyze $CodeqlDb --format=sarifv2.1.0 --output=$cqsarif --threads=0 @suites
    Write-Host "CodeQL SARIF: $cqsarif  [$($suites.Count) suite(s)]"
    $sarifInputs += "codeql=$cqsarif"
    # The ANALYSIS ran here, so the run id is this run's. The commit is a different
    # question: results come from the DB, and a reused DB was built from a tree this
    # script never saw. Claiming the current HEAD for it would be a guess wearing a
    # commit hash, so it is null unless the DB was built in this run.
    # producer_version is left unset: CodeQL states its semanticVersion in the SARIF
    # driver, and the normalizer reads it from there rather than having it asserted twice.
    Add-Provenance -Tool "codeql" -SarifPath $cqsarif -RunId "$auditRunId/codeql" `
        -SourceCommit $(if ($codeqlDbBuiltNow) { $sourceCommit } else { $null })
}

# Infer# (build-required) - fold in if a SARIF is present. Produce it first with
# Run-Infersharp.ps1 (WSL). Infer# reports at the last-access line, so the clustering
# window is raised to 8 below unless -LineTol was passed explicitly.
if (Test-Path (Join-Path $Out "infersharp.sarif")) {
    Write-Host "Infer# SARIF: $Out\infersharp.sarif (folding in)"
    $sarifInputs += "infersharp=$(Join-Path $Out 'infersharp.sarif')"
    # Found, not produced: no run id, no commit. See Add-Provenance's note.
    Add-Provenance -Tool "infersharp" -SarifPath (Join-Path $Out 'infersharp.sarif')
}

# Roslyn analyzer packs (build-required) - fold in if a SARIF is present. Produce it
# first with Run-Roslyn.ps1 (VS2022 build). High volume and shifted/generated locations,
# so the clustering window is raised to 8 below unless -LineTol was passed explicitly.
if (Test-Path (Join-Path $Out "roslyn.sarif")) {
    Write-Host "Roslyn SARIF: $Out\roslyn.sarif (folding in)"
    $sarifInputs += "roslyn=$(Join-Path $Out 'roslyn.sarif')"
    # Found, not produced: no run id, no commit. See Add-Provenance's note.
    Add-Provenance -Tool "roslyn" -SarifPath (Join-Path $Out 'roslyn.sarif')
}

# The folding above is automatic; the clustering window it needs used to be manual.
# Resolve it now that the input set is final - Infer# and Roslyn report shifted or
# generated locations, so at the default window one defect splits into several
# findings. An explicitly passed -LineTol is honoured exactly, including when it is
# lower than those tools want: the mismatch is reported, never corrected behind the
# caller's back. See scripts/LineTolPolicy.ps1 and OwnAudit#59.
$tolDecision = Resolve-LineTol -Requested $LineTol -Explicit $lineTolExplicit `
                               -Tools @($sarifInputs | ForEach-Object { ($_ -split '=', 2)[0] })
if ($tolDecision.Message) { Write-Host $tolDecision.Message }
if ($tolDecision.Warning) { Write-Warning $tolDecision.Warning }
$LineTol = $tolDecision.Value

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
# Persist the manifest next to the artifacts it describes. Keep it: re-normalizing
# this recorded run WITHOUT it produces occurrence_id: null everywhere, because the
# normalizer will not mint a run id of its own - and it should not, since a run id
# minted at normalization time would describe the normalization instead.
$manifest = Join-Path $Out "provenance.json"
@{ schema_version = "producer-provenance/v1"; inputs = $provenanceInputs } |
    ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifest -Encoding utf8
$withRun = @($provenanceInputs.Values | Where-Object { $_.producer_run_id }).Count
Write-Host "Provenance manifest: $manifest ($auditRunId; $withRun of $($provenanceInputs.Count) producer(s) carry a run id - the rest are pre-existing SARIF and their occurrence ids stay null)"
python "$PSScriptRoot\aggregate\normalize.py" @nargs --strip "$leaf" --strip $absStrip --strip "/$absStrip" --provenance $manifest --json $findings
foreach ($fmt in @(@{f='markdown';e='md'}, @{f='html';e='html'}, @{f='json';e='json'})) {
    python "$Worktree\audit\aggregate\report.py" --findings $findings --format $fmt.f --target $leaf --commit $commit --line-tol $LineTol |
        Set-Content -LiteralPath (Join-Path $Out "health-report.$($fmt.e)") -Encoding utf8
}
Write-Host "Report: $Out\health-report.md  (+ .html, .json)  [tools: $($sarifInputs -join ', '); line-tol $LineTol]"
