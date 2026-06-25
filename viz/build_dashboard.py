#!/usr/bin/env python3
"""Build a self-contained interactive HTML dashboard from the STS audit artifacts.

    python3 viz/build_dashboard.py   ->  viz/sts-dashboard.html

Reads sts_audit/findings.json (the 72k raw findings) + health-report.md (the module
pain table), and emits one standalone HTML file (Plotly from CDN; data embedded inline).
Open it in any browser — hover, zoom, toggle legends, drill into the module treemap.
"""
import collections
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STS = os.path.join(ROOT, "sts_audit")


def _source(rule: str) -> str:
    r = rule or ""
    table = [("INPC", "PropertyChangedAnalyzers"), ("WPF", "WpfAnalyzers"),
             ("IDISP", "IDisposableAnalyzers"), ("MA", "Meziantou.Analyzer"),
             ("RCS", "Roslynator"), ("CA", "NetAnalyzers"), ("AsyncFixer", "AsyncFixer"),
             ("cs/", "CodeQL"), ("OWN", "own-check"), ("CS", "C# compiler")]
    for prefix, name in table:
        if r.startswith(prefix):
            return name
    if r.isupper() and "_" in r:
        return "Infer#"
    return "other"


_SHIPS_FIX = {"PropertyChangedAnalyzers", "WpfAnalyzers", "IDisposableAnalyzers",
              "Meziantou.Analyzer", "Roslynator", "NetAnalyzers", "AsyncFixer"}


def collect() -> dict:
    findings = json.load(open(os.path.join(STS, "findings.json"), encoding="utf-8"))["findings"]
    cat = collections.Counter(x.get("category_name") for x in findings)
    tool = collections.Counter(x.get("tool") for x in findings)
    src = collections.Counter(_source(x.get("rule")) for x in findings)
    rule = collections.Counter(x.get("rule") for x in findings)

    # OWN shape split (own-check's OWN001/OWN014) — what the bespoke fixer covers.
    own = [x for x in findings if (x.get("rule") or "").startswith("OWN")]
    shapes = collections.Counter()
    for x in own:
        m = x.get("message", "")
        if "field" in m and "never disposed" in m:
            shapes["disposable field → dispose"] += 1
        elif "local" in m and "never disposed" in m:
            shapes["disposable local → using"] += 1
        elif "subscribed" in m and "=>" in m:
            shapes["inline lambda → extract"] += 1
        elif "subscribed" in m:
            shapes["named handler → detach"] += 1
        else:
            shapes["other"] += 1

    mods = []
    for line in open(os.path.join(STS, "health-report.md"), encoding="utf-8"):
        m = re.match(r"\|\s*`([^`]+)`\s*\|\s*([\d.]+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([^|]+)\|", line)
        if m:
            mods.append({"module": m.group(1), "pain": float(m.group(2)),
                         "findings": int(m.group(3)), "high": int(m.group(4)),
                         "cat": m.group(5).strip()})

    by_source = [{"source": s, "count": c, "codefix": int(s in _SHIPS_FIX)}
                 for s, c in src.most_common()]
    return {
        "total": len(findings),
        "by_category": cat.most_common(),
        "by_tool": tool.most_common(),
        "by_source": by_source,
        "top_rules": rule.most_common(18),
        "own_shapes": shapes.most_common(),
        "modules": mods,
        "clusters": {"high": 3602, "candidate": 12201, "total": 15803},
        "fixable_pct": round(100 * sum(s["count"] for s in by_source if s["codefix"]) / len(findings)),
    }


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OwnAudit — STS health dashboard</title>
%PLOTLY%
<style>
  :root{--bg:#0d1117;--card:#161b22;--line:#21262d;--fg:#e6edf3;--mut:#8b949e;--ok:#3fb950;--accent:#58a6ff}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
  header{padding:28px 32px 8px}
  h1{margin:0;font-size:24px}
  .sub{color:var(--mut);margin-top:4px}
  .kpis{display:flex;flex-wrap:wrap;gap:14px;padding:18px 32px}
  .kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 18px;min-width:150px}
  .kpi .n{font-size:26px;font-weight:700}
  .kpi .l{color:var(--mut);font-size:13px;margin-top:2px}
  .kpi .n.ok{color:var(--ok)}
  .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;padding:14px 32px 40px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:8px 8px 4px}
  .card h2{font-size:14px;margin:8px 12px 0;color:var(--fg)}
  .card p{font-size:12px;color:var(--mut);margin:2px 12px 6px}
  .wide{grid-column:1/-1}
  .plot{width:100%;height:360px}
  .tall{height:460px}
  footer{color:var(--mut);font-size:12px;padding:0 32px 32px}
  a{color:var(--accent)}
  @media(max-width:880px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  <h1>OwnAudit — STS health dashboard</h1>
  <div class="sub">Static audit of <code>STS_new/SectorTS</code> — a legacy .NET 4.7.2 / WPF / DevExpress app. Hover, zoom, toggle legends, click into the treemap.</div>
</header>
<div class="kpis" id="kpis"></div>
<div class="grid">
  <div class="card wide"><h2>Where it hurts most</h2><p>Modules sized by pain index (severity × cross-tool agreement), coloured by share of high-confidence findings. Click to zoom.</p><div id="treemap" class="plot tall"></div></div>
  <div class="card"><h2>Findings by category</h2><p>What kind of problem.</p><div id="cat" class="plot"></div></div>
  <div class="card"><h2>By analyzer source — does it ship a fix?</h2><p>85% come from analyzers with a CodeFixProvider → wire, don't build.</p><div id="src" class="plot"></div></div>
  <div class="card"><h2>By tool</h2><p>Who flagged it.</p><div id="tool" class="plot"></div></div>
  <div class="card"><h2>Top rules</h2><p>The most frequent diagnostics.</p><div id="rules" class="plot"></div></div>
  <div class="card wide"><h2>OWN fixer — shape coverage</h2><p>The leak shapes own-check flags that no off-the-shelf tool fixes — and how the bespoke T4 fixer remediates each.</p><div id="own" class="plot"></div></div>
</div>
<footer>Generated by <code>viz/build_dashboard.py</code> from <code>sts_audit/</code> · raw findings clustered to %CLUSTERS% (high-confidence = ≥2 tools agree).</footer>
<script>
const D = %DATA%;
const T = {paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{color:'#e6edf3'},
  margin:{l:140,r:16,t:10,b:30},showlegend:false,colorway:['#58a6ff','#3fb950','#d29922','#f85149','#bc8cff','#39c5cf','#ff7b72','#79c0ff']};
const CFG = {displayModeBar:false,responsive:true};

// KPIs
const kpis=[['72,569','raw findings'],[D.fixable_pct+'%','auto-fixable (ships a fix)','ok'],
  ['3,602','high-confidence clusters'],[D.modules.length,'modules ranked'],['4','OWN leak shapes fixed','ok']];
document.getElementById('kpis').innerHTML=kpis.map(k=>
  `<div class="kpi"><div class="n ${k[2]||''}">${k[0]}</div><div class="l">${k[1]}</div></div>`).join('');

// Treemap of modules by pain
const ratio=D.modules.map(m=>m.findings?m.high/m.findings:0);
Plotly.newPlot('treemap',[{type:'treemap',
  labels:D.modules.map(m=>m.module), parents:D.modules.map(()=>''),
  values:D.modules.map(m=>m.pain), textinfo:'label+value',
  marker:{colors:ratio,colorscale:[[0,'#21262d'],[0.5,'#d29922'],[1,'#f85149']],
          cmin:0,cmax:0.6,line:{color:'#0d1117',width:1}},
  customdata:D.modules.map(m=>[m.findings,m.high,m.cat]),
  hovertemplate:'<b>%{label}</b><br>pain %{value}<br>%{customdata[0]} findings · %{customdata[1]} high-conf<br>top: %{customdata[2]}<extra></extra>'}],
  Object.assign({},T,{margin:{l:4,r:4,t:4,b:4}}),CFG);

function bar(id,pairs,horizontal,color){
  const lab=pairs.map(p=>p[0]), val=pairs.map(p=>p[1]);
  const tr=horizontal?{type:'bar',orientation:'h',y:lab,x:val,marker:{color:color||'#58a6ff'}}
                     :{type:'bar',x:lab,y:val,marker:{color:color||'#58a6ff'}};
  Plotly.newPlot(id,[tr],Object.assign({},T,horizontal?{margin:{l:170,r:16,t:6,b:24}}:{margin:{l:50,r:10,t:6,b:90}}),CFG);
}
bar('cat',D.by_category,true);
bar('tool',D.by_tool,false,'#bc8cff');
bar('rules',D.top_rules,true,'#39c5cf');

// Source, coloured by whether it ships a code fix
Plotly.newPlot('src',[{type:'bar',orientation:'h',
  y:D.by_source.map(s=>s.source), x:D.by_source.map(s=>s.count),
  marker:{color:D.by_source.map(s=>s.codefix?'#3fb950':'#8b949e')},
  customdata:D.by_source.map(s=>s.codefix?'ships a code fix':'detect-only / bespoke'),
  hovertemplate:'<b>%{y}</b><br>%{x} findings<br>%{customdata}<extra></extra>'}],
  Object.assign({},T,{margin:{l:170,r:16,t:6,b:24}}),CFG);

// OWN shapes
bar('own',D.own_shapes,true,'#3fb950');
</script>
</body>
</html>
"""


def _plotly_tag() -> str:
    """Inline the vendored Plotly for a fully offline, self-contained file; fall back
    to the CDN if viz/plotly.min.js isn't present (run: curl the lib into viz/)."""
    vendored = os.path.join(ROOT, "viz", "plotly.min.js")
    if os.path.exists(vendored):
        with open(vendored, encoding="utf-8") as fh:
            return "<script>" + fh.read() + "</script>"
    return '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>'


def main():
    data = collect()
    out = HTML.replace("%PLOTLY%", _plotly_tag()) \
              .replace("%DATA%", json.dumps(data)) \
              .replace("%CLUSTERS%", f"{data['clusters']['total']:,} clusters")
    dst = os.path.join(ROOT, "viz", "sts-dashboard.html")
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"wrote {dst}  ({len(out):,} bytes; {data['total']:,} findings, {len(data['modules'])} modules)")


if __name__ == "__main__":
    main()
