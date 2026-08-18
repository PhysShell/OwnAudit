#Requires -Version 5.1
<#
.SYNOPSIS
  The shell contract of the three runners (OwnAudit#64). Runs on BOTH editions.

.DESCRIPTION
  Run-Audit.ps1, Run-Infersharp.ps1 and Run-Roslyn.ps1 are pwsh-only. That was
  true before #64 as well - but it was true by ACCIDENT: the files carried
  non-ASCII characters and no BOM, so Windows PowerShell 5.1 decoded them in the
  system ANSI codepage and died on a syntax error inside whatever word happened
  to contain a byte above 127. Someone opening an old Windows console was told
  that `honouring` was a syntax crime.

  The contract this suite pins down is deliberately NOT "the runners work under
  5.1". It is:

      5.1 can READ the file, and says the true thing about it.

  Two halves, and both are load-bearing. ASCII-only is what makes the file
  readable under any single-byte codepage. `#Requires -Version 7` is what the
  engine then acts on - refusing before a single statement of the body runs.
  Without the first, the second is unreachable; without the second, the first
  just moves the failure somewhere less honest.

  Under 5.1 the refusal is exercised for real: the runner is invoked with an
  -Out directory that does not exist, and the check is that it STILL does not
  exist afterwards. Under pwsh the runners are only parsed, never invoked - they
  drive worktrees, WSL and MSBuild, which is not something a test may start.

.NOTES
  Bare invocation, no Pester (it is not guaranteed in the dev shell):
      pwsh -File scripts/tests/Test-RunnerShellContract.ps1
      powershell -File scripts/tests/Test-RunnerShellContract.ps1
  ASCII-only by its own rule - this file is a runner-adjacent script and is held
  to the standard it enforces.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:Count = 0
$script:Fails = @()

function Check([bool]$ok, [string]$msg) {
    $script:Count++
    if (-not $ok) { $script:Fails += $msg }
}

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$runners = @('Run-Audit.ps1', 'Run-Infersharp.ps1', 'Run-Roslyn.ps1')

# ---- 1. Byte-level ASCII. ----------------------------------------------------
# Read as BYTES, not as text: reading as text is exactly the step that hides the
# defect, because whatever encoding the reader assumes will produce SOME string.
foreach ($name in $runners) {
    $path = Join-Path $repo $name
    Check (Test-Path -LiteralPath $path) "$name is missing"
    if (-not (Test-Path -LiteralPath $path)) { continue }

    if ($PSVersionTable.PSVersion.Major -ge 6) {
        $bytes = [System.IO.File]::ReadAllBytes($path)
    } else {
        $bytes = Get-Content -LiteralPath $path -Encoding Byte -ReadCount 0
    }
    $high = @($bytes | Where-Object { $_ -gt 127 })
    Check ($high.Count -eq 0) `
          ("{0} carries {1} byte(s) above 127. Windows PowerShell 5.1 reads a BOM-less file in the system ANSI codepage, so those bytes become a parse error in an unrelated word." -f $name, $high.Count)

    # A BOM would also make 5.1 decode correctly - and is deliberately NOT the
    # fix. It would leave the file non-ASCII and make correctness depend on three
    # bytes that any editor may drop.
    $hasBom = $bytes.Count -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
    Check (-not $hasBom) "$name starts with a UTF-8 BOM; the contract is ASCII content, not a decoding hint"
}

# ---- 2. The requirement is DECLARED, where the engine can act on it. ---------
foreach ($name in $runners) {
    $path = Join-Path $repo $name
    if (-not (Test-Path -LiteralPath $path)) { continue }
    $lines = Get-Content -LiteralPath $path
    $req = @($lines | Where-Object { $_ -match '^\s*#Requires\s+-Version\s+7' })
    Check ($req.Count -ge 1) `
          "$name must declare '#Requires -Version 7' - a comment saying 'use pwsh' is advice, and the engine cannot act on advice"
}

# ---- 3. Every edition can PARSE them, 5.1 included. --------------------------
# This is the check that would have failed before #64, and it is the whole point:
# a refusal you can read beats a syntax error you cannot.
foreach ($name in $runners) {
    $path = Join-Path $repo $name
    if (-not (Test-Path -LiteralPath $path)) { continue }
    $tokens = $null; $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile(
        (Resolve-Path $path).Path, [ref]$tokens, [ref]$errors)
    Check ($errors.Count -eq 0) `
          ("{0} does not parse under {1} {2}: {3}" -f $name, $PSVersionTable.PSEdition,
           $PSVersionTable.PSVersion, (($errors | ForEach-Object { $_.Message }) -join '; '))
}

# ---- 4. Under 5.1 the refusal is real, and stops before the body. -----------
if ($PSVersionTable.PSEdition -eq 'Desktop') {
    foreach ($name in $runners) {
        $path = Join-Path $repo $name
        if (-not (Test-Path -LiteralPath $path)) { continue }

        # A directory that does not exist. Every runner creates its -Out early;
        # if the body runs at all, this appears. Its ABSENCE afterwards is the
        # evidence that #Requires fired first.
        $probe = Join-Path ([System.IO.Path]::GetTempPath()) ("shellcontract-" + [Guid]::NewGuid().ToString("N"))
        $out = & powershell.exe -NoProfile -NonInteractive -File $path -Out $probe 2>&1
        $text = ($out | Out-String)

        Check ($LASTEXITCODE -ne 0) "$name ran to success under Windows PowerShell 5.1; it is declared pwsh-only"
        Check ($text -match '(?i)version|requires') `
              ("{0} failed under 5.1 without naming the version requirement. That is the #64 defect returning in another costume: the message must be about the shell, not about a word in a comment. Got: {1}" -f $name, $text.Trim())
        Check (-not (Test-Path -LiteralPath $probe)) `
              "$name created its -Out directory before refusing; #Requires must stop the script before any statement of the body"
        if (Test-Path -LiteralPath $probe) { Remove-Item -Recurse -Force -LiteralPath $probe }
    }
} else {
    # Under pwsh the requirement is SATISFIED, so invoking would really start a
    # worktree/WSL/MSBuild run. The half that can be checked here is that the
    # declaration does not disturb the file: help still resolves, which is what
    # would break if `#Requires` had been placed somewhere it detaches the
    # comment-based help from the script.
    foreach ($name in $runners) {
        $path = Join-Path $repo $name
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $help = Get-Help $path -ErrorAction SilentlyContinue
        Check ($null -ne $help -and -not [string]::IsNullOrWhiteSpace(($help.Synopsis | Out-String).Trim())) `
              "$name lost its comment-based help; '#Requires' must sit above the help block without detaching it"
    }
}

# ---- 5. This suite holds itself to the same rule. ---------------------------
$self = $PSCommandPath
if ($PSVersionTable.PSVersion.Major -ge 6) {
    $selfBytes = [System.IO.File]::ReadAllBytes($self)
} else {
    $selfBytes = Get-Content -LiteralPath $self -Encoding Byte -ReadCount 0
}
Check (@($selfBytes | Where-Object { $_ -gt 127 }).Count -eq 0) `
      "this suite is not ASCII; a test for readability that cannot itself be read is theatre"

# ---- verdict ----------------------------------------------------------------
foreach ($f in $script:Fails) { Write-Host "FAIL: $f" }
if ($script:Fails.Count -gt 0) {
    Write-Host ("runner shell contract: FAIL - {0} of {1} checks failed on {2} {3}" -f
                $script:Fails.Count, $script:Count, $PSVersionTable.PSEdition, $PSVersionTable.PSVersion)
    exit 1
}
Write-Host ("runner shell contract: OK - {0} checks passed on {1} {2}" -f
            $script:Count, $PSVersionTable.PSEdition, $PSVersionTable.PSVersion)
exit 0
