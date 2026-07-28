"""`aggregate` - SARIF in, one categorized findings set out.

This initializer exists so the package cannot be shadowed. Without it the
directory would be an implicit namespace package, and any installed distribution
named `aggregate` on `sys.path` would win over the repo's own code even with the
repo root inserted first - the failure mode found on `identity/` (Own.NET#266
slice 0) and fixed the same way here.
"""
