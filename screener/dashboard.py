"""Static HTML dashboard, styled after the R.W. Mansfield weekly chartbooks
that Weinstein worked from: chart-paper ground, ink lines, stage colours.
Data is embedded as JSON and rendered client-side (tabs, sorting, detail
panels with weekly price/30W-MA chart and MRS pane)."""
from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import datetime, timezone


def render(long_signals, short_signals, sectors_df, watchlist_rows,
           issues: list[str], stats: dict) -> str:
    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "stats": stats,
        "long": [asdict(s) for s in long_signals],
        "short": [asdict(s) for s in short_signals],
        "sectors": sectors_df.to_dict(orient="records") if len(sectors_df) else [],
        "watchlists": watchlist_rows,
        "issues": issues,
    }
    return _TEMPLATE.replace("__DATA__",
                             json.dumps(_sanitize(payload), allow_nan=False))


def _sanitize(o):
    """Recursively replace NaN/Inf with None so JSON stays valid."""
    if isinstance(o, dict):
        return {k: _sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_sanitize(v) for v in o]
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Weinstein Weekly Screener</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --paper:#F5F4EF; --panel:#FDFCF8; --ink:#16181D; --grid:#DCDAD0;
  --muted:#6B6A63; --long:#1F7A4D; --short:#B3362B; --mrs:#2B5D8C;
  --flag:#8A6D1F;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font:14px/1.45 "IBM Plex Mono",monospace;
  background-image:repeating-linear-gradient(0deg,transparent,transparent 27px,rgba(22,24,29,.035) 28px);}
header{padding:26px 28px 14px;border-bottom:2px solid var(--ink)}
h1{font:700 26px/1.1 "Space Grotesk",sans-serif;margin:0;letter-spacing:-.5px}
h1 span{color:var(--muted);font-weight:500}
.meta{color:var(--muted);font-size:12px;margin-top:6px}
nav{display:flex;gap:0;border-bottom:1px solid var(--ink);padding:0 28px;flex-wrap:wrap}
nav button{font:600 13px "IBM Plex Mono",monospace;background:none;border:none;
  border-right:1px solid var(--grid);padding:11px 18px;cursor:pointer;color:var(--muted)}
nav button.active{color:var(--ink);box-shadow:inset 0 -3px 0 var(--ink)}
main{padding:20px 28px 60px;max-width:1280px}
table{border-collapse:collapse;width:100%;background:var(--panel);
  border:1px solid var(--ink)}
th{font:600 11px "IBM Plex Mono",monospace;text-transform:uppercase;
  letter-spacing:.06em;text-align:left;padding:8px 10px;cursor:pointer;
  border-bottom:2px solid var(--ink);white-space:nowrap;user-select:none}
th .arr{color:var(--muted)}
td{padding:7px 10px;border-bottom:1px solid var(--grid);white-space:nowrap}
tr.row{cursor:pointer}
tr.row:hover{background:#EFEEE6}
.tick{font-weight:600}
.pos{color:var(--long)} .neg{color:var(--short)}
.badge{display:inline-block;font-size:10px;padding:1px 6px;border:1px solid;
  border-radius:2px;margin-left:6px;vertical-align:1px}
.badge.fresh{color:var(--long);border-color:var(--long)}
.badge.div{color:var(--short);border-color:var(--short)}
.badge.vol{color:var(--flag);border-color:var(--flag)}
.quad{font-size:11px;padding:1px 6px;border-radius:2px;border:1px solid var(--grid)}
.quad.leader{color:var(--long);border-color:var(--long)}
.quad.avoid{color:var(--short);border-color:var(--short)}
.quad.beta_only,.quad.discounted_strength{color:var(--flag);border-color:var(--flag)}
tr.detail td{background:var(--panel);padding:14px 10px;border-bottom:2px solid var(--ink)}
.chartwrap{display:flex;gap:24px;flex-wrap:wrap}
svg text{font:10px "IBM Plex Mono",monospace;fill:var(--muted)}
.empty{color:var(--muted);padding:30px 0}
.issues{margin-top:34px;font-size:12px;color:var(--muted)}
.issues h3{font:600 12px "IBM Plex Mono";text-transform:uppercase;color:var(--ink)}
.spark{vertical-align:middle}
.note{font-size:12px;color:var(--muted);margin:0 0 14px}
@media(max-width:720px){main,header,nav{padding-left:12px;padding-right:12px}
  td,th{padding:6px 6px;font-size:12px}}
</style>
</head>
<body>
<header>
  <h1>WEINSTEIN WEEKLY <span>/ Mansfield RS Screener</span></h1>
  <div class="meta" id="meta"></div>
</header>
<nav id="tabs"></nav>
<main id="main"></main>
<script>
const D = __DATA__;
const fmt=(v,d=2)=>v==null||Number.isNaN(v)?"–":Number(v).toFixed(d);
const cls=v=>v>0?"pos":v<0?"neg":"";

/* ---------- sparkline / detail charts ---------- */
function spark(vals,color,w=110,h=26){
  const v=vals.filter(x=>x!=null); if(v.length<2)return"";
  const mn=Math.min(...v),mx=Math.max(...v),r=mx-mn||1;
  const pts=vals.map((x,i)=>x==null?null:
    `${(i/(vals.length-1)*w).toFixed(1)},${(h-2-(x-mn)/r*(h-4)).toFixed(1)}`)
    .filter(Boolean).join(" ");
  return `<svg class="spark" width="${w}" height="${h}">
    <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.4"/></svg>`;
}
function mansfieldPanel(s){
  const W=560,H1=180,H2=70,P=8;
  const c=s.spark_close,m=s.spark_sma,r=s.spark_mrs;
  const all=c.concat(m).filter(x=>x!=null);
  const mn=Math.min(...all),mx=Math.max(...all),rg=mx-mn||1;
  const X=i=>P+i/(c.length-1)*(W-2*P);
  const Y1=v=>P+(1-(v-mn)/rg)*(H1-2*P);
  const line=(vals,y,color,wd)=>{
    const pts=vals.map((v,i)=>v==null?null:`${X(i).toFixed(1)},${y(v).toFixed(1)}`)
      .filter(Boolean).join(" ");
    return `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="${wd}"/>`;}
  const rv=r.filter(x=>x!=null);
  const rmn=Math.min(0,...rv),rmx=Math.max(0,...rv),rrg=rmx-rmn||1;
  const Y2=v=>H1+6+((rmx-v)/rrg)*(H2-10);
  let grid="";
  for(let i=0;i<=4;i++){const y=P+i*(H1-2*P)/4;
    grid+=`<line x1="${P}" y1="${y}" x2="${W-P}" y2="${y}" stroke="var(--grid)"/>`;}
  return `<svg width="${W}" height="${H1+H2+12}" style="max-width:100%">
    <rect x="0" y="0" width="${W}" height="${H1}" fill="var(--panel)" stroke="var(--ink)"/>
    ${grid}
    ${line(c,Y1,"var(--ink)",1.5)}
    ${line(m,Y1,s.side==="long"?"var(--long)":"var(--short)",1.5)}
    <text x="${P+2}" y="14">${s.ticker} — weekly close · 30W MA</text>
    <rect x="0" y="${H1+4}" width="${W}" height="${H2+6}" fill="var(--panel)" stroke="var(--ink)"/>
    <line x1="${P}" y1="${Y2(0)}" x2="${W-P}" y2="${Y2(0)}" stroke="var(--muted)" stroke-dasharray="3 3"/>
    ${line(r,Y2,"var(--mrs)",1.4)}
    <text x="${P+2}" y="${H1+16}">Mansfield RS (52W) · zero line</text>
  </svg>`;
}

/* ---------- tables ---------- */
function table(rows,cols,detail){
  if(!rows.length)return `<div class="empty">Keine Treffer diese Woche.</div>`;
  let html=`<table><thead><tr>`+cols.map((c,i)=>
    `<th data-i="${i}">${c.h} <span class="arr"></span></th>`).join("")+`</tr></thead><tbody>`;
  rows.forEach((r,ri)=>{
    html+=`<tr class="row" data-ri="${ri}">`+cols.map(c=>`<td>${c.f(r)}</td>`).join("")+`</tr>`;
    if(detail)html+=`<tr class="detail" data-ri="${ri}" style="display:none">
      <td colspan="${cols.length}"><div class="chartwrap">${detail(r)}</div></td></tr>`;
  });
  return html+`</tbody></table>`;
}
const sigCols=[
  {h:"Ticker",f:r=>`<span class="tick">${r.ticker}</span>`+
    (r.mrs_fresh_cross?`<span class="badge fresh">RS-CROSS</span>`:"")+
    (r.divergence?`<span class="badge div">RS-DIV</span>`:"")+
    (r.vol_bonus?`<span class="badge vol">VOL</span>`:""),k:r=>r.ticker},
  {h:"Name",f:r=>r.name.slice(0,26),k:r=>r.name},
  {h:"Univ.",f:r=>r.universe,k:r=>r.universe},
  {h:"Close",f:r=>fmt(r.close),k:r=>r.close},
  {h:"vs 30W",f:r=>`<span class="${cls(r.close/r.sma30-1)}">${fmt((r.close/r.sma30-1)*100,1)}%</span>`,k:r=>r.close/r.sma30},
  {h:"Slope 6W",f:r=>`<span class="${cls(r.slope6)}">${fmt(r.slope6*100,2)}%</span>`,k:r=>r.slope6},
  {h:"MRS",f:r=>`<span class="${cls(r.mrs)}">${fmt(r.mrs,1)}</span>`,k:r=>r.mrs},
  {h:"Vol ×",f:r=>fmt(r.vol_ratio,2),k:r=>r.vol_ratio},
  {h:"Basis W",f:r=>r.base_weeks,k:r=>r.base_weeks},
  {h:"Sektor-MRS",f:r=>r.sector_mrs==null?"–":`<span class="${cls(r.sector_mrs)}">${fmt(r.sector_mrs,1)}</span>`,k:r=>r.sector_mrs??-99},
  {h:"Score",f:r=>`<b>${fmt(r.score,1)}</b>`,k:r=>r.score},
  {h:"52W",f:r=>spark(r.spark_close,"var(--ink)"),k:r=>0},
];
const secCols=[
  {h:"ETF",f:r=>`<span class="tick">${r.symbol}</span>`,k:r=>r.symbol},
  {h:"Sektor / Thema",f:r=>r.name,k:r=>r.name},
  {h:"MRS vs SPX",f:r=>`<span class="${cls(r.mrs)}">${fmt(r.mrs,1)}</span>`,k:r=>r.mrs},
  {h:"Δ 4W",f:r=>`<span class="${cls(r.mrs_chg_4w)}">${fmt(r.mrs_chg_4w,1)}</span>`,k:r=>r.mrs_chg_4w},
  {h:"MRS 52W",f:r=>spark(r.spark_mrs,"var(--mrs)",170,30),k:r=>0},
];
const wlCols=[
  {h:"Ticker",f:r=>`<span class="tick">${r.ticker}</span>`,k:r=>r.ticker},
  {h:"Liste",f:r=>r.list,k:r=>r.list},
  {h:"Close",f:r=>fmt(r.close),k:r=>r.close},
  {h:"vs 30W",f:r=>`<span class="${cls(r.vs_ma)}">${fmt(r.vs_ma*100,1)}%</span>`,k:r=>r.vs_ma},
  {h:"MRS lokal",f:r=>`<span class="${cls(r.mrs_local)}">${fmt(r.mrs_local,1)}</span>`,k:r=>r.mrs_local},
  {h:"MRS Thema",f:r=>r.mrs_theme==null?"–":`<span class="${cls(r.mrs_theme)}">${fmt(r.mrs_theme,1)}</span>`,k:r=>r.mrs_theme??-99},
  {h:"Quadrant",f:r=>r.quadrant?`<span class="quad ${r.quadrant}">${r.quadrant}</span>`:"–",k:r=>r.quadrant||""},
  {h:"Signal",f:r=>r.signal||"–",k:r=>r.signal||""},
];

/* ---------- app ---------- */
const TABS=[
 {id:"long",label:`LONG · Stage 1→2 (${D.long.length})`,
  render:()=>`<p class="note">Ausbruch auf 26W-Hoch · Kurs &gt; steigender 30W-MA · MRS &gt; 0 · Basis ≥ 13W mit ≥ 2 MA-Crossings · Volumen ≥ 1,5× — sortiert nach Score.</p>`+
   table(D.long,sigCols,r=>mansfieldPanel(r))},
 {id:"short",label:`SHORT · Stage 3→4 (${D.short.length})`,
  render:()=>`<p class="note">Bruch auf 26W-Tief · Kurs &lt; kippendem 30W-MA · MRS &lt; 0 · vorheriger Stage-2-Markup vorhanden · Volumen nur Bonus-Flag.</p>`+
   table(D.short,sigCols,r=>mansfieldPanel(r))},
 {id:"sectors",label:"SEKTOR-ROTATION",
  render:()=>`<p class="note">Mansfield RS aller Sektor-/Themen-ETFs gegen SPX. Δ 4W = Momentum der relativen Stärke — die Wachablösung zeigt sich hier zuerst.</p>`+
   table(D.sectors,secCols,null)},
 {id:"watch",label:"WATCHLISTS",
  render:()=>`<p class="note">Dual-MRS: gegen lokalen Index und gegen Themen-Benchmark. leader = beide positiv · discounted_strength = sektorstark, Länder-Beta drückt.</p>`+
   table(D.watchlists,wlCols,null)},
];
function show(id){
  document.querySelectorAll("nav button").forEach(b=>b.classList.toggle("active",b.dataset.id===id));
  const t=TABS.find(t=>t.id===id);
  const m=document.getElementById("main");
  m.innerHTML=t.render()+issuesBlock();
  m.querySelectorAll("tr.row").forEach(tr=>tr.addEventListener("click",()=>{
    const d=m.querySelector(`tr.detail[data-ri="${tr.dataset.ri}"]`);
    if(d)d.style.display=d.style.display==="none"?"":"none";
  }));
  m.querySelectorAll("th").forEach(th=>th.addEventListener("click",()=>{/* simple resort */
    const tabRows={long:D.long,short:D.short,sectors:D.sectors,watch:D.watchlists}[id];
    const colsets={long:sigCols,short:sigCols,sectors:secCols,watch:wlCols};
    const col=colsets[id][+th.dataset.i];
    const dir=th.dataset.dir==="asc"?"desc":"asc";th.dataset.dir=dir;
    tabRows.sort((a,b)=>{const x=col.k(a),y=col.k(b);
      return (x>y?1:x<y?-1:0)*(dir==="asc"?1:-1);});
    show(id);
  }));
}
function issuesBlock(){
  if(!D.issues.length)return"";
  return `<div class="issues"><h3>Daten-Hinweise (${D.issues.length})</h3>`+
    D.issues.slice(0,40).map(i=>`<div>· ${i}</div>`).join("")+
    (D.issues.length>40?`<div>… ${D.issues.length-40} weitere</div>`:"")+`</div>`;
}
document.getElementById("meta").textContent=
  `Stand ${D.generated} · ${D.stats.tickers} Ticker gescreent · ${D.stats.failed} ohne Daten · Lauf: sonntags 07:00 UTC`;
const nav=document.getElementById("tabs");
TABS.forEach((t,i)=>{const b=document.createElement("button");
  b.textContent=t.label;b.dataset.id=t.id;
  b.addEventListener("click",()=>show(t.id));nav.appendChild(b);});
show("long");
</script>
</body>
</html>
"""
