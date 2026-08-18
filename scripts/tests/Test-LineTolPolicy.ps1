<#
.SYNOPSIS
  The `--line-tol` decision matrix (OwnAudit#59), pinned without running an
  analyzer.

.DESCRIPTION
  `Run-Audit.ps1` needs a build, a worktree, CodeQL and a Windows stand to run at
  all, so the tolerance rule could never be exercised as part of it. Extracting
  `Resolve-LineTol` into a pure function makes the decision testable on its own,
  which is the only way this matrix runs on every push instead of the day someone
  happens to have a stand.

  No Pester: OwnAudit's CI installs no packages, and the Python suites are bare
  `python3` for the same reason. ASCII-only output; explicit exit code.

.EXAMPLE
  pwsh scripts/tests/Test-LineTolPolicy.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path (Split-Path $PSScriptRoot -Parent) 'LineTolPolicy.ps1')

$script:Fails = @()
$script:Skips = @()
$script:Count = 0

function Check {
    param([bool]$Ok, [string]$Message)
    $script:Count++
    if (-not $Ok) { $script:Fails += $Message }
}

function Skip {
    # Loudly, never silently: a skipped check that prints nothing reads exactly
    # like a passing one. Same rule the Python suites here follow.
    param([string]$Message)
    $script:Skips += $Message
}

function Case {
    <#  One row of the matrix: inputs -> expected effective tolerance.  #>
    param(
        [string]$Name,
        [int]$Requested,
        [bool]$Explicit,
        [string[]]$Tools,
        [int]$Expect,
        [bool]$ExpectRaised = $false,
        [bool]$ExpectWarning = $false
    )
    $r = Resolve-LineTol -Requested $Requested -Explicit $Explicit -Tools $Tools
    Check ($r.Value -eq $Expect) "$Name : effective tolerance $($r.Value), want $Expect"
    Check ($r.Raised -eq $ExpectRaised) "$Name : Raised=$($r.Raised), want $ExpectRaised"
    Check (($null -ne $r.Warning) -eq $ExpectWarning) `
          "$Name : warning present=$($null -ne $r.Warning), want $ExpectWarning"
    # An automatic change must announce itself. A silent raise is the same class of
    # defect as a silent override, only in the other direction.
    if ($ExpectRaised) {
        Check ($null -ne $r.Message) "$Name : an automatic raise must say so on stdout"
    }
}

# ---- The matrix from the issue ---------------------------------------------
# The default of 3 is what `Run-Audit.ps1` declares; 8 is what AGENTS.md asks for
# when Infer# or Roslyn are folded in.

Case -Name 'nothing extra, implicit'    -Requested 3 -Explicit $false -Tools @('own-check') -Expect 3
Case -Name 'codeql only, implicit'      -Requested 3 -Explicit $false -Tools @('own-check','codeql') -Expect 3
Case -Name 'infersharp, implicit'       -Requested 3 -Explicit $false -Tools @('own-check','infersharp') -Expect 8 -ExpectRaised $true
Case -Name 'roslyn, implicit'           -Requested 3 -Explicit $false -Tools @('own-check','roslyn') -Expect 8 -ExpectRaised $true
Case -Name 'both shifted, implicit'     -Requested 3 -Explicit $false -Tools @('own-check','infersharp','roslyn') -Expect 8 -ExpectRaised $true
Case -Name 'roslyn + explicit 3'        -Requested 3 -Explicit $true  -Tools @('own-check','roslyn') -Expect 3 -ExpectWarning $true
Case -Name 'infersharp + explicit 12'   -Requested 12 -Explicit $true -Tools @('own-check','infersharp') -Expect 12

# ---- The distinctions the matrix rows depend on -----------------------------

# An explicitly passed value that HAPPENS to equal the default is still explicit.
# This is the whole reason the caller must read $PSBoundParameters rather than
# compare against 3: the two cases are indistinguishable by value.
$implicit3 = Resolve-LineTol -Requested 3 -Explicit $false -Tools @('roslyn')
$explicit3 = Resolve-LineTol -Requested 3 -Explicit $true  -Tools @('roslyn')
Check ($implicit3.Value -eq 8 -and $explicit3.Value -eq 3) `
      "an explicit 3 and a defaulted 3 must not resolve alike (got $($implicit3.Value)/$($explicit3.Value))"

# An explicit value is never rewritten, in either direction.
Check ((Resolve-LineTol -Requested 1 -Explicit $true -Tools @('roslyn','infersharp')).Value -eq 1) `
      "an explicit 1 must survive both shifted tools"
Check ((Resolve-LineTol -Requested 99 -Explicit $true -Tools @()).Value -eq 99) `
      "an explicit 99 must survive with no shifted tools"

# An explicit value at or above the threshold is not worth warning about.
Check ($null -eq (Resolve-LineTol -Requested 8 -Explicit $true -Tools @('roslyn')).Warning) `
      "an explicit 8 with roslyn needs no warning"
Check ($null -eq (Resolve-LineTol -Requested 12 -Explicit $true -Tools @('infersharp')).Warning) `
      "an explicit 12 with infersharp needs no warning"

# ...and neither is a low explicit value when nothing shifted was folded in.
Check ($null -eq (Resolve-LineTol -Requested 2 -Explicit $true -Tools @('own-check','codeql')).Warning) `
      "an explicit 2 without shifted tools needs no warning"

# The trigger is reported so a reader can check the attribution instead of
# trusting it, and it names every shifted tool, not just the first one found.
$both = Resolve-LineTol -Requested 3 -Explicit $false -Tools @('roslyn','own-check','infersharp')
Check (($both.Trigger -join ',') -eq 'infersharp,roslyn') `
      "both shifted tools must be named, sorted: got '$($both.Trigger -join ',')'"
Check ($both.Message -match 'infersharp' -and $both.Message -match 'roslyn') `
      "the raise message must name what triggered it"

# Tool names are matched case-insensitively: the caller builds this list from
# strings it also uses as SARIF keys, and a capitalised spelling must not silently
# stop triggering the policy.
Check ((Resolve-LineTol -Requested 3 -Explicit $false -Tools @('Roslyn')).Value -eq 8) `
      "tool matching must be case-insensitive"

# An unknown tool is not a shifted-location tool. Failing open here would raise
# the window for producers nobody has measured.
Check ((Resolve-LineTol -Requested 3 -Explicit $false -Tools @('own-check','semgrep')).Value -eq 3) `
      "an unrecognised tool must not trigger the raise"

# No tools at all is a coherent state (the caller may be re-reporting), not a crash.
Check ((Resolve-LineTol -Requested 3 -Explicit $false -Tools @()).Value -eq 3) `
      "an empty tool list must resolve to the requested value"

# ---- Encoding: these files must be pure ASCII -------------------------------
# Windows PowerShell 5.1 reads a BOM-less .ps1 in the system ANSI codepage, not
# UTF-8. A single em dash in a comment therefore arrives as mojibake and takes the
# PARSER down -- the policy cannot even be dot-sourced, so a stand on 5.1 gets a
# crash rather than a tolerance. That is exactly how this suite first failed on
# the windows-latest/5.1 leg.
#
# A UTF-8 BOM would also fix it, but ASCII is the one answer that does not depend
# on BOM handling surviving an editor, a git filter or a copy-paste. The Python
# suites here are ASCII-only for the same reason.
foreach ($f in @((Join-Path (Split-Path $PSScriptRoot -Parent) 'LineTolPolicy.ps1'),
                 (Join-Path $PSScriptRoot 'Test-LineTolPolicy.ps1'))) {
    $bytes = [System.IO.File]::ReadAllBytes($f)
    $high  = @($bytes | Where-Object { $_ -gt 127 })
    # Parenthesise the concatenation BEFORE -f: the format operator binds tighter
    # than '+', so `"a{0}" + "b" -f $x` formats only "b" and leaves {0} literal.
    # Run-Audit.ps1 already carries a comment about this trap; it is easy to fall
    # into anyway, and it only shows up on the failure path.
    Check ($high.Count -eq 0) `
          (("{0}: {1} non-ASCII byte(s) -- Windows PowerShell 5.1 will mis-decode this file " +
            "and fail to parse it") -f (Split-Path $f -Leaf), $high.Count)
}

# ---- The wiring in Run-Audit.ps1 --------------------------------------------
# The pure function can be right while the caller uses it wrongly, and the caller
# cannot be executed here: it fetches a worktree, builds, and wants a Windows
# stand. So the two things that would break silently are checked directly.

$runAudit = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'Run-Audit.ps1'
Check (Test-Path $runAudit) "Run-Audit.ps1 not found at $runAudit"

# 1. Tool names are derived from the "tool=path" strings the script accumulates.
#    A Windows path carries backslashes, spaces and a drive colon, so pin the
#    split against a realistic one rather than a tidy fixture.
$sarifInputs = @(
    'own-check=C:\Repos\_ownaudit\artifacts\own.sarif',
    'roslyn=C:\Program Files\Out Dir\roslyn.sarif'
)
$derived = @($sarifInputs | ForEach-Object { ($_ -split '=', 2)[0] })
Check (($derived -join ',') -eq 'own-check,roslyn') `
      "tool extraction from 'tool=path' broke: got '$($derived -join ',')'"
Check ((Resolve-LineTol -Requested 3 -Explicit $false -Tools $derived).Value -eq 8) `
      "a roslyn entry with a spacey Windows path must still trigger the raise"

# 2. The AST, for the two facts a unit test cannot reach: explicitness is read in
#    the script's OWN scope, and the decision is made AFTER the folding blocks
#    (resolving earlier would consult a tool list that is not final yet).
#
#    These run on EVERY edition now, 5.1 included. They used to be skipped there:
#    `Run-Audit.ps1` carried 23 non-ASCII characters and 5.1 reads a BOM-less file
#    in the system ANSI codepage, so the runner did not parse at all. #64 made the
#    three runners ASCII and declared them pwsh-only with `#Requires -Version 7`,
#    which is a different thing from unparseable: 5.1 can now READ the file and
#    refuse it for a reason that is true. The shell contract itself is asserted in
#    Test-RunnerShellContract.ps1; what stays here is the tolerance policy.
$tokens = $null; $errors = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path $runAudit), [ref]$tokens, [ref]$errors)
Check ($errors.Count -eq 0) `
      "Run-Audit.ps1 does not parse: $($errors | ForEach-Object { $_.Message })"
$text = Get-Content -LiteralPath $runAudit -Raw

if ($null -ne $text) {
    Check ($text -match [regex]::Escape("PSBoundParameters.ContainsKey('LineTol')")) `
          "Run-Audit.ps1 must decide explicitness via PSBoundParameters, not by comparing to the default"
    Check ($text -match 'LineTolPolicy\.ps1') "Run-Audit.ps1 must dot-source the policy"

    $iRoslyn  = $text.IndexOf('roslyn.sarif')
    $iInfer   = $text.IndexOf('infersharp.sarif')
    $iResolve = $text.IndexOf('Resolve-LineTol')
    $iUse     = $text.IndexOf('--line-tol')
    Check ($iResolve -gt $iRoslyn -and $iResolve -gt $iInfer) `
          "the tolerance must be resolved AFTER both folding blocks, or the tool list is not final"
    Check ($iUse -gt $iResolve) "the resolved tolerance must be computed before report.py consumes it"
}

# ---- verdict ----------------------------------------------------------------
foreach ($f in $script:Fails) { Write-Host "FAIL: $f" }
foreach ($s in $script:Skips) { Write-Host "SKIP: $s" }
if ($script:Fails.Count -gt 0) {
    Write-Host ("line-tol policy: FAIL - {0} of {1} checks failed, {2} skipped" -f
                $script:Fails.Count, $script:Count, $script:Skips.Count)
    exit 1
}
Write-Host ("line-tol policy: OK - {0} checks passed (7 matrix rows + distinctions), {1} skipped" -f
            $script:Count, $script:Skips.Count)
exit 0
