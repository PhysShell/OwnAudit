<#
.SYNOPSIS
  Decide the effective clustering tolerance (`--line-tol`) for a set of folded-in
  SARIF producers.

.DESCRIPTION
  `Run-Audit.ps1` folds Infer# and Roslyn SARIF in AUTOMATICALLY whenever the
  files are already sitting in `artifacts/`, but `$LineTol` stayed at its default
  of 3 unless the caller remembered a flag. `AGENTS.md:15` says the opposite:

    > use `-LineTol 8` when folding Infer# or Roslyn because those tools report
    > shifted/generated locations.

  So the folding was automatic and the tolerance it requires was manual, and
  clustering ran with the wrong window every time nobody remembered. The comments
  inside the script repeated the rule and, being comments, did nothing.

  THIS FUNCTION DOES NOT OVERRIDE A DELIBERATE CHOICE. The obvious one-liner —
  `$LineTol = [Math]::Max($LineTol, 8)` — silently rewrites an explicitly passed
  `-LineTol 3` into an 8. That is the script deciding for the caller and not
  saying so, which is the behaviour the provenance contract exists to prevent:
  do not assert what you did not observe, and do not substitute your choice for
  someone else's. An explicitly passed value is therefore honoured EXACTLY, even
  when it is lower than the tools want; the mismatch is reported and left standing.

  Kept as a pure function in its own file so the matrix can be pinned without
  running an analyzer, a build, or a Python process.

.NOTES
  Whether `-LineTol` was passed cannot be decided here — `$PSBoundParameters`
  belongs to the caller's own invocation. `Run-Audit.ps1` reads it in its own
  scope and passes the answer in as `-Explicit`.
#>

Set-StrictMode -Version Latest

#: Producers whose reported location is routinely shifted from the site a human
#: would point at: Infer# reports at the last-access line, Roslyn at generated or
#: expanded positions. Clustering them at the default window splits one defect
#: into several findings.
$script:ShiftedLocationTools = @('infersharp', 'roslyn')

#: The tolerance those producers need. From AGENTS.md, not invented here.
$script:ShiftedLineTol = 8

function Resolve-LineTol {
    <#
    .SYNOPSIS
      Effective `--line-tol`, plus a human-readable account of why.

    .OUTPUTS
      [pscustomobject] with:
        Value    - the tolerance to pass to report.py
        Raised   - $true when this function raised an implicit default
        Reason   - 'default' | 'raised-for-shifted-tools' | 'explicit'
        Trigger  - the shifted-location tools that were folded in (may be empty)
        Message  - one line for stdout, or $null when there is nothing to say
        Warning  - one line for stderr, or $null
    #>
    [CmdletBinding()]
    param(
        # The value `$LineTol` currently holds in the caller: either its default
        # or whatever was passed.
        [Parameter(Mandatory)][int]$Requested,

        # $true when the caller actually passed -LineTol. The caller must compute
        # this with $PSBoundParameters.ContainsKey('LineTol') in its OWN scope: a
        # value equal to the default is not evidence either way, so this cannot be
        # inferred from $Requested.
        [Parameter(Mandatory)][bool]$Explicit,

        # Tool names being folded in, in any spelling order — e.g.
        # @('own-check','codeql','roslyn'). Matched case-insensitively.
        [string[]]$Tools = @()
    )

    $trigger = @($Tools | Where-Object { $script:ShiftedLocationTools -contains $_.ToLowerInvariant() } |
                 Sort-Object -Unique)

    if (-not $Explicit) {
        if ($trigger.Count -gt 0) {
            return [pscustomobject]@{
                Value   = $script:ShiftedLineTol
                Raised  = $true
                Reason  = 'raised-for-shifted-tools'
                Trigger = $trigger
                Message = ("line-tol: raised {0} -> {1} because {2} report shifted/generated " +
                           "locations (AGENTS.md); pass -LineTol explicitly to override") -f
                          $Requested, $script:ShiftedLineTol, ($trigger -join ' and ')
                Warning = $null
            }
        }
        return [pscustomobject]@{
            Value   = $Requested
            Raised  = $false
            Reason  = 'default'
            Trigger = $trigger
            Message = $null
            Warning = $null
        }
    }

    # Explicit. The value stands, whatever it is. Say so when it is below what the
    # folded-in tools want, but do not move it: a warning the caller can act on is
    # worth more than a silent correction they cannot see.
    $warn = $null
    if ($trigger.Count -gt 0 -and $Requested -lt $script:ShiftedLineTol) {
        $warn = ("line-tol: using the explicit {0}, but {1} report shifted/generated locations " +
                 "and cluster better at {2} (AGENTS.md) — honouring your value, not overriding it") -f
                $Requested, ($trigger -join ' and '), $script:ShiftedLineTol
    }
    return [pscustomobject]@{
        Value   = $Requested
        Raised  = $false
        Reason  = 'explicit'
        Trigger = $trigger
        Message = $null
        Warning = $warn
    }
}
