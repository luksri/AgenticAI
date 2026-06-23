"""Session 9 — interactive browser replay viewer.

Generates a self-contained HTML file you open in a browser.
Click ▶ to auto-play through every node in the session.
All data (screenshots, outputs, prompts) is embedded inline.

Usage:
    uv run python browser_report.py <session_id>
    uv run python browser_report.py          # lists available sessions

Output:
    state/sessions/<session_id>/report.html
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

from persistence import SessionStore, list_sessions
from schemas import NodeState

ROOT = Path(__file__).parent

SKILL_COLOR: dict[str, str] = {
    "planner":          "#6366f1",
    "browser":          "#0ea5e9",
    "distiller":        "#8b5cf6",
    "critic":           "#f59e0b",
    "formatter":        "#10b981",
    "researcher":       "#ec4899",
    "retriever":        "#14b8a6",
    "summariser":       "#f97316",
    "coder":            "#a855f7",
    "sandbox_executor": "#64748b",
}
PATH_COLOR: dict[str, str] = {
    "extract":       "#10b981",
    "deterministic": "#f59e0b",
    "a11y":          "#0ea5e9",
    "vision":        "#8b5cf6",
}


def _b64(path: str) -> str:
    try:
        data = base64.b64encode(Path(path).read_bytes()).decode()
        return f"data:image/png;base64,{data}"
    except Exception:
        return ""


def _node_to_dict(st: NodeState) -> dict:
    r = st.result
    out = r.output if r else None
    replay = (out or {}).get("replay") or {}
    shots_raw: list[str] = replay.get("screenshots") or []
    shots_b64 = [_b64(p) for p in shots_raw if _b64(p)]
    return {
        "node_id":    st.node_id,
        "skill":      st.skill,
        "status":     st.status,
        "elapsed":    round(r.elapsed_s or 0, 2) if r else 0,
        "provider":   (r.provider or "") if r else "",
        "error":      (r.error or "") if r else "",
        "output":     out,
        "prompt":     (st.prompt_sent or "")[:12_000],
        "screenshots": shots_b64,
        "replay":     {
            "planner_dag": replay.get("planner_dag") or [],
            "layer_trace": replay.get("layer_trace") or [],
            "actions":     (out or {}).get("actions") or [],
            "path":        (out or {}).get("path", ""),
            "turns":       (out or {}).get("turns", 0),
            "content":     (out or {}).get("content") or "",
            "cost":        (out or {}).get("cost_summary") or {},
        },
    }


# ── HTML / JS ─────────────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Replay · __SESSION_ID__</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:#0f172a;color:#e2e8f0;height:100vh;display:flex;flex-direction:column;overflow:hidden}

/* ── header ── */
#hdr{background:#1e293b;border-bottom:1px solid #334155;padding:14px 24px;
  display:flex;align-items:center;gap:16px;flex-shrink:0}
#hdr .sid{font-family:monospace;font-size:12px;color:#64748b}
#hdr .q{font-size:13px;color:#94a3b8;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#hdr .counter{font-size:12px;color:#475569;white-space:nowrap}

/* ── stage ── */
#stage{flex:1;overflow-y:auto;padding:28px 32px;display:flex;justify-content:center;align-items:flex-start}

/* ── card ── */
.card{width:100%;max-width:860px;background:#1e293b;border:1px solid #334155;
  border-radius:16px;padding:28px 32px;
  animation:fadeUp .35s ease forwards}
@keyframes fadeUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}

.card-header{display:flex;align-items:center;gap:12px;margin-bottom:22px;flex-wrap:wrap}
.skill-chip{padding:4px 14px;border-radius:20px;font-size:12px;font-weight:700;
  letter-spacing:.04em;text-transform:uppercase;color:#fff}
.node-id{font-family:monospace;font-size:13px;color:#475569}
.status-badge{font-size:12px;font-weight:600;padding:3px 10px;border-radius:12px}
.st-complete{background:#166534;color:#bbf7d0}
.st-failed  {background:#7f1d1d;color:#fecaca}
.st-skipped {background:#78350f;color:#fde68a}
.st-running {background:#0c4a6e;color:#bae6fd}
.st-pending {background:#1e3a5f;color:#93c5fd}
.elapsed{font-size:12px;color:#475569}
.provider{font-size:11px;color:#334155;background:#0f172a;padding:2px 8px;border-radius:6px}

/* ── sections ── */
.section{margin-bottom:20px}
.section-label{font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
  color:#475569;margin-bottom:10px}
.section-body{background:#0f172a;border-radius:10px;padding:14px 18px}

/* ── verdict ── */
.verdict-pass{text-align:center;padding:24px;border-radius:12px;background:#14532d}
.verdict-fail{text-align:center;padding:24px;border-radius:12px;background:#450a0a}
.verdict-icon{font-size:48px;display:block;margin-bottom:6px}
.verdict-word{font-size:22px;font-weight:900;letter-spacing:.05em}
.verdict-rat{font-size:13px;color:#94a3b8;margin-top:10px;line-height:1.6}

/* ── dag ── */
.dag{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.dag-chip{border:2px solid transparent;padding:4px 12px;border-radius:6px;
  font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.dag-arr{color:#334155;font-size:16px}

/* ── path badge ── */
.path-badge{display:inline-block;padding:5px 18px;border-radius:20px;
  font-size:13px;font-weight:700;color:#fff}

/* ── actions table ── */
table.acts{width:100%;border-collapse:collapse;font-size:12px}
table.acts th{color:#475569;font-weight:700;text-align:left;padding:6px 10px;
  border-bottom:1px solid #334155;text-transform:uppercase;font-size:10px;letter-spacing:.05em}
table.acts td{padding:7px 10px;border-bottom:1px solid #1e293b;vertical-align:top;
  font-family:monospace;word-break:break-all}
table.acts tr:last-child td{border-bottom:none}

/* ── screenshots ── */
.shots{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}
.shot-fig{border-radius:8px;overflow:hidden;border:1px solid #334155;background:#0f172a;cursor:zoom-in}
.shot-fig img{width:100%;display:block}
.shot-fig figcaption{font-size:10px;font-family:monospace;color:#475569;
  padding:4px 8px;background:#1e293b}

/* ── compare table ── */
table.cmp{width:100%;border-collapse:collapse;font-size:12px}
table.cmp thead tr{background:#0f172a}
table.cmp th{color:#94a3b8;padding:8px 12px;text-align:left;font-size:11px;
  border-bottom:1px solid #334155}
table.cmp td{padding:8px 12px;border-bottom:1px solid #1e293b}
table.cmp tr:nth-child(even) td{background:#0a0f1a}

/* ── fields (distiller) ── */
.fields dl{display:grid;grid-template-columns:auto 1fr;gap:4px 16px}
.fields dt{font-size:11px;color:#475569;font-weight:700;padding-top:6px}
.fields dd{font-size:13px;color:#cbd5e1;padding-top:6px;word-break:break-word}

/* ── plan list ── */
.plan-list{list-style:none;display:flex;flex-direction:column;gap:8px}
.plan-item{background:#0f172a;border-radius:8px;padding:10px 14px;
  display:flex;align-items:baseline;gap:10px}
.plan-num{font-size:11px;color:#475569;font-family:monospace;min-width:22px}
.plan-skill{font-size:12px;font-weight:700;padding:2px 10px;border-radius:10px;color:#fff}
.plan-q{font-size:12px;color:#94a3b8;margin-top:4px;font-style:italic}

/* ── json / text ── */
.pre{font-family:monospace;font-size:11px;color:#94a3b8;white-space:pre-wrap;
  word-break:break-word;max-height:280px;overflow-y:auto;line-height:1.7}
.extracted{font-family:monospace;font-size:11px;color:#94a3b8;white-space:pre-wrap;
  word-break:break-word;max-height:220px;overflow-y:auto;line-height:1.7}

/* ── prompt drawer ── */
.prompt-toggle{background:none;border:1px solid #334155;color:#475569;
  font-size:11px;padding:4px 12px;border-radius:6px;cursor:pointer;margin-top:4px}
.prompt-toggle:hover{background:#1e293b;color:#94a3b8}
#prompt-drawer{display:none;background:#0a0f1a;border:1px solid #1e293b;
  border-radius:10px;padding:14px;margin-top:10px;
  font-family:monospace;font-size:11px;color:#64748b;white-space:pre-wrap;
  word-break:break-word;max-height:260px;overflow-y:auto;line-height:1.6}

/* ── error ── */
.err-box{background:#450a0a;border:1px solid #7f1d1d;border-radius:8px;
  padding:12px 16px;font-size:12px;color:#fca5a5;font-family:monospace;
  word-break:break-word}

/* ── cost cards ── */
.cost-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:10px}
.cost-card{background:#0f172a;border:1px solid #334155;border-radius:8px;
  padding:12px;text-align:center}
.cost-val{font-size:20px;font-weight:800;color:#e2e8f0}
.cost-lbl{font-size:10px;color:#475569;text-transform:uppercase;
  letter-spacing:.05em;margin-top:4px}

/* ── lightbox ── */
#lb{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);
  z-index:1000;align-items:center;justify-content:center;cursor:zoom-out}
#lb.open{display:flex}
#lb img{max-width:92vw;max-height:92vh;border-radius:8px;box-shadow:0 0 60px rgba(0,0,0,.8)}

/* ── timeline ── */
#timeline{background:#0f172a;border-top:1px solid #1e293b;padding:10px 24px;
  display:flex;gap:6px;overflow-x:auto;flex-shrink:0;scroll-behavior:smooth;
  scrollbar-width:thin;scrollbar-color:#334155 transparent}
.tn{width:38px;height:38px;border-radius:8px;border:2px solid transparent;
  display:flex;align-items:center;justify-content:center;cursor:pointer;
  flex-shrink:0;transition:transform .15s,border-color .15s;position:relative}
.tn:hover{transform:scale(1.15)}
.tn.active{border-color:#e2e8f0;transform:scale(1.15)}
.tn-label{font-size:9px;font-weight:800;letter-spacing:.03em;color:#fff;text-transform:uppercase}
.tn-dot{position:absolute;bottom:2px;left:50%;transform:translateX(-50%);
  width:5px;height:5px;border-radius:50%;background:#22c55e;display:none}
.tn.done .tn-dot{display:block}

/* ── controls ── */
#controls{background:#1e293b;border-top:1px solid #334155;padding:12px 24px;
  display:flex;align-items:center;gap:14px;flex-shrink:0}
.ctrl-btn{background:#0f172a;border:1px solid #334155;color:#94a3b8;
  width:38px;height:38px;border-radius:10px;cursor:pointer;
  font-size:16px;display:flex;align-items:center;justify-content:center;
  transition:background .1s,color .1s}
.ctrl-btn:hover{background:#334155;color:#e2e8f0}
.ctrl-btn:active{transform:scale(.93)}
#btn-play{background:#6366f1;border-color:#6366f1;color:#fff;width:46px;height:46px;
  border-radius:12px;font-size:20px}
#btn-play:hover{background:#4f46e5}

#scrubber{flex:1;-webkit-appearance:none;height:4px;border-radius:2px;
  background:#334155;outline:none;cursor:pointer}
#scrubber::-webkit-slider-thumb{-webkit-appearance:none;width:16px;height:16px;
  border-radius:50%;background:#6366f1;cursor:pointer;
  transition:transform .1s}
#scrubber::-webkit-slider-thumb:hover{transform:scale(1.3)}

.speed-btn{background:#0f172a;border:1px solid #334155;color:#64748b;
  font-size:11px;padding:4px 10px;border-radius:6px;cursor:pointer;
  transition:background .1s,color .1s}
.speed-btn.active{background:#334155;color:#e2e8f0;font-weight:700}
.speed-btn:hover{background:#334155;color:#e2e8f0}

#pos-label{font-size:12px;color:#475569;white-space:nowrap;min-width:50px;text-align:center}
</style>
</head>
<body>

<div id="hdr">
  <span class="sid">__SESSION_ID__</span>
  <span class="q" id="q-text"></span>
  <span class="counter" id="hdr-counter"></span>
</div>

<div id="stage"><div class="card" id="node-card"></div></div>

<div id="timeline" id="tl"></div>

<div id="controls">
  <button class="ctrl-btn" id="btn-first" title="First">⏮</button>
  <button class="ctrl-btn" id="btn-prev"  title="Previous">◀</button>
  <button class="ctrl-btn" id="btn-play"  title="Play/Pause">▶</button>
  <button class="ctrl-btn" id="btn-next"  title="Next">▶</button>
  <button class="ctrl-btn" id="btn-last"  title="Last">⏭</button>
  <input type="range" id="scrubber" min="0" step="1">
  <span id="pos-label">1 / 1</span>
  <button class="speed-btn" data-s="2"  >0.5×</button>
  <button class="speed-btn active" data-s="1">1×</button>
  <button class="speed-btn" data-s=".5" >2×</button>
  <button class="speed-btn" data-s=".33">3×</button>
</div>

<div id="lb"><img id="lb-img" src="" alt="screenshot"></div>

<script>
// ── data ──────────────────────────────────────────────────────────────────────
const DATA = __DATA_JSON__;

// ── helpers ───────────────────────────────────────────────────────────────────
const SKILL_COLOR = __SKILL_COLOR__;
const PATH_COLOR  = __PATH_COLOR__;

function esc(s){ return String(s||"")
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
  .replace(/"/g,"&quot;").replace(/'/g,"&#39;"); }

function skillChip(sk){
  const c=SKILL_COLOR[sk]||"#64748b";
  return `<span class="skill-chip" style="background:${c}">${esc(sk)}</span>`;
}

function statusBadge(st){
  const cls=`st-${st||"pending"}`;
  const icon={complete:"✓",failed:"✗",skipped:"⊘",running:"…",pending:"·"}[st]||"?";
  return `<span class="status-badge ${cls}">${icon} ${esc(st)}</span>`;
}

function mdTableToHtml(text){
  if(!text) return "";
  const lines=text.split("\n");
  let buf=[],out=[],inT=false;
  function flushTable(){
    if(!buf.length) return;
    const rows=buf
      .filter(l=>!/^\s*\|?\s*[-:]+[-|: ]*\|?\s*$/.test(l))
      .map(l=>l.trim().replace(/^\||\|$/g,"").split("|").map(c=>c.trim()));
    if(!rows.length){buf=[];return;}
    const [hdr,...data]=rows;
    const th=hdr.map(h=>`<th>${esc(h)}</th>`).join("");
    const tb=data.map(r=>{
      while(r.length<hdr.length) r.push("");
      return "<tr>"+r.slice(0,hdr.length).map(c=>`<td>${esc(c)}</td>`).join("")+"</tr>";
    }).join("");
    out.push(`<table class="cmp"><thead><tr>${th}</tr></thead><tbody>${tb}</tbody></table>`);
    buf=[];
  }
  for(const ln of lines){
    if(/^\s*\|/.test(ln)){buf.push(ln);inT=true;}
    else{if(inT){flushTable();inT=false;} if(ln.trim()) out.push(`<p style="font-size:12px;color:#94a3b8;margin:4px 0">${esc(ln)}</p>`);}
  }
  flushTable();
  return out.join("\n");
}

// ── per-skill renderers ────────────────────────────────────────────────────────
function renderPlanner(node){
  const nodes=(node.output||{}).nodes||[];
  if(!nodes.length) return renderDefault(node);
  const items=nodes.map((n,i)=>{
    const c=SKILL_COLOR[n.skill]||"#64748b";
    const q=n.metadata&&n.metadata.question?`<div class="plan-q">"${esc(n.metadata.question)}"</div>`:"";
    const inp=(n.inputs||[]).join(", ");
    return `<li class="plan-item">
      <span class="plan-num">${i+1}.</span>
      <div style="flex:1">
        <span class="plan-skill" style="background:${c}">${esc(n.skill)}</span>
        <span style="font-size:11px;color:#475569;margin-left:8px">inputs: ${esc(inp)}</span>
        ${q}
      </div>
    </li>`;
  }).join("");
  return `<div class="section">
    <div class="section-label">Plan — ${nodes.length} node(s)</div>
    <div class="section-body"><ul class="plan-list">${items}</ul></div>
  </div>`;
}

function renderCritic(node){
  const out=node.output||{};
  const verdict=(out.verdict||"").toLowerCase();
  const pass=verdict==="pass";
  const icon=pass?"✓":"✗";
  const cls=pass?"verdict-pass":"verdict-fail";
  const color=pass?"#4ade80":"#f87171";
  return `<div class="section">
    <div class="section-body" style="padding:0;border-radius:10px;overflow:hidden">
      <div class="${cls}">
        <span class="verdict-icon">${icon}</span>
        <span class="verdict-word" style="color:${color}">${esc(out.verdict||"?").toUpperCase()}</span>
        ${out.rationale?`<p class="verdict-rat">${esc(out.rationale)}</p>`:""}
      </div>
    </div>
  </div>`;
}

function renderBrowser(node){
  const rp=node.replay||{};
  const dag=rp.planner_dag||[];
  const actions=rp.actions||[];
  const shots=node.screenshots||[];
  const content=rp.content||"";
  const cost=rp.cost||{};
  const path=rp.path||"?";
  const turns=rp.turns||0;
  const pc=PATH_COLOR[path]||"#64748b";
  let html="";

  // DAG
  if(dag.length){
    const chips=dag.map(s=>{
      const c=SKILL_COLOR[s]||"#64748b";
      return `<span class="dag-chip" style="border-color:${c};color:${c}">${esc(s)}</span>`;
    }).join('<span class="dag-arr">→</span>');
    html+=`<div class="section">
      <div class="section-label">① Planner DAG</div>
      <div class="section-body"><div class="dag">${chips}</div></div>
    </div>`;
  }

  // layer trace
  const trace=rp.layer_trace||[];
  if(trace.length){
    const LAYER_COLOR={"used":"#22c55e","skipped":"#475569","tried":"#f59e0b","blocked":"#ef4444"};
    const rows=trace.map(t=>{
      const st=(t.status||"").toLowerCase();
      const col=LAYER_COLOR[st]||"#64748b";
      const turns=t.turns!=null?`<td style="color:#64748b;text-align:right">${t.turns} turns</td>`:`<td></td>`;
      return `<tr>
        <td style="font-family:monospace;font-size:11px;color:#94a3b8;white-space:nowrap">${esc(t.layer||"")}</td>
        <td><span style="display:inline-block;padding:2px 10px;border-radius:10px;font-size:11px;font-weight:700;background:${col}22;color:${col};border:1px solid ${col}44">${esc(t.status||"")}</span></td>
        ${turns}
        <td style="font-size:11px;color:#64748b">${esc(t.reason||"")}</td>
      </tr>`;
    }).join("");
    html+=`<div class="section">
      <div class="section-label">② Layer Cascade</div>
      <div class="section-body" style="padding:0;overflow:hidden;border-radius:10px">
        <table class="acts">
          <thead><tr><th>Layer</th><th>Status</th><th>Turns</th><th>Reason</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;
  }

  // path + cost
  const costItems=Object.entries({path,turns,...cost})
    .map(([k,v])=>`<div class="cost-card"><div class="cost-val">${esc(String(v))}</div><div class="cost-lbl">${esc(k)}</div></div>`)
    .join("");
  html+=`<div class="section">
    <div class="section-label">③ Path &amp; Cost</div>
    <div class="section-body">
      <div style="margin-bottom:12px">
        <span class="path-badge" style="background:${pc}">${esc(path)}</span>
      </div>
      <div class="cost-grid">${costItems}</div>
    </div>
  </div>`;

  // actions
  if(actions.length){
    const rows=actions.slice(0,30).map(a=>{
      const t=a.turn||a.turn===0?a.turn:"?";
      const act=String(a.actions||a.action||"?").slice(0,120);
      const out2=String(a.outcome||"").slice(0,80);
      const ok=/ok|success|done|true/i.test(out2);
      const oc=ok?"#4ade80":"#f87171";
      return `<tr><td style="color:#475569;white-space:nowrap">turn ${esc(t)}</td>
        <td>${esc(act)}</td>
        <td style="color:${oc}">${esc(out2)}</td></tr>`;
    }).join("");
    html+=`<div class="section">
      <div class="section-label">④ Browser Actions (${actions.length})</div>
      <div class="section-body" style="padding:0;overflow:hidden;border-radius:10px">
        <table class="acts">
          <thead><tr><th>Turn</th><th>Actions</th><th>Outcome</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;
  }

  // screenshots
  if(shots.length){
    const imgs=shots.map((src,i)=>`
      <figure class="shot-fig" onclick="openLb('${src}')">
        <img src="${src}" alt="shot ${i+1}" loading="lazy">
        <figcaption>screenshot ${i+1}</figcaption>
      </figure>`).join("");
    html+=`<div class="section">
      <div class="section-label">⑤ Screenshots (${shots.length})</div>
      <div class="section-body" style="padding:10px"><div class="shots">${imgs}</div></div>
    </div>`;
  }

  // extracted
  if(content){
    const preview=content.slice(0,1200)+(content.length>1200?"…":"");
    html+=`<div class="section">
      <div class="section-label">⑥ Extracted Data</div>
      <div class="section-body"><div class="extracted">${esc(preview)}</div></div>
    </div>`;
  }

  return html;
}

function renderDistiller(node){
  const out=node.output||{};
  const fields=out.fields||{};
  const keys=Object.keys(fields);
  if(!keys.length) return renderDefault(node);
  const rows=keys.map(k=>{
    const v=fields[k];
    const vstr=Array.isArray(v)||typeof v==="object"
      ? JSON.stringify(v,null,2) : String(v||"");
    return `<dt>${esc(k)}</dt><dd><span class="pre">${esc(vstr)}</span></dd>`;
  }).join("");
  const rat=out.rationale?`<div style="font-size:12px;color:#64748b;margin-top:12px;font-style:italic">${esc(out.rationale)}</div>`:"";
  return `<div class="section">
    <div class="section-label">Extracted Fields</div>
    <div class="section-body fields"><dl>${rows}</dl>${rat}</div>
  </div>`;
}

function renderFormatter(node){
  const out=node.output||{};
  const fa=out.final_answer||out.answer||"";
  if(!fa) return renderDefault(node);
  const tableHtml=mdTableToHtml(fa);
  return `<div class="section">
    <div class="section-label">⑦ Comparison Table</div>
    <div class="section-body">${tableHtml||`<div class="pre">${esc(fa.slice(0,2000))}</div>`}</div>
  </div>`;
}

function renderDefault(node){
  if(!node.output) return '<p style="color:#475569;font-size:13px">No output</p>';
  let s;
  try{ s=JSON.stringify(node.output,null,2); }
  catch(e){ s=String(node.output); }
  return `<div class="section">
    <div class="section-label">Output</div>
    <div class="section-body"><div class="pre">${esc(s.slice(0,3000))}</div></div>
  </div>`;
}

function renderNodeCard(node){
  const sc=SKILL_COLOR[node.skill]||"#64748b";
  let body="";
  if(node.skill==="planner")   body=renderPlanner(node);
  else if(node.skill==="critic")    body=renderCritic(node);
  else if(node.skill==="browser")   body=renderBrowser(node);
  else if(node.skill==="distiller") body=renderDistiller(node);
  else if(node.skill==="formatter") body=renderFormatter(node);
  else body=renderDefault(node);

  const errHtml=node.error
    ?`<div class="section"><div class="err-box">${esc(node.error.slice(0,400))}</div></div>`:"";

  const prov=node.provider?`<span class="provider">${esc(node.provider)}</span>`:"";

  return `
    <div class="card-header">
      ${skillChip(node.skill)}
      <span class="node-id">${esc(node.node_id)}</span>
      ${statusBadge(node.status)}
      <span class="elapsed">${node.elapsed}s</span>
      ${prov}
    </div>
    ${errHtml}
    ${body}
    ${node.prompt?`<button class="prompt-toggle" onclick="togglePrompt()">
      <span id="pt-label">▸ Show prompt</span></button>
      <div id="prompt-drawer">${esc(node.prompt)}</div>`:""}
  `;
}

// ── state ─────────────────────────────────────────────────────────────────────
let cur=0, playing=false, timer=null, speedSec=1;
const nodes=DATA.nodes;
const N=nodes.length;

function goTo(i,animate=true){
  cur=Math.max(0,Math.min(N-1,i));
  const card=document.getElementById("node-card");
  if(animate){
    card.style.animation="none";
    card.offsetHeight; // reflow
    card.style.animation="";
  }
  card.innerHTML=renderNodeCard(nodes[cur]);
  document.getElementById("scrubber").value=cur;
  document.getElementById("pos-label").textContent=`${cur+1} / ${N}`;
  document.getElementById("hdr-counter").textContent=`node ${cur+1} of ${N}`;
  // timeline
  document.querySelectorAll(".tn").forEach((el,i)=>{
    el.classList.toggle("active",i===cur);
    el.classList.toggle("done",i<cur);
  });
  const tl=document.getElementById("timeline");
  const el=tl.children[cur];
  if(el) el.scrollIntoView({inline:"nearest",behavior:"smooth"});
}

function play(){
  if(cur>=N-1) goTo(0,false);
  playing=true;
  document.getElementById("btn-play").textContent="⏸";
  timer=setInterval(()=>{
    if(cur<N-1) goTo(cur+1);
    else{ pause(); }
  }, speedSec*1000);
}
function pause(){
  playing=false;
  document.getElementById("btn-play").textContent="▶";
  clearInterval(timer); timer=null;
}
function togglePlay(){ playing?pause():play(); }

function setSpeed(s){
  speedSec=parseFloat(s);
  document.querySelectorAll(".speed-btn").forEach(b=>{
    b.classList.toggle("active",b.dataset.s===s);
  });
  if(playing){ clearInterval(timer); timer=null; play(); }
}

function togglePrompt(){
  const d=document.getElementById("prompt-drawer");
  const lbl=document.getElementById("pt-label");
  if(!d||!lbl) return;
  const open=d.style.display==="block";
  d.style.display=open?"none":"block";
  lbl.textContent=open?"▸ Show prompt":"▾ Hide prompt";
}

function openLb(src){
  document.getElementById("lb-img").src=src;
  document.getElementById("lb").classList.add("open");
}

// ── init ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded",()=>{
  document.getElementById("q-text").textContent=DATA.session.query;

  // build timeline
  const tl=document.getElementById("timeline");
  nodes.forEach((n,i)=>{
    const c=SKILL_COLOR[n.skill]||"#64748b";
    const d=document.createElement("div");
    d.className="tn";
    d.title=`${n.node_id} · ${n.skill} · ${n.status}`;
    d.style.background=c+"22";
    d.style.borderColor=c+"44";
    d.innerHTML=`<span class="tn-label" style="color:${c}">${n.skill.slice(0,3)}</span><span class="tn-dot"></span>`;
    d.onclick=()=>{ pause(); goTo(i); };
    tl.appendChild(d);
  });

  // scrubber
  const sc=document.getElementById("scrubber");
  sc.max=N-1; sc.value=0;
  sc.oninput=()=>{ pause(); goTo(parseInt(sc.value)); };

  // speed buttons
  document.querySelectorAll(".speed-btn").forEach(b=>{
    b.onclick=()=>setSpeed(b.dataset.s);
  });

  // player buttons
  document.getElementById("btn-play").onclick=togglePlay;
  document.getElementById("btn-prev").onclick=()=>{ pause(); goTo(cur-1); };
  document.getElementById("btn-next").onclick=()=>{ pause(); goTo(cur+1); };
  document.getElementById("btn-first").onclick=()=>{ pause(); goTo(0); };
  document.getElementById("btn-last").onclick=()=>{ pause(); goTo(N-1); };

  // keyboard
  document.addEventListener("keydown",e=>{
    if(e.key==="ArrowRight"||e.key===" "){ e.preventDefault(); pause(); goTo(cur+1); }
    else if(e.key==="ArrowLeft"){ e.preventDefault(); pause(); goTo(cur-1); }
    else if(e.key==="p"||e.key==="P") togglePlay();
    else if(e.key==="Escape"){ pause(); document.getElementById("lb").classList.remove("open"); }
  });

  // lightbox close
  document.getElementById("lb").onclick=()=>document.getElementById("lb").classList.remove("open");

  goTo(0,false);
});
</script>
</body>
</html>
"""


def _build_html(session_id: str, query: str, states: list[NodeState]) -> str:
    nodes_data = [_node_to_dict(st) for st in states]
    session_data = {"id": session_id, "query": query, "total": len(states)}
    payload = {"session": session_data, "nodes": nodes_data}

    # embed as JSON — escape </script> to prevent early close
    raw = json.dumps(payload, ensure_ascii=False)
    raw = raw.replace("</script>", r"<\/script>")

    skill_color_js = json.dumps(SKILL_COLOR)
    path_color_js  = json.dumps(PATH_COLOR)

    return (
        _HTML
        .replace("__SESSION_ID__", session_id)
        .replace("__DATA_JSON__", raw)
        .replace("__SKILL_COLOR__", skill_color_js)
        .replace("__PATH_COLOR__", path_color_js)
    )


def generate(session_id: str) -> Path:
    store = SessionStore(session_id)
    states = store.read_all_nodes()
    if not states:
        print(f"error: no nodes under state/sessions/{session_id}/", file=sys.stderr)
        sys.exit(2)
    query = store.read_query() or ""
    content = _build_html(session_id, query, states)
    out = ROOT / "state" / "sessions" / session_id / "report.html"
    out.write_text(content, encoding="utf-8")
    return out


def main() -> None:
    args = sys.argv[1:]
    if not args:
        sessions = list_sessions()
        if not sessions:
            print("no sessions found under state/sessions/", file=sys.stderr)
            sys.exit(2)
        print("available sessions:")
        for s in sessions:
            print(f"  {s}")
        print("\nusage: uv run python browser_report.py <session_id>")
        return
    out = generate(args[0])
    print(f"report  →  {out}")
    print(f"open it:   open '{out}'")


if __name__ == "__main__":
    main()
