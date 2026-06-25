#!/usr/bin/env python3
"""Build a self-contained interactive HTML dashboard from the STS audit artifacts.

    python3 viz/build_dashboard.py   ->  viz/sts-dashboard.html

Reads sts_audit/findings.json (the 72k raw findings) + health-report.md (the module
pain table), and emits one standalone HTML file (Plotly inlined when viz/plotly.min.js
is vendored, else from CDN; data embedded inline). Open it in any browser — hover,
zoom, toggle legends, drill into the module treemap, and switch visual themes.
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

    # the cluster headline (high-confidence / candidate) is the report's, not
    # recomputable from findings.json here — parse it from health-report.md so the KPI
    # tracks the artifact instead of being a frozen literal.
    md = open(os.path.join(STS, "health-report.md"), encoding="utf-8").read()
    cm = re.search(r"\*\*([\d,]+) findings\*\* \(([\d,]+) high-confidence, ([\d,]+) candidate\)", md)
    clusters = ({"total": int(cm.group(1).replace(",", "")),
                 "high": int(cm.group(2).replace(",", "")),
                 "candidate": int(cm.group(3).replace(",", "")), }
                if cm else {"high": 0, "candidate": 0, "total": 0})

    return {
        "total": len(findings),
        "by_category": cat.most_common(),
        "by_tool": tool.most_common(),
        "by_source": by_source,
        "top_rules": rule.most_common(18),
        "own_shapes": shapes.most_common(),
        "own_shapes_fixed": sum(1 for s, _ in shapes.most_common() if s != "other"),
        "modules": mods,
        "clusters": clusters,
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
  :root{
    --bg:#0b0f17;--bg2:#0e1422;--card:rgba(20,27,42,.72);--line:rgba(120,140,180,.16);
    --fg:#e8eef7;--mut:#8b97a8;--accent:#58a6ff;--ok:#3fb950;--mute:#6b7686;
    --c1:#58a6ff;--c2:#3fb950;--c3:#bc8cff;--c4:#39c5cf;
    --glow:rgba(88,166,255,.45);--grid:rgba(120,140,180,.14);
    --font:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
    --bgimg:radial-gradient(1100px 560px at 82% -12%, rgba(56,90,170,.30), transparent 60%),
            radial-gradient(900px 500px at 8% 8%, rgba(63,185,80,.10), transparent 55%);
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{background:var(--bg);background-image:var(--bgimg);background-attachment:fixed;
    color:var(--fg);font:15px/1.55 var(--font);-webkit-font-smoothing:antialiased;
    transition:background-color .35s, color .35s}
  header{padding:30px 34px 6px;display:flex;justify-content:space-between;align-items:flex-start;gap:20px;flex-wrap:wrap}
  h1{margin:0;font-size:26px;font-weight:800;letter-spacing:-.4px;
    background:linear-gradient(92deg,var(--fg),var(--accent));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
  .sub{color:var(--mut);margin-top:5px;max-width:760px}
  .themes{display:flex;gap:8px;flex-wrap:wrap}
  .themes button{cursor:pointer;border:1px solid var(--line);background:var(--card);color:var(--mut);
    border-radius:999px;padding:7px 14px;font:600 13px/1 var(--font);transition:.2s;backdrop-filter:blur(8px)}
  .themes button:hover{color:var(--fg);border-color:var(--accent)}
  .themes button.on{color:#fff;border-color:transparent;background:linear-gradient(92deg,var(--accent),var(--c3));box-shadow:0 0 0 1px var(--accent), 0 6px 22px var(--glow)}
  .kpis{display:flex;flex-wrap:wrap;gap:14px;padding:18px 34px}
  .kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:15px 20px;min-width:158px;
    backdrop-filter:blur(10px);transition:transform .2s, border-color .2s}
  .kpi:hover{transform:translateY(-3px);border-color:var(--accent)}
  .kpi .n{font-size:28px;font-weight:800;letter-spacing:-.5px;text-shadow:0 0 22px var(--glow)}
  .kpi .l{color:var(--mut);font-size:12.5px;margin-top:3px}
  .kpi .n.ok{color:var(--ok);text-shadow:0 0 22px color-mix(in srgb,var(--ok) 50%,transparent)}
  .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;padding:14px 34px 44px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:10px 10px 6px;
    backdrop-filter:blur(10px);transition:transform .2s, border-color .2s, box-shadow .2s}
  .card:hover{transform:translateY(-2px);border-color:var(--line);box-shadow:0 14px 40px rgba(0,0,0,.35)}
  .card h2{font-size:14px;margin:9px 13px 0;font-weight:700}
  .card p{font-size:12px;color:var(--mut);margin:3px 13px 7px}
  .wide{grid-column:1/-1}
  .plot{width:100%;height:360px}
  .tall{height:470px}
  footer{color:var(--mut);font-size:12px;padding:0 34px 34px}
  code{color:var(--accent);background:rgba(120,140,180,.12);padding:1px 5px;border-radius:5px}
  @media(max-width:880px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body data-theme="midnight">
<header>
  <div>
    <h1>OwnAudit — STS health dashboard</h1>
    <div class="sub">Static audit of <code>STS_new/SectorTS</code> — a legacy .NET 4.7.2 / WPF / DevExpress app. Hover, zoom, toggle legends, click into the treemap.</div>
  </div>
  <div class="themes" id="themes"></div>
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

// ---- themes -------------------------------------------------------------
const THEMES = {
  midnight:{label:'Midnight', vars:{
    '--bg':'#0b0f17','--bg2':'#0e1422','--card':'rgba(20,27,42,.72)','--line':'rgba(120,140,180,.16)',
    '--fg':'#e8eef7','--mut':'#8b97a8','--accent':'#58a6ff','--ok':'#3fb950','--mute':'#6b7686',
    '--c1':'#58a6ff','--c2':'#3fb950','--c3':'#bc8cff','--c4':'#39c5cf','--glow':'rgba(88,166,255,.45)','--grid':'rgba(120,140,180,.14)',
    '--font':'-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif',
    '--bgimg':'radial-gradient(1100px 560px at 82% -12%, rgba(56,90,170,.30), transparent 60%), radial-gradient(900px 500px at 8% 8%, rgba(63,185,80,.10), transparent 55%)'},
    scale:[[0,'#1b2433'],[.5,'#d29922'],[1,'#f85149']]},
  terminal:{label:'Terminal', vars:{
    '--bg':'#000600','--bg2':'#03110a','--card':'rgba(0,22,12,.7)','--line':'rgba(0,255,156,.20)',
    '--fg':'#c8ffe4','--mut':'#5d9c7c','--accent':'#00ff9c','--ok':'#00ff9c','--mute':'#2f6b4d',
    '--c1':'#00ff9c','--c2':'#39d98a','--c3':'#7CFFB2','--c4':'#00d2c2','--glow':'rgba(0,255,156,.40)','--grid':'rgba(0,255,156,.12)',
    '--font':'ui-monospace,SFMono-Regular,Menlo,Consolas,monospace',
    '--bgimg':'radial-gradient(1000px 520px at 80% -10%, rgba(0,255,156,.14), transparent 60%), repeating-linear-gradient(0deg, rgba(0,255,156,.035) 0 1px, transparent 1px 3px)'},
    scale:[[0,'#04140c'],[.5,'#0c8f54'],[1,'#00ff9c']]},
  aurora:{label:'Aurora', vars:{
    '--bg':'#0a0716','--bg2':'#120a26','--card':'rgba(28,18,52,.62)','--line':'rgba(180,150,255,.20)',
    '--fg':'#f0eaff','--mut':'#a99cc9','--accent':'#b388ff','--ok':'#2dd4bf','--mute':'#7a6ca0',
    '--c1':'#b388ff','--c2':'#2dd4bf','--c3':'#ff8fd0','--c4':'#7aa2ff','--glow':'rgba(179,136,255,.50)','--grid':'rgba(180,150,255,.14)',
    '--font':'-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif',
    '--bgimg':'radial-gradient(1000px 560px at 84% -14%, rgba(179,136,255,.34), transparent 60%), radial-gradient(900px 540px at 6% 12%, rgba(45,212,191,.20), transparent 58%), radial-gradient(700px 420px at 50% 110%, rgba(255,143,208,.16), transparent 60%)'},
    scale:[[0,'#1a1230'],[.5,'#7c5cff'],[1,'#ff8fd0']]},
};
function cssv(n){return getComputedStyle(document.body).getPropertyValue(n).trim();}
let CUR='midnight';

function applyTheme(name){
  CUR=name; const t=THEMES[name];
  for(const k in t.vars) document.body.style.setProperty(k,t.vars[k]);
  document.body.setAttribute('data-theme',name);
  document.querySelectorAll('.themes button').forEach(b=>b.classList.toggle('on',b.dataset.t===name));
  renderAll();
}

// theme switcher
document.getElementById('themes').innerHTML=Object.entries(THEMES)
  .map(([k,t])=>`<button data-t="${k}">${t.label}</button>`).join('');
document.getElementById('themes').onclick=e=>{const b=e.target.closest('button'); if(b) applyTheme(b.dataset.t);};

// ---- KPIs ---------------------------------------------------------------
const kpis=[[D.total.toLocaleString(),'raw findings'],[D.fixable_pct+'%','auto-fixable (ships a fix)','ok'],
  [D.clusters.high.toLocaleString(),'high-confidence clusters'],[D.modules.length,'modules ranked'],
  [D.own_shapes_fixed,'OWN leak shapes fixed','ok']];
document.getElementById('kpis').innerHTML=kpis.map(k=>
  `<div class="kpi"><div class="n ${k[2]||''}">${k[0]}</div><div class="l">${k[1]}</div></div>`).join('');

// ---- charts -------------------------------------------------------------
const CFG={displayModeBar:false,responsive:true};
function base(extra){
  return Object.assign({paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',
    font:{color:cssv('--fg'),family:cssv('--font')},showlegend:false,
    xaxis:{gridcolor:cssv('--grid'),zerolinecolor:cssv('--grid')},
    yaxis:{gridcolor:cssv('--grid'),zerolinecolor:cssv('--grid')},
    margin:{l:140,r:16,t:10,b:30}},extra||{});
}
function bar(id,pairs,horizontal,colorvar){
  const lab=pairs.map(p=>p[0]), val=pairs.map(p=>p[1]), col=cssv(colorvar||'--c1');
  const tr=horizontal?{type:'bar',orientation:'h',y:lab,x:val,marker:{color:col}}
                     :{type:'bar',x:lab,y:val,marker:{color:col}};
  Plotly.react(id,[tr],base(horizontal?{margin:{l:170,r:16,t:6,b:24}}:{margin:{l:50,r:10,t:6,b:90}}),CFG);
}
function renderAll(){
  const t=THEMES[CUR];
  const ratio=D.modules.map(m=>m.findings?m.high/m.findings:0);
  Plotly.react('treemap',[{type:'treemap',
    labels:D.modules.map(m=>m.module), parents:D.modules.map(()=>''),
    values:D.modules.map(m=>m.pain), textinfo:'label+value',
    marker:{colors:ratio,colorscale:t.scale,cmin:0,cmax:0.6,line:{color:cssv('--bg'),width:1.5}},
    customdata:D.modules.map(m=>[m.findings,m.high,m.cat]),
    hovertemplate:'<b>%{label}</b><br>pain %{value}<br>%{customdata[0]} findings · %{customdata[1]} high-conf<br>top: %{customdata[2]}<extra></extra>'}],
    base({margin:{l:4,r:4,t:4,b:4}}),CFG);
  bar('cat',D.by_category,true,'--c1');
  bar('tool',D.by_tool,false,'--c3');
  bar('rules',D.top_rules,true,'--c4');
  bar('own',D.own_shapes,true,'--ok');
  Plotly.react('src',[{type:'bar',orientation:'h',
    y:D.by_source.map(s=>s.source), x:D.by_source.map(s=>s.count),
    marker:{color:D.by_source.map(s=>s.codefix?cssv('--ok'):cssv('--mute'))},
    customdata:D.by_source.map(s=>s.codefix?'ships a code fix':'detect-only / bespoke'),
    hovertemplate:'<b>%{y}</b><br>%{x} findings<br>%{customdata}<extra></extra>'}],
    base({margin:{l:170,r:16,t:6,b:24}}),CFG);
}

applyTheme('midnight');
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
              .replace("%DATA%", json.dumps(data).replace("</", "<\\/")) \
              .replace("%CLUSTERS%", f"{data['clusters']['total']:,} clusters")
    dst = os.path.join(ROOT, "viz", "sts-dashboard.html")
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"wrote {dst}  ({len(out):,} bytes; {data['total']:,} findings, {len(data['modules'])} modules)")


if __name__ == "__main__":
    main()
