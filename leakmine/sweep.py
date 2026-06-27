"""Prospective sweep — the unbiased experiment: run OwnAudit on live popular code.

The fixed-bug corpus is selection-biased (only noticed+fixed+leak-labelled bugs survive).
The sweep sidesteps that entirely: take the top-N packages by downloads, run OwnAudit on
their *current* HEAD, triage, and report upstream. Acceptance rate = precision in the wild.
This is what already worked in miniature for OwnTS (real useEffect leaks in popular npm).

The catch you flagged: the very top of npm/NuGet is foundational, ultra-vetted libraries —
Dapper, Polly, Serilog — which are *supposed* to be leak-free and produce a floor effect.
Sampling only them tells you nothing. So selection here deliberately CAPS the over-vetted
fraction and over-weights application-shaped repos (dashboards, SaaS control planes, CLIs,
sample apps), where lifetime bugs actually survive in the wild.

Registry access is isolated behind injectable getters (npm downloads API, NuGet search) so
the selection logic unit-tests with no network.
"""
from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass, field


@dataclass
class Package:
    name: str
    registry: str               # "npm" | "nuget"
    downloads: int = 0
    stars: int = 0
    maintainers: int = 0
    open_issues: int = 0
    age_days: int = 0
    has_ci: bool = False
    # repo shape hint, when known: "library" | "application" | "framework" | "unknown".
    shape: str = "unknown"
    repo: str = ""


@dataclass
class Scored:
    pkg: Package
    vetted: float               # 0..1, higher = more polished = worse sample
    weight: float               # selection weight (higher = prefer)
    reason: list[str] = field(default_factory=list)


def over_vetted_score(p: Package) -> Scored:
    """Heuristic 0..1 of how 'already-vlizany' a package is. The signals that make a lib a
    BAD leak-hunting sample: many maintainers, CI, mature age, and a high stars-per-issue
    ratio (lots of eyeballs, few open problems) — the Dapper/Polly/Serilog profile."""
    s = 0.0
    reason: list[str] = []
    if p.maintainers >= 5:
        s += 0.20; reason.append("many-maintainers")
    if p.has_ci:
        s += 0.10; reason.append("ci")
    if p.age_days >= 5 * 365:
        s += 0.20; reason.append("mature")
    if p.stars >= 5000:
        s += 0.15; reason.append("popular")
    # eyeballs-per-problem: high stars, few open issues -> heavily curated.
    if p.stars and p.open_issues is not None:
        ratio = p.stars / (p.open_issues + 1)
        if ratio >= 200:
            s += 0.25; reason.append("high-stars-per-issue")
    if p.shape == "library":
        s += 0.10; reason.append("foundational-library")
    elif p.shape == "application":
        s -= 0.15; reason.append("application-shaped")
    vetted = max(0.0, min(1.0, s))
    # selection weight: prefer downloads (reach) but discount by vettedness.
    import math
    reach = math.log10(p.downloads + 10)
    weight = reach * (1.0 - 0.7 * vetted)
    return Scored(pkg=p, vetted=vetted, weight=weight, reason=reason)


def select_targets(
    packages: list[Package],
    *,
    n: int,
    max_vetted_fraction: float = 0.3,
    vetted_threshold: float = 0.6,
) -> list[Scored]:
    """Pick N sweep targets that don't drown in over-vetted libraries.

    Sort by selection weight, then admit greedily while keeping the share of
    `vetted >= vetted_threshold` packages under `max_vetted_fraction`. The cap is the whole
    point: it forces application-shaped, less-curated repos into the sample where leaks live.
    """
    scored = sorted((over_vetted_score(p) for p in packages), key=lambda s: -s.weight)
    chosen: list[Scored] = []
    n_vetted = 0
    for s in scored:
        if len(chosen) >= n:
            break
        is_vetted = s.vetted >= vetted_threshold
        if is_vetted and (n_vetted + 1) > max_vetted_fraction * n:
            continue  # cap reached — skip this polished lib, leave room for app-shaped repos
        chosen.append(s)
        n_vetted += int(is_vetted)
    return chosen


# ---- registry URL builders (pure; fetch injected) --------------------------------

def npm_downloads_url(pkg: str, *, period: str = "last-month") -> str:
    return f"https://api.npmjs.org/downloads/point/{period}/{urllib.parse.quote(pkg, safe='@/')}"


def nuget_search_url(query: str = "", *, take: int = 100, prerelease: bool = False) -> str:
    return "https://azuresearch-usnc.nuget.org/query?" + urllib.parse.urlencode(
        {"q": query, "take": take, "prerelease": str(prerelease).lower()}
    )


def parse_npm_downloads(raw: bytes) -> int:
    return int(json.loads(raw).get("downloads", 0))


def parse_nuget_search(raw: bytes) -> list[Package]:
    data = json.loads(raw)
    out: list[Package] = []
    for it in data.get("data", []):
        out.append(Package(
            name=it.get("id", ""),
            registry="nuget",
            downloads=int(it.get("totalDownloads", 0)),
            repo=it.get("projectUrl", "") or "",
        ))
    return out
