#!/usr/bin/env python3
"""Build a self-contained interactive HTML dashboard from the STS audit artifacts.

    python3 viz/build_dashboard.py   ->  viz/sts-dashboard.html

Reads sts_audit/findings.json (the 72k raw findings) + health-report.md (the module
pain table), and emits one standalone HTML file (Plotly inlined when viz/plotly.min.js
is vendored, else from CDN; data embedded inline). Open it in any browser.

Interactive:
  * filter by tool and/or category (chips) — every live chart + the table re-aggregate
  * drill down from a module treemap tile into its individual findings (table)
  * fix-tier breakdown (T1 auto / T2 review / T3 unfixable / T4 bespoke), filter-aware
  * trend across runs — each build appends a dated snapshot to viz/history.jsonl

The per-finding rows are embedded with string interning (paths/rules/tools/cats become
small integer indices) so client-side filtering over 72k findings stays cheap and the
file stays a few MB.
"""
import collections
import datetime
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STS = os.path.join(ROOT, "sts_audit")
HISTORY = os.path.join(ROOT, "viz", "history.jsonl")

# the fix-arm tier map is the single source of truth for T1..T4 — reuse it rather
# than re-deriving the classification here.
sys.path.insert(0, os.path.join(ROOT, "fix"))
from fixarm.tiers import tier_of, gate_for_tier, T1, T2, T3, T4   # noqa: E402

TIERS = [T1, T2, T3, T4]


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


def _own_shapes(findings) -> collections.Counter:
    """Classify the OWN-check leak findings into the shapes the bespoke fixer handles."""
    shapes = collections.Counter()
    for x in findings:
        if not (x.get("rule") or "").startswith("OWN"):
            continue
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
    return shapes


def _modules() -> list:
    """The module pain table parsed from health-report.md (severity x tool agreement)."""
    mods = []
    for line in open(os.path.join(STS, "health-report.md"), encoding="utf-8"):
        m = re.match(r"\|\s*`([^`]+)`\s*\|\s*([\d.]+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([^|]+)\|", line)
        if m:
            mods.append({"module": m.group(1), "pain": float(m.group(2)),
                         "findings": int(m.group(3)), "high": int(m.group(4)),
                         "cat": m.group(5).strip()})
    return mods


def _module_assigner(mod_names):
    """Map a finding path to the index of its longest matching module (segment-aligned),
    or the trailing '(other)' bucket. Modules nest (Broker, Broker/GTD), so match the
    most specific first."""
    by_len = sorted(mod_names, key=len, reverse=True)
    idx = {n: i for i, n in enumerate(mod_names)}
    other = len(mod_names)

    def assign(path):
        for mn in by_len:
            if path == mn or path.startswith(mn + "/"):
                return idx[mn]
        return other
    return assign


class _Intern:
    """String -> stable small-int index, preserving first-seen order."""
    def __init__(self, seed=()):
        self.items, self._idx = [], {}
        for s in seed:
            self.index(s)

    def index(self, s):
        i = self._idx.get(s)
        if i is None:
            i = len(self.items)
            self._idx[s] = i
            self.items.append(s)
        return i


def collect() -> dict:
    raw = open(os.path.join(STS, "findings.json"), encoding="utf-8").read()
    # content digest = the audit run's identity for the trend series (below).
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    findings = json.loads(raw)["findings"]

    # stable dimension orders: most-frequent first reads best in the chips/legends.
    cat = collections.Counter(x.get("category_name") for x in findings)
    tool = collections.Counter(x.get("tool") for x in findings)
    rule = collections.Counter(x.get("rule") for x in findings)
    cats = _Intern(c for c, _ in cat.most_common())
    tools = _Intern(t for t, _ in tool.most_common())
    rules = _Intern(r for r, _ in rule.most_common())
    paths = _Intern()

    mods = _modules()
    mod_names = [m["module"] for m in mods]
    module_of = _module_assigner(mod_names)

    # source (analyzer family) and tier are functions of the rule (+ tool for tier);
    # precompute the source per unique rule so the client can group without the table.
    src = _Intern()
    rule_src = [src.index(_source(r)) for r in rules.items]
    sources = [{"name": n, "codefix": int(n in _SHIPS_FIX)} for n in src.items]
    tier_pos = {t: i for i, t in enumerate(TIERS)}

    # one compact row per finding: [pathIdx, line, ruleIdx, toolIdx, catIdx, tierIdx, moduleIdx]
    rows, tier_counts = [], collections.Counter()
    for x in findings:
        r = x.get("rule")
        ti = tier_pos[tier_of(r, x.get("tool", ""))]
        tier_counts[TIERS[ti]] += 1
        rows.append([paths.index(x.get("path", "")), x.get("line", 0),
                     rules.index(r), tools.index(x.get("tool")),
                     cats.index(x.get("category_name")), ti,
                     module_of(x.get("path", ""))])

    shapes = _own_shapes(findings)
    md = open(os.path.join(STS, "health-report.md"), encoding="utf-8").read()
    cm = re.search(r"\*\*([\d,]+) findings\*\* \(([\d,]+) high-confidence, ([\d,]+) candidate\)", md)
    clusters = ({"total": int(cm.group(1).replace(",", "")),
                 "high": int(cm.group(2).replace(",", "")),
                 "candidate": int(cm.group(3).replace(",", "")), }
                if cm else {"high": 0, "candidate": 0, "total": 0})
    by_source = collections.Counter(rule_src[r[2]] for r in rows)

    snapshot = {"date": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "digest": digest, "total": len(findings),
                "tiers": {t: tier_counts[t] for t in TIERS}}
    history = _update_history(snapshot)

    return {
        "total": len(findings),
        "modules": mods,
        "own_shapes": shapes.most_common(),
        "own_shapes_fixed": sum(1 for s, _ in shapes.most_common() if s != "other"),
        "clusters": clusters,
        "fixable_pct": (round(100 * sum(c for s, c in by_source.items()
                                        if sources[s]["codefix"]) / len(findings))
                        if findings else 0),
        "tier_gates": {t: gate_for_tier(t) for t in TIERS},
        "dims": {"paths": paths.items, "rules": rules.items, "tools": tools.items,
                 "cats": cats.items, "sources": sources, "modules": [*mod_names, "(other)"],
                 "tiers": TIERS},
        "rule_src": rule_src,
        "rows": rows,
        "history": history,
    }


def _update_history(snapshot: dict) -> list:
    """Append this run's snapshot to viz/history.jsonl and return the full series — the
    trend chart's source. A run's identity is the `findings.json` content digest: any new
    audit (changed findings) is appended as its own point, even if it shares a date or the
    same aggregate counts as a prior run; only a plain re-render of the *same* findings
    (identical digest) is collapsed, so rebuilding the dashboard stays idempotent."""
    series = []
    if os.path.exists(HISTORY):
        with open(HISTORY, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    series.append(json.loads(line))
    if not (series and series[-1].get("digest") == snapshot["digest"]):
        series.append(snapshot)
    series.sort(key=lambda s: s["date"])
    with open(HISTORY, "w", encoding="utf-8") as fh:
        for s in series:
            fh.write(json.dumps(s) + "\n")
    return series


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
  .kpis{display:flex;flex-wrap:wrap;gap:14px;padding:18px 34px 6px}
  .kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:15px 20px;min-width:158px;
    backdrop-filter:blur(10px);transition:transform .2s, border-color .2s}
  .kpi:hover{transform:translateY(-3px);border-color:var(--accent)}
  .kpi .n{font-size:28px;font-weight:800;letter-spacing:-.5px;text-shadow:0 0 22px var(--glow)}
  .kpi .l{color:var(--mut);font-size:12.5px;margin-top:3px}
  .kpi .n.ok{color:var(--ok);text-shadow:0 0 22px color-mix(in srgb,var(--ok) 50%,transparent)}
  /* filter bar */
  .filters{padding:10px 34px 4px;display:flex;flex-wrap:wrap;gap:16px;align-items:center}
  .fgroup{display:flex;gap:7px;align-items:center;flex-wrap:wrap}
  .fgroup .lbl{color:var(--mut);font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;margin-right:2px}
  .chip{cursor:pointer;border:1px solid var(--line);background:var(--card);color:var(--mut);
    border-radius:999px;padding:5px 12px;font:600 12.5px/1 var(--font);transition:.15s;white-space:nowrap}
  .chip:hover{color:var(--fg);border-color:var(--accent)}
  .chip.on{color:#fff;border-color:transparent;background:linear-gradient(92deg,var(--accent),var(--c4));box-shadow:0 0 0 1px var(--accent)}
  .chip .x{opacity:.7;margin-left:5px}
  #clear{cursor:pointer;border:1px dashed var(--line);background:transparent;color:var(--mut);
    border-radius:999px;padding:5px 12px;font:600 12.5px/1 var(--font)}
  #clear:hover{color:var(--fg);border-color:var(--accent)}
  #fcount{color:var(--mut);font-size:12.5px;margin-left:auto}
  #fcount b{color:var(--fg)}
  .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;padding:14px 34px 44px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:10px 10px 6px;
    backdrop-filter:blur(10px);transition:transform .2s, border-color .2s, box-shadow .2s}
  .card:hover{transform:translateY(-2px);border-color:var(--line);box-shadow:0 14px 40px rgba(0,0,0,.35)}
  .card h2{font-size:14px;margin:9px 13px 0;font-weight:700}
  .card p{font-size:12px;color:var(--mut);margin:3px 13px 7px}
  .wide{grid-column:1/-1}
  .plot{width:100%;height:360px}
  .tall{height:470px}
  /* drill-down table */
  .tablecard{max-height:520px;overflow:auto}
  table{border-collapse:collapse;width:100%;font-size:12.5px;margin:4px 0 2px}
  thead th{position:sticky;top:0;background:var(--bg2);color:var(--mut);text-align:left;
    font-weight:700;padding:7px 13px;border-bottom:1px solid var(--line);z-index:1}
  tbody td{padding:6px 13px;border-bottom:1px solid var(--line);white-space:nowrap;
    overflow:hidden;text-overflow:ellipsis;max-width:420px}
  tbody tr:hover{background:rgba(120,140,180,.08)}
  .tg{font-weight:700;border-radius:5px;padding:1px 7px;font-size:11px}
  code{color:var(--accent);background:rgba(120,140,180,.12);padding:1px 5px;border-radius:5px}
  footer{color:var(--mut);font-size:12px;padding:0 34px 34px}
  @media(max-width:880px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body data-theme="midnight">
<header>
  <div>
    <h1>OwnAudit — STS health dashboard</h1>
    <div class="sub">Static audit of <code>STS_new/SectorTS</code> — a legacy .NET 4.7.2 / WPF / DevExpress app. Filter by tool/category, click a module to drill into its findings, switch themes.</div>
  </div>
  <div class="themes" id="themes"></div>
</header>
<div class="kpis" id="kpis"></div>
<div class="filters">
  <div class="fgroup" id="f-tools"><span class="lbl">Tool</span></div>
  <div class="fgroup" id="f-cats"><span class="lbl">Category</span></div>
  <div class="fgroup" id="f-mod"></div>
  <button id="clear">clear filters</button>
  <span id="fcount"></span>
</div>
<div class="grid">
  <div class="card wide"><h2>Where it hurts most</h2><p>Modules sized by pain index (severity x cross-tool agreement), coloured by share of high-confidence findings. <b>Click a tile to drill into its findings ↓</b></p><div id="treemap" class="plot tall"></div></div>
  <div class="card"><h2>Fix tiers — how the backlog is remediated</h2><p>T1 auto · T2 review · T3 unfixable (detect-only) · T4 bespoke (OWN). Respects the filters.</p><div id="tiers" class="plot"></div></div>
  <div class="card"><h2>Findings by category</h2><p>What kind of problem.</p><div id="cat" class="plot"></div></div>
  <div class="card"><h2>By analyzer source — does it ship a fix?</h2><p>Green = an analyzer with a CodeFixProvider → wire, don't build.</p><div id="src" class="plot"></div></div>
  <div class="card"><h2>By tool</h2><p>Who flagged it.</p><div id="tool" class="plot"></div></div>
  <div class="card"><h2>Top rules</h2><p>The most frequent diagnostics.</p><div id="rules" class="plot"></div></div>
  <div class="card wide"><h2>OWN fixer — shape coverage</h2><p>The leak shapes own-check flags that no off-the-shelf tool fixes — and how the bespoke T4 fixer remediates each.</p><div id="own" class="plot"></div></div>
  <div class="card wide"><h2>Trend across runs</h2><p>Total findings and per-tier split over time — one point per audit run (from <code>viz/history.jsonl</code>).</p><div id="trend" class="plot"></div></div>
  <div class="card wide tablecard"><h2 id="tbl-h">Findings</h2><p id="tbl-p">Filtered findings. Apply a filter or click a module to narrow this down.</p><div id="tablewrap"></div></div>
</div>
<footer>Generated by <code>viz/build_dashboard.py</code> from <code>sts_audit/</code> · raw findings clustered to %CLUSTERS% (high-confidence = ≥2 tools agree).</footer>
<script>
const D = %DATA%;
const D_ = D.dims;
const P=0, LN=1, RU=2, TO=3, CA=4, TI=5, MO=6;            // row column indices
const TIERMETA={T1:{g:'auto',c:'--c2'},T2:{g:'review',c:'--c1'},T3:{g:'unfixable',c:'--mute'},T4:{g:'bespoke',c:'--c3'}};
// audit-derived strings (paths/rules/categories/tools/module names) are escaped before
// any innerHTML so a crafted name can't inject HTML into the generated dashboard.
function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

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
document.getElementById('themes').innerHTML=Object.entries(THEMES)
  .map(([k,t])=>`<button data-t="${k}">${t.label}</button>`).join('');
document.getElementById('themes').onclick=e=>{const b=e.target.closest('button'); if(b) applyTheme(b.dataset.t);};

// ---- KPIs (global, filter-independent) ----------------------------------
const kpis=[[D.total.toLocaleString(),'raw findings'],[D.fixable_pct+'%','auto-fixable (ships a fix)','ok'],
  [D.clusters.high.toLocaleString(),'high-confidence clusters'],[D.modules.length,'modules ranked'],
  [D.own_shapes_fixed,'OWN leak shapes fixed','ok']];
document.getElementById('kpis').innerHTML=kpis.map(k=>
  `<div class="kpi"><div class="n ${k[2]||''}">${k[0]}</div><div class="l">${k[1]}</div></div>`).join('');

// ---- filter state -------------------------------------------------------
const F={tools:new Set(), cats:new Set(), module:null};
function filteredRows(){
  return D.rows.filter(r=>
    (F.tools.size===0 || F.tools.has(r[TO])) &&
    (F.cats.size===0  || F.cats.has(r[CA])) &&
    (F.module===null  || r[MO]===F.module));
}
function aggCount(rows, col){
  const m=new Map();
  for(const r of rows){const k=r[col]; m.set(k,(m.get(k)||0)+1);}
  return m;
}
function topPairs(map, names, n){
  return [...map.entries()].map(([k,v])=>[names[k],v]).sort((a,b)=>b[1]-a[1]).slice(0,n||999);
}

// chips for tools + categories
function chipRow(host, names, set){
  host.querySelectorAll('.chip').forEach(c=>c.remove());
  names.forEach((nm,i)=>{
    const b=document.createElement('button');
    b.className='chip'+(set.has(i)?' on':''); b.textContent=nm; b.dataset.i=i;
    b.onclick=()=>{ set.has(i)?set.delete(i):set.add(i); chipRow(host,names,set); update(); };
    host.appendChild(b);
  });
}
function renderModChip(){
  const host=document.getElementById('f-mod');
  host.innerHTML='';
  if(F.module===null) return;
  const b=document.createElement('button');
  b.className='chip on';
  b.innerHTML=`module: ${esc(D_.modules[F.module])} <span class="x">✕</span>`;
  b.onclick=()=>{ F.module=null; renderModChip(); update(); };
  host.appendChild(b);
}
document.getElementById('clear').onclick=()=>{
  F.tools.clear(); F.cats.clear(); F.module=null;
  chipRow(document.getElementById('f-tools'),D_.tools,F.tools);
  chipRow(document.getElementById('f-cats'),D_.cats,F.cats);
  renderModChip(); update();
};

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

function drawTreemap(){
  const t=THEMES[CUR];
  const ratio=D.modules.map(m=>m.findings?m.high/m.findings:0);
  Plotly.react('treemap',[{type:'treemap',
    labels:D.modules.map(m=>m.module), parents:D.modules.map(()=>''),
    values:D.modules.map(m=>m.pain), textinfo:'label+value',
    marker:{colors:ratio,colorscale:t.scale,cmin:0,cmax:0.6,line:{color:cssv('--bg'),width:1.5}},
    customdata:D.modules.map(m=>[m.findings,m.high,m.cat]),
    hovertemplate:'<b>%{label}</b><br>pain %{value}<br>%{customdata[0]} findings · %{customdata[1]} high-conf<br>top: %{customdata[2]}<br><i>click to drill in</i><extra></extra>'}],
    base({margin:{l:4,r:4,t:4,b:4}}),CFG);
  const el=document.getElementById('treemap');
  el.removeAllListeners&&el.removeAllListeners('plotly_treemapclick');
  el.on('plotly_treemapclick',ev=>{
    const lab=ev.points&&ev.points[0]&&ev.points[0].label;
    const i=D_.modules.indexOf(lab);
    if(i>=0){ F.module=i; renderModChip(); update();
      document.getElementById('tbl-h').scrollIntoView({behavior:'smooth',block:'center'}); }
    return false;
  });
}

function drawTiers(rows){
  const m=aggCount(rows,TI);
  const labels=D_.tiers, vals=labels.map((_,i)=>m.get(i)||0);
  const cols=labels.map(t=>cssv(TIERMETA[t].c));
  Plotly.react('tiers',[{type:'bar', x:labels, y:vals, marker:{color:cols},
    customdata:labels.map(t=>`${TIERMETA[t].g} · ${D.tier_gates[t]}`),
    text:vals.map(v=>v.toLocaleString()), textposition:'outside',
    hovertemplate:'<b>%{x}</b> — %{customdata}<br>%{y} findings<extra></extra>'}],
    base({margin:{l:50,r:10,t:18,b:30}}),CFG);
}

const TG_COL={T1:'--c2',T2:'--c1',T3:'--mute',T4:'--c3'};
function drawTable(rows){
  const cap=300;
  document.getElementById('tbl-h').textContent =
    `Findings — ${rows.length.toLocaleString()}${F.module!==null?` in ${D_.modules[F.module]}`:''}`;
  document.getElementById('tbl-p').textContent = rows.length>cap
    ? `Showing the first ${cap}. Narrow with the tool/category chips or a module.`
    : (rows.length?`Each row is one finding.`:`No findings match the current filters.`);
  const rowsHtml=rows.slice(0,cap).map(r=>{
    const tier=D_.tiers[r[TI]];
    return `<tr><td>${esc(D_.paths[r[P]])}</td><td>${esc(r[LN])}</td>`+
      `<td><code>${esc(D_.rules[r[RU]])}</code></td>`+
      `<td><span class="tg" style="background:${cssv(TG_COL[tier])};color:#0b0f17">${esc(tier)}</span></td>`+
      `<td>${esc(D_.cats[r[CA]])}</td><td>${esc(D_.tools[r[TO]])}</td></tr>`;
  }).join('');
  document.getElementById('tablewrap').innerHTML=
    `<table><thead><tr><th>File</th><th>Line</th><th>Rule</th><th>Tier</th><th>Category</th><th>Tool</th></tr></thead>`+
    `<tbody>${rowsHtml}</tbody></table>`;
}

function drawTrend(){
  const h=D.history, x=h.map(s=>s.date);
  const traces=[{x, y:h.map(s=>s.total), name:'total', mode:'lines+markers', type:'scatter',
    line:{color:cssv('--accent'),width:2}, marker:{size:7}}];
  D_.tiers.forEach(t=>traces.push({x, y:h.map(s=>(s.tiers&&s.tiers[t])||0), name:t,
    mode:'lines+markers', type:'scatter', line:{color:cssv(TIERMETA[t].c),width:1.5}, marker:{size:5}}));
  const lay=base({showlegend:true, legend:{orientation:'h',y:-0.2,font:{color:cssv('--mut')}},
    margin:{l:60,r:16,t:10,b:40}});
  if(h.length<2){
    lay.annotations=[{text:'single run so far — the trend fills in on the next audit',
      xref:'paper',yref:'paper',x:.5,y:.5,showarrow:false,font:{color:cssv('--mut'),size:13}}];
  }
  Plotly.react('trend',traces,lay,CFG);
}

function update(){
  const rows=filteredRows();
  document.getElementById('fcount').innerHTML=
    `<b>${rows.length.toLocaleString()}</b> / ${D.total.toLocaleString()} findings`;
  bar('cat', topPairs(aggCount(rows,CA), D_.cats), true, '--c1');
  bar('tool', topPairs(aggCount(rows,TO), D_.tools), false, '--c3');
  bar('rules', topPairs(aggCount(rows,RU), D_.rules, 18), true, '--c4');
  // source: group rows by analyzer family via rule_src
  const sm=new Map();
  for(const r of rows){const s=D.rule_src[r[RU]]; sm.set(s,(sm.get(s)||0)+1);}
  const spairs=[...sm.entries()].sort((a,b)=>b[1]-a[1]);
  Plotly.react('src',[{type:'bar',orientation:'h',
    y:spairs.map(p=>D_.sources[p[0]].name), x:spairs.map(p=>p[1]),
    marker:{color:spairs.map(p=>D_.sources[p[0]].codefix?cssv('--ok'):cssv('--mute'))},
    customdata:spairs.map(p=>D_.sources[p[0]].codefix?'ships a code fix':'detect-only / bespoke'),
    hovertemplate:'<b>%{y}</b><br>%{x} findings<br>%{customdata}<extra></extra>'}],
    base({margin:{l:170,r:16,t:6,b:24}}),CFG);
  drawTiers(rows);
  drawTable(rows);
}

function renderAll(){
  drawTreemap();
  bar('own', D.own_shapes, true, '--ok');     // static narrative, filter-independent
  drawTrend();
  update();
}

// init
chipRow(document.getElementById('f-tools'),D_.tools,F.tools);
chipRow(document.getElementById('f-cats'),D_.cats,F.cats);
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


def _json_for_script(data: dict) -> str:
    """Serialize for embedding inside a <script> block: escape <, >, & to their \\uXXXX
    forms so no audit-derived value (a path/rule/module containing </script>, <!--, etc.)
    can break out of the script context. The result is still valid JSON to JSON.parse."""
    return (json.dumps(data).replace("&", "\\u0026")
            .replace("<", "\\u003c").replace(">", "\\u003e"))


def main():
    data = collect()
    out = HTML.replace("%PLOTLY%", _plotly_tag()) \
              .replace("%DATA%", _json_for_script(data)) \
              .replace("%CLUSTERS%", f"{data['clusters']['total']:,} clusters")
    dst = os.path.join(ROOT, "viz", "sts-dashboard.html")
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"wrote {dst}  ({len(out):,} bytes; {data['total']:,} findings, "
          f"{len(data['modules'])} modules, {len(data['history'])} run(s))")


if __name__ == "__main__":
    main()
