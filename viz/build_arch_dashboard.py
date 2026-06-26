"""Architecture / drift / runtime dashboard (Own.NET Auditor phases 3-5).

A standalone single-file HTML view over the *new* engines (data + styles inlined; Plotly
inlined when viz/plotly.min.js is vendored, else loaded from the CDN) — separate from
viz/build_dashboard.py (which visualizes the 72k raw audit findings) so neither has to
refactor the other. It computes straight from the stand artifacts via the engine modules:

    graph.json            -> coupling metrics (Ca/Ce/Instability, A/D when present) + arch findings
    drift.json            -> architecture drift risk buckets + items
    findings.json + runtime.json -> runtime leak correlation (confirmed / static-only / blind spot)

Every section is optional: with no artifact it renders a muted empty-state, so the build
smokes in CI (where the stand artifacts aren't present) and lights up on the stand.
Build-free, stdlib + the engine modules only.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from arch.graph import Graph                                              # noqa: E402
from arch.metrics import component_metrics                               # noqa: E402
from arch import rules as arch_rules                                     # noqa: E402
from arch import drift as arch_drift                                     # noqa: E402
from runtime import correlate as rt                                      # noqa: E402

RISK_ORDER = ("high", "medium", "low", "info")
CONF_ORDER = ("high", "medium")


def _safe_json(path):
    """Load JSON, distinguishing a MISSING artifact (-> None, a legit empty-state) from a
    PRESENT but malformed one (-> raise). A stale/corrupt artifact should fail loudly, not be
    silently rendered as 'not collected yet'."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON in {path}: {e}") from e


def collect(graph_path, drift_path, findings_path, runtime_path) -> dict:
    data = {"meta": {"types": None, "edges": None, "cycles": None,
                     "confirmed": None, "drift_high": None},
            "metrics": [], "arch_by_rule": [], "has_abstractness": False,
            "drift": None, "runtime": None}

    graph_raw = _safe_json(graph_path)
    if graph_raw is not None:
        g = Graph(graph_raw)            # a present-but-invalid/stale graph raises here, not None
        m = component_metrics(g, "namespace")
        data["metrics"] = [dict(ns=ns, **rec) for ns, rec in sorted(m.items())]
        data["has_abstractness"] = any(r["abstractness"] is not None for r in m.values())
        findings = arch_rules.run(g, arch_rules.load_rules())
        data["arch_by_rule"] = collections.Counter(f["rule"] for f in findings).most_common()
        data["meta"]["types"] = len(g.type_ids())
        data["meta"]["edges"] = len(g.unique_edges())
        data["meta"]["cycles"] = (len(g.type_cycles()) + len(g.namespace_cycles())
                                  + len(g.assembly_cycles()))

    drift = _safe_json(drift_path)
    if drift is not None:               # present -> must be well-formed, else fail (not empty-state)
        if not isinstance(drift, dict) or not isinstance(drift.get("items"), list):
            raise ValueError(f"{drift_path} must be a drift.json object with list-valued 'items'")
        buckets = collections.Counter(i.get("risk") for i in drift["items"])
        data["drift"] = {
            "counts": [buckets.get(r, 0) for r in RISK_ORDER],
            "items": [{"risk": i.get("risk"), "kind": i.get("kind"), "detail": i.get("detail")}
                      for i in drift["items"][:80]],
            "new_cycles": drift.get("new_cycles", 0), "new_edges": drift.get("new_edges", 0)}
        data["meta"]["drift_high"] = buckets.get("high", 0)

    static = _safe_json(findings_path)
    dump = _safe_json(runtime_path)
    if dump is not None:                # present runtime.json -> must be a JSON object
        if not isinstance(dump, dict):
            raise ValueError(f"{runtime_path} must be a runtime.json object")
        # findings.json is normally {"findings": [...]} but accept a top-level list too; a
        # present-but-wrong shape fails loudly, a missing file (static is None) just skips.
        if isinstance(static, dict):
            if not isinstance(static.get("findings"), list):
                raise ValueError(f"{findings_path} must contain a list-valued 'findings'")
            static_findings = static["findings"]
        else:
            static_findings = static if isinstance(static, list) else None
        if static_findings is not None:
            res = rt.correlate(static_findings, dump, rt.load_config())
            leaks = res["confirmed"] + res["runtime_only"]
            data["runtime"] = {
                "confirmed": len(res["confirmed"]), "static_only": len(res["static_only"]),
                "runtime_only": len(res["runtime_only"]), "scenario": dump.get("scenario", ""),
                "leaks": [{"resource": f.get("resource"), "confidence": f.get("confidence"),
                           "retained": f.get("retained"), "expected": f.get("expected"),
                           "category": f.get("category_name"), "message": f.get("message")}
                          for f in leaks[:80]]}
            data["meta"]["confirmed"] = len(res["confirmed"])
    return data


# --------------------------------------------------------------------------- HTML

HTML = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Own.NET Auditor — architecture · drift · runtime</title>
%PLOTLY%
<style>
:root{--bg:#0b0f17;--bg2:#0e1422;--card:rgba(20,27,42,.72);--line:rgba(120,140,180,.16);
--fg:#e8eef7;--mut:#8b97a8;--c1:#58a6ff;--c2:#3fb950;--c3:#bc8cff;--c4:#39c5cf;
--hi:#f85149;--me:#d29922;--lo:#58a6ff;--in:#6b7686;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
background-image:radial-gradient(1100px 560px at 82% -12%,rgba(56,90,170,.30),transparent 60%);}
header{padding:26px 30px 6px}h1{margin:0;font-size:21px;letter-spacing:.2px}
.sub{color:var(--mut);margin:4px 0 0}
.kpis{display:flex;gap:14px;flex-wrap:wrap;padding:16px 30px 4px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 18px;min-width:130px}
.kpi .n{font-size:24px;font-weight:700}.kpi .n.ok{color:var(--c2)}.kpi .n.bad{color:var(--hi)}
.kpi .l{color:var(--mut);font-size:12px}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;padding:16px 30px 40px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px 18px;min-width:0}
.card.wide{grid-column:1/-1}h2{margin:0 0 2px;font-size:15px}.card p{color:var(--mut);margin:0 0 10px;font-size:12px}
.plot{width:100%;height:320px}.plot.tall{height:420px}
.empty{color:var(--mut);font-style:italic;padding:26px 6px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:600;position:sticky;top:0;background:var(--bg2)}
.scroll{max-height:420px;overflow:auto;border-radius:10px}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:700}
.r-high{background:rgba(248,81,73,.18);color:#ff9a93}.r-medium{background:rgba(210,153,34,.18);color:#f0c560}
.r-low{background:rgba(88,166,255,.16);color:#9cc4ff}.r-info{background:rgba(107,118,134,.18);color:#aeb6c2}
code{background:rgba(120,140,180,.14);padding:1px 5px;border-radius:5px}
footer{color:var(--mut);padding:0 30px 30px;font-size:12px}
</style></head><body>
<header><h1>Own.NET Auditor — architecture · drift · runtime</h1>
<p class="sub">Phases 3&ndash;5 over the stand artifacts. Sections light up as <code>graph.json</code>, <code>drift.json</code> and <code>runtime.json</code> become available.</p></header>
<div class="kpis" id="kpis"></div>
<div class="grid">
  <div class="card wide"><h2>Coupling map — Martin's instability vs abstractness</h2>
    <p>Each namespace by Instability <code>I=Ce/(Ca+Ce)</code>. With an <code>is_abstract</code> flag the Y axis is Abstractness and the diagonal is the main sequence (distance D = how far off it sits); without it, bars of efferent coupling Ce.</p>
    <div id="coupling" class="plot tall"></div></div>
  <div class="card"><h2>Architecture findings by rule</h2><p>layering / cycles / god-class / coupling, from <code>arch.rules</code>.</p><div id="archrules" class="plot"></div></div>
  <div class="card"><h2>Drift risk</h2><p>Change vs the baseline snapshot, bucketed by risk.</p><div id="driftbar" class="plot"></div></div>
  <div class="card"><h2>Runtime correlation</h2><p>static &times; heap retention: confirmed leaks vs suspected FPs vs blind spots.</p><div id="rtdonut" class="plot"></div></div>
  <div class="card"><h2>Confirmed &amp; unpredicted leaks</h2><p id="rt-p">Runtime-confirmed leaks and the retentions static analysis missed.</p><div id="rttable" class="scroll"></div></div>
  <div class="card wide"><h2>Architecture drift — what moved</h2><p>Risk-tagged structural changes vs baseline.</p><div id="drifttable" class="scroll"></div></div>
  <div class="card wide"><h2>Per-namespace coupling metrics</h2><p>Ca (afferent) · Ce (efferent) · Instability · Abstractness · Distance.</p><div id="metrictable" class="scroll"></div></div>
</div>
<footer>Generated by <code>viz/build_arch_dashboard.py</code>. Build-free; computed from the stand artifacts via the engine modules.</footer>
<script>
const D = %DATA%;
function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function cv(n){return getComputedStyle(document.body).getPropertyValue(n).trim();}
const LAYOUT={paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{color:cv('--fg'),size:12},
  margin:{l:48,r:16,t:10,b:40},xaxis:{gridcolor:cv('--line')},yaxis:{gridcolor:cv('--line')}};
const CFG={displayModeBar:false,responsive:true};
function empty(id,msg){document.getElementById(id).outerHTML='<div class="empty">'+esc(msg)+'</div>';}

// KPIs
const m=D.meta;
const kpis=[[m.types,'internal types'],[m.edges,'dependency edges'],[m.cycles,'cycles (type+ns+asm)','bad'],
  [m.drift_high,'high-risk drifts','bad'],[m.confirmed,'runtime-confirmed leaks','bad']];
document.getElementById('kpis').innerHTML=kpis.filter(k=>k[0]!=null).map(k=>
  `<div class="kpi"><div class="n ${k[2]||''}">${Number(k[0]).toLocaleString()}</div><div class="l">${esc(k[1])}</div></div>`).join('')
  || '<div class="kpi"><div class="n">—</div><div class="l">no artifacts yet</div></div>';

// Coupling map
(function(){
  if(!D.metrics.length){empty('coupling','No graph.json — run the Roslyn extractor on the stand.');return;}
  const ms=D.metrics;
  if(D.has_abstractness){
    Plotly.newPlot('coupling',[
      {x:[0,1],y:[1,0],mode:'lines',line:{dash:'dot',color:cv('--mut')},hoverinfo:'skip',showlegend:false},
      {x:ms.map(r=>r.instability),y:ms.map(r=>r.abstractness),text:ms.map(r=>r.ns),mode:'markers+text',
       textposition:'top center',textfont:{size:9,color:cv('--mut')},
       marker:{size:ms.map(r=>8+Math.sqrt(r.types)*3),color:ms.map(r=>r.distance),colorscale:'YlOrRd',
       showscale:true,colorbar:{title:'D'},line:{width:1,color:cv('--line')}},
       hovertemplate:'%{text}<br>I=%{x}, A=%{y}<extra></extra>'}],
      Object.assign({},LAYOUT,{xaxis:{title:'Instability',range:[-.05,1.05],gridcolor:cv('--line')},
        yaxis:{title:'Abstractness',range:[-.05,1.05],gridcolor:cv('--line')}}),CFG);
  }else{
    const s=ms.slice().sort((a,b)=>b.ce-a.ce);
    Plotly.newPlot('coupling',[
      {x:s.map(r=>r.ns),y:s.map(r=>r.ce),name:'Ce (efferent)',type:'bar',marker:{color:cv('--c1')}},
      {x:s.map(r=>r.ns),y:s.map(r=>r.ca),name:'Ca (afferent)',type:'bar',marker:{color:cv('--c3')}}],
      Object.assign({},LAYOUT,{barmode:'group',xaxis:{gridcolor:cv('--line'),tickangle:-30}}),CFG);
  }
})();

// Arch findings by rule
(function(){
  if(!D.arch_by_rule.length){empty('archrules','No graph.json — no architecture findings yet.');return;}
  const r=D.arch_by_rule.slice().reverse();
  Plotly.newPlot('archrules',[{y:r.map(x=>x[0]),x:r.map(x=>x[1]),type:'bar',orientation:'h',
    marker:{color:cv('--c4')}}],Object.assign({},LAYOUT,{margin:{l:140,r:16,t:10,b:30}}),CFG);
})();

// Drift bar
(function(){
  if(!D.drift){empty('driftbar','No drift.json — run arch.drift_cli against a baseline snapshot.');return;}
  const labels=['high','medium','low','info'],cols=[cv('--hi'),cv('--me'),cv('--lo'),cv('--in')];
  Plotly.newPlot('driftbar',[{x:labels,y:D.drift.counts,type:'bar',marker:{color:cols}}],
    Object.assign({},LAYOUT,{}),CFG);
})();

// Runtime donut
(function(){
  if(!D.runtime){empty('rtdonut','No runtime.json — collect a heap dump on the stand.');return;}
  const rt=D.runtime;
  Plotly.newPlot('rtdonut',[{values:[rt.confirmed,rt.static_only,rt.runtime_only],
    labels:['confirmed','static-only (suspect FP)','runtime-only (blind spot)'],type:'pie',hole:.55,
    marker:{colors:[cv('--hi'),cv('--me'),cv('--c3')]},textinfo:'value'}],
    Object.assign({},LAYOUT,{margin:{l:10,r:10,t:10,b:10},showlegend:true,
      legend:{orientation:'h',y:-.1,font:{size:10}}}),CFG);
})();

// Runtime table
(function(){
  const host=document.getElementById('rttable');
  if(!D.runtime){host.outerHTML='<div class="empty">No runtime.json yet.</div>';return;}
  if(!D.runtime.leaks.length){host.innerHTML='<div class="empty">No confirmed or unpredicted leaks.</div>';return;}
  host.innerHTML='<table><thead><tr><th>type</th><th>conf</th><th>retained</th><th>kind</th></tr></thead><tbody>'+
    D.runtime.leaks.map(f=>`<tr><td>${esc(f.resource)}</td>`+
      `<td><span class="pill r-${f.confidence==='high'?'high':'medium'}">${esc(f.confidence)}</span></td>`+
      `<td>${esc(f.retained)} / ${esc(f.expected)}</td>`+
      `<td>${f.category==='runtime-confirmed-leak'?'confirmed':'blind spot'}</td></tr>`).join('')+
    '</tbody></table>';
})();

// Drift table
(function(){
  const host=document.getElementById('drifttable');
  if(!D.drift){host.outerHTML='<div class="empty">No drift.json yet.</div>';return;}
  if(!D.drift.items.length){host.innerHTML='<div class="empty">No drift vs baseline. 🎉</div>';return;}
  host.innerHTML='<table><thead><tr><th>risk</th><th>kind</th><th>detail</th></tr></thead><tbody>'+
    D.drift.items.map(i=>`<tr><td><span class="pill r-${esc(i.risk)}">${esc(i.risk)}</span></td>`+
      `<td>${esc(i.kind)}</td><td>${esc(i.detail)}</td></tr>`).join('')+'</tbody></table>';
})();

// Metrics table
(function(){
  const host=document.getElementById('metrictable');
  if(!D.metrics.length){host.outerHTML='<div class="empty">No graph.json yet.</div>';return;}
  const f=v=>v==null?'-':v;
  host.innerHTML='<table><thead><tr><th>namespace</th><th>types</th><th>Ca</th><th>Ce</th><th>I</th><th>A</th><th>D</th></tr></thead><tbody>'+
    D.metrics.slice().sort((a,b)=>b.ce-a.ce).map(r=>`<tr><td>${esc(r.ns)}</td><td>${r.types}</td>`+
      `<td>${r.ca}</td><td>${r.ce}</td><td>${r.instability}</td><td>${f(r.abstractness)}</td><td>${f(r.distance)}</td></tr>`).join('')+
    '</tbody></table>';
})();
</script></body></html>"""


def _plotly_tag() -> str:
    """Inline the vendored Plotly for a fully-offline file when viz/plotly.min.js is present
    (curl it into viz/ once); otherwise fall back to the CDN — the same contract as
    viz/build_dashboard.py. Warn loudly on fallback so a "self-contained" file that actually
    needs the network doesn't ship silently."""
    vendored = os.path.join(ROOT, "viz", "plotly.min.js")
    if os.path.exists(vendored):
        with open(vendored, encoding="utf-8") as fh:
            return "<script>" + fh.read() + "</script>"
    print("warning: viz/plotly.min.js is not vendored — the dashboard will load Plotly from the "
          "CDN (needs network); vendor it for a fully-offline file.", file=sys.stderr)
    # SRI-pinned so the remote bundle can't be swapped silently (hash of plotly-2.35.2.min.js,
    # byte-identical to the vendored copy).
    return ('<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" '
            'integrity="sha384-cCVCZkAjYNxaYKbM8lsArLznDF/SvMFr1jcZrvOpSTCa0W40ZAdLzHCEulnUa5i7" '
            'crossorigin="anonymous" charset="utf-8"></script>')


def _json_for_script(data: dict) -> str:
    """Escape <, >, & to \\uXXXX so no artifact-derived string can break out of <script>."""
    return (json.dumps(data).replace("&", "\\u0026")
            .replace("<", "\\u003c").replace(">", "\\u003e"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="build_arch_dashboard",
                                 description="Own.NET Auditor — architecture/drift/runtime dashboard")
    ap.add_argument("--graph", default=os.path.join(ROOT, "sts_audit", "graph.json"))
    ap.add_argument("--drift", default=os.path.join(ROOT, "arch", "out", "drift.json"))
    ap.add_argument("--findings", default=os.path.join(ROOT, "sts_audit", "findings.json"))
    ap.add_argument("--runtime", default=os.path.join(ROOT, "sts_audit", "runtime.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "viz", "arch-dashboard.html"))
    args = ap.parse_args(argv)

    data = collect(args.graph, args.drift, args.findings, args.runtime)
    out = HTML.replace("%PLOTLY%", _plotly_tag()).replace("%DATA%", _json_for_script(data))
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(out)
    present = [k for k, v in (("graph", data["metrics"]), ("drift", data["drift"]),
                              ("runtime", data["runtime"])) if v]
    print(f"wrote {args.out}  ({len(out):,} bytes; sections: {', '.join(present) or 'empty-state'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
