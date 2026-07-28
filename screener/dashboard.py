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
           issues: list[str], stats: dict, macro: dict | None = None) -> str:
    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "stats": stats,
        "long": [asdict(s) for s in long_signals],
        "short": [asdict(s) for s in short_signals],
        "sectors": sectors_df.to_dict(orient="records") if len(sectors_df) else [],
        "watchlists": watchlist_rows,
        "issues": issues,
        "macro": macro,
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
.badge.pb{color:var(--mrs);border-color:var(--mrs)}
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
.gauge{background:var(--panel);border:1px solid var(--ink);padding:18px 20px;margin-bottom:18px}
.gauge h2{font:700 34px/1 "Space Grotesk",sans-serif;margin:0 0 2px}
.gauge .lbl{font-size:13px;color:var(--muted);margin-bottom:14px}
.track{position:relative;height:26px;background:linear-gradient(90deg,#F2DEDA,#EFEEE6,#DCEBE2);border:1px solid var(--grid)}
.needle{position:absolute;top:-5px;bottom:-5px;width:3px;background:var(--ink)}
.ends{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-top:5px}
.sd{display:flex;height:24px;border:1px solid var(--ink);margin:6px 0 4px;font-size:10px}
.sd div{display:flex;align-items:center;justify-content:center;color:#fff}
.s1{background:#8A8D93}.s2{background:var(--long)}.s3{background:var(--flag)}.s4{background:var(--short)}
.panel{background:var(--panel);border:1px solid var(--ink);padding:14px 16px;margin-bottom:18px}
.panel h3{font:600 12px "IBM Plex Mono";text-transform:uppercase;letter-spacing:.06em;margin:0 0 10px}
.chk{font-size:12px;line-height:1.9;color:var(--muted)}
.chk b{color:var(--ink)}
.flagset{display:inline-flex;gap:4px;align-items:center}
.fb{cursor:pointer;font-style:normal;font-size:14px;line-height:1;padding:1px 2px;
    color:var(--grid);border-radius:2px}
.fb:hover{color:var(--muted);background:#EFEEE6}
.fb.on{font-weight:700}
.flagcell{cursor:pointer;user-select:none;text-align:center;width:26px;font-size:15px;line-height:1}
.fl-buy{color:var(--long)} .fl-short{color:var(--short)} .fl-skip{color:var(--muted)}
.fl-none{color:var(--grid)}
.filterbar{display:flex;gap:6px;margin:0 0 12px;flex-wrap:wrap;align-items:center}
.filterbar button{font:600 11px "IBM Plex Mono",monospace;background:var(--panel);
  border:1px solid var(--grid);padding:5px 10px;cursor:pointer;color:var(--muted);border-radius:2px}
.filterbar button.on{border-color:var(--ink);color:var(--ink);background:#EFEEE6}
.filterbar .sep{flex:1}
.filterbar .reset{border-style:dashed}
.badge.neu{color:var(--mrs);border-color:var(--mrs);font-weight:600}
tr.reviewed td{opacity:.5}
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
const sortState = {};   // {tabId: {col, dir}} — ueberlebt Re-Renders

/* ---------- Markierungen (Browser-lokal, ueberleben Wochenlaeufe) ------- */
const FLAGS_KEY="weinstein_flags_v1", SKIP_DAYS=56;
function loadFlags(){
  try{
    const raw=JSON.parse(localStorage.getItem(FLAGS_KEY)||"{}"), now=Date.now(), out={};
    for(const [t,v] of Object.entries(raw)){
      if(v.s==="skip" && now-v.t > SKIP_DAYS*864e5) continue;   // × laeuft ab
      out[t]=v;
    }
    return out;
  }catch(e){ return {}; }
}
function saveFlags(){ try{ localStorage.setItem(FLAGS_KEY,JSON.stringify(FLAGS)); }catch(e){} }
let FLAGS=loadFlags();
const FLAG_ICON={buy:"\u2691",short:"\u2691",skip:"\u00D7","":"\u00B7"};
const FLAG_CLS={buy:"fl-buy",short:"fl-short",skip:"fl-skip","":"fl-none"};
function flagOf(t){ return (FLAGS[t]||{}).s || ""; }
function setFlag(t,s){            // gleiches Symbol nochmal = zuruecksetzen
  if(flagOf(t)===s) delete FLAGS[t]; else FLAGS[t]={s:s,t:Date.now()};
  saveFlags();
}
let filterMode="offen";   // alle | neu | offen | buy | short
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
  if(!rows.length)return `<div class="empty">Keine Treffer in dieser Ansicht.</div>`;
  let html=`<table><thead><tr>`+cols.map((c,i)=>
    `<th data-i="${i}">${c.h} <span class="arr"></span></th>`).join("")+`</tr></thead><tbody>`;
  rows.forEach((r,ri)=>{
    const key=r.ticker||("r"+ri), fl=r.ticker?flagOf(r.ticker):"";
    html+=`<tr class="row${fl==="skip"?" reviewed":""}" data-k="${key}">`+
      cols.map(c=>`<td>${c.f(r)}</td>`).join("")+`</tr>`;
    if(detail)html+=`<tr class="detail" data-k="${key}" style="display:none">
      <td colspan="${cols.length}"><div class="chartwrap">${detail(r)}</div></td></tr>`;
  });
  return html+`</tbody></table>`;
}
function applyFilter(rows){
  return rows.filter(r=>{
    const f=flagOf(r.ticker);
    if(filterMode==="alle")   return true;
    if(filterMode==="neu")    return r.is_new && f!=="skip";
    if(filterMode==="offen")  return f==="";
    if(filterMode==="buy")    return f==="buy";
    if(filterMode==="short")  return f==="short";
    return true;
  });
}
function updateCounts(id){
  const rows={stage12:L12,stage2:LPB,baselow:LBL,short:D.short}[id];
  if(!rows)return;
  document.querySelectorAll("[data-cnt]").forEach(el=>{
    const save=filterMode; filterMode=el.dataset.cnt;
    el.textContent=applyFilter(rows).length; filterMode=save;
  });
}
function filterBar(rows,id){
  const n=m=>{const s=filterMode; filterMode=m; const c=applyFilter(rows).length; filterMode=s; return c;};
  const b=(m,l)=>`<button data-fm="${m}" class="${filterMode===m?"on":""}">${l} `+
    `<span class="cnt" data-cnt="${m}">${n(m)}</span></button>`;
  return `<div class="filterbar">${b("offen","offen")}${b("neu","neu")}
    ${b("buy","\u2691 kauf")}${b("short","\u2691 short")}${b("alle","alle")}
    <span class="sep"></span>
    <button class="reset" data-reset="1">Markierungen zurücksetzen</button></div>
    <div class="chk" style="margin:-6px 0 12px">Links pro Zeile:
    <span class="fl-buy">⚑</span> Kauf-Kandidat · <span class="fl-short">⚑</span> Short-Kandidat ·
    <span class="fl-skip">×</span> erledigt. Ein Klick setzt, derselbe Klick nochmal setzt zurück.
    Markierte Zeilen bleiben stehen, bis du den Filter wechselst — „×" verschwindet dann aus
    „offen" und läuft nach 8 Wochen automatisch ab. Markierungen liegen lokal in diesem Browser.</div>`;
}
const sigCols=[
  {h:"",f:r=>{const s=flagOf(r.ticker);
    const ico=(v,ch,t)=>`<i class="fb${s===v?" on "+FLAG_CLS[v]:""}" data-set="${v}" title="${t}">${ch}</i>`;
    return `<span class="flagset" data-tk="${r.ticker}">`+
      ico("buy","\u2691","Kauf-Kandidat")+ico("short","\u2691","Short-Kandidat")+
      ico("skip","\u00D7","erledigt / nicht relevant")+`</span>`;},
   k:r=>flagOf(r.ticker)||"zz"},
  {h:"Ticker",f:r=>`<span class="tick">${r.ticker}</span>`+
    (r.is_new?`<span class="badge neu">NEU</span>`:"")+
    (r.signal_type==="pullback"?`<span class="badge pb">PULLBACK</span>`:"")+
    (r.signal_type==="pre_breakout"?`<span class="badge pb">PRE-BO</span>`:"")+
    (r.signal_type==="base_low"?`<span class="badge vol">BASE-LOW</span>`:"")+
    (r.signal_type==="rally"?`<span class="badge div">RALLY</span>`:"")+
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
  {h:"Wo. Liste",f:r=>r.weeks_on_list??1,k:r=>r.weeks_on_list??1},
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
function macroPanel(){
  const M=D.macro;
  if(!M)return `<div class="empty">Marktlage-Modul lieferte keine Daten — siehe Hinweise unten.</div>`;
  const pos=(M.score+100)/2;
  const compRows=M.components.map(c=>`<tr><td><b>${c.key}</b><div style="color:var(--muted);font-size:11px">${c.detail}</div></td>
    <td>${c.value}</td><td class="${cls(c.score)}">${fmt(c.score,2)}</td>
    <td class="${cls(c.contribution)}">${fmt(c.contribution,1)}</td></tr>`).join("");
  const sd=M.stage_dist.pct;
  const worldRows=M.world.map(r=>`<tr><td><span class="tick">${r.symbol}</span></td><td>${r.name}</td>
    <td>${r.stage_name}</td><td class="${cls(r.vs_ma)}">${fmt(r.vs_ma,1)}%</td>
    <td class="${cls(r.slope)}">${fmt(r.slope,2)}%</td>
    <td class="${cls(r.mrs)}">${r.mrs==null?"–":fmt(r.mrs,1)}</td>
    <td>${spark(r.spark,"var(--ink)",120,26)}</td></tr>`).join("");
  const fmRows=M.four_month.rows.map(r=>`<tr><td><span class="tick">${r.ticker}</span></td>
    <td>${r.stage}</td><td>${r.note}</td><td>${r.weeks_since_high}W</td></tr>`).join("")
    || `<tr><td colspan="4" style="color:var(--muted)">Keine Schwergewichte auffällig.</td></tr>`;
  const pdr=M.price_dividend;
  const pdBlock=pdr?`<div class="panel"><h3>Preis / Dividende (S&amp;P via SPY)</h3>
      <div style="font:700 22px 'Space Grotesk',sans-serif">${fmt(pdr.ratio,1)}
        <span style="font:400 13px 'IBM Plex Mono';color:var(--muted)">
        · Rendite ${fmt(pdr.yield_pct,2)}% · ${fmt(pdr.percentile,0)}. Perzentil der eigenen Historie</span></div>
      ${spark(pdr.spark,"var(--mrs)",320,40)}
      <div class="chk" style="margin-top:8px">Weinsteins absolute Schwellen (&lt;15 billig, &gt;26 teuer) stammen aus der Zeit vor Aktienrückkäufen. Seit den 1990ern liegt das Verhältnis dauerhaft über 26 — die Kennzahl zeigt seither permanent „teuer" und hat als Timing-Signal praktisch keinen Wert mehr. Nur das Perzentil gegen die eigene Historie ist noch lesbar. <b>Fließt bewusst nicht in den Score ein.</b></div>
    </div>`:`<div class="panel"><h3>Preis / Dividende</h3><div class="chk">Keine Dividendendaten abrufbar.</div></div>`;

  const hist=(M.history||[]).map(h=>h.score);
  const histBlock=hist.length>2?`<div class="panel"><h3>Score-Verlauf · ${hist.length} Läufe</h3>
      ${spark(hist,"var(--ink)",420,60)}
      <div class="chk">Erster Wert ${fmt(hist[0],0)} · aktuell ${fmt(hist[hist.length-1],0)}. Eine Einzelmessung sagt wenig — die Richtung über Wochen ist die eigentliche Information.</div></div>`
    :`<div class="panel"><h3>Score-Verlauf</h3><div class="chk">Noch ${hist.length||0} Datenpunkt(e). Der Verlauf baut sich mit jedem Lauf auf und wird ab etwa fünf Wochen lesbar.</div></div>`;
  return `<div class="gauge">
      <h2 class="${cls(M.score)}">${M.score>0?"+":""}${fmt(M.score,0)}</h2>
      <div class="lbl">${M.label} · gewichteter Verbund aus ${M.components.length} Komponenten · Breite über ${M.breadth_universe} US-Titel · Perzentile gegen ${M.hist_weeks||0} Wochen eigene Historie</div>
      <div class="track"><div class="needle" style="left:${pos}%"></div></div>
      <div class="ends"><span>−100 · näher am Top</span><span>0 · Zyklusmitte</span><span>+100 · näher am Boden</span></div>
    </div>
    <p class="note"><b>Lesart:</b> Dieser Tab ist mean-revertierend (Zyklusposition), der Rest des Screeners trendfolgend (Einstiege). Sie werden sich widersprechen — das ist beabsichtigt. Weinstein nutzte den Makro-Blick zur <b>Steuerung der Gesamtexponierung</b>, nicht für einzelne Entries.</p>
    ${histBlock}
    <div class="panel"><h3>Komponenten</h3>
      <table><thead><tr><th>Indikator</th><th>Wert</th><th>Score</th><th>Beitrag</th></tr></thead>
      <tbody>${compRows}</tbody></table></div>
    <div class="panel"><h3>Stage-Verteilung des US-Universums</h3>
      <div class="sd">
        <div class="s1" style="width:${sd[1]}%">${sd[1]>6?"S1 "+sd[1]+"%":""}</div>
        <div class="s2" style="width:${sd[2]}%">${sd[2]>6?"S2 "+sd[2]+"%":""}</div>
        <div class="s3" style="width:${sd[3]}%">${sd[3]>6?"S3 "+sd[3]+"%":""}</div>
        <div class="s4" style="width:${sd[4]}%">${sd[4]>6?"S4 "+sd[4]+"%":""}</div>
      </div>
      <div class="chk">S1 Basis · S2 Aufwärts · S3 Topping · S4 Abwärts${M.eu_breadth!=null?` &nbsp;|&nbsp; Europa: ${fmt(M.eu_breadth,0)}% über dem eigenen 30W-MA`:""}</div></div>
    <div class="panel"><h3>Marktbreite · 2 Jahre</h3>
      <div class="chartwrap">
        <div><div class="chk">S&amp;P 500</div>${spark(M.spark_spx,"var(--ink)",260,54)}</div>
        <div><div class="chk">A/D-Linie (kumuliert)</div>${spark(M.spark_ad,"var(--mrs)",260,54)}</div>
        <div><div class="chk">High-Low-Differential %</div>${spark(M.spark_hl,"var(--flag)",260,54)}</div>
        <div><div class="chk">% über 30W-MA</div>${spark(M.spark_above,"var(--long)",260,54)}</div>
      </div>
      <div class="chk" style="margin-top:8px">Divergenz-Prüfung: neues Index-Hoch ohne neues A/D-Hoch = Top-Warnung. Am Boden dreht die A/D-Linie laut Weinstein <b>nicht</b> früher — dort ist ihr Fehlen kein Signal.</div></div>
    <div class="panel"><h3>Weltmärkte — laufen den USA oft voraus</h3>
      <table><thead><tr><th>Index</th><th>Name</th><th>Stage</th><th>vs 30W</th><th>Slope</th><th>MRS vs SPX</th><th>52W</th></tr></thead>
      <tbody>${worldRows}</tbody></table></div>
    <div class="panel"><h3>4-Monats-Regel · Top-50 nach Liquidität</h3>
      <table><thead><tr><th>Ticker</th><th>Stage</th><th>Befund</th><th>seit Hoch</th></tr></thead>
      <tbody>${fmRows}</tbody></table>
      <div class="chk" style="margin-top:8px">Kein neues Hoch seit 4 Monaten im Aufwärtstrend (bzw. kein neues Tief im Abwärtstrend) = Trendwende wahrscheinlich. „Groß" ist hier über das Median-Dollarvolumen angenähert, nicht über Marktkapitalisierung.</div></div>
    ${pdBlock}
    <div class="panel"><h3>Medien-Kontraindikation — manuell</h3>
      <div class="chk">Nicht automatisierbar, ohne Objektivität vorzutäuschen. Weinstein liest sie mit dem Kopf; diese Fragen einmal pro Monat selbst beantworten:<br>
      · <b>Titelseiten:</b> Erscheint der Markt in Publikumsmedien (nicht Fachpresse) auf Titelseiten? Euphorisch oder apokalyptisch?<br>
      · <b>Neue Erklärungen:</b> Wird ein dauerhaft neues Regime behauptet („diesmal ist es anders", „Zyklus ist tot")?<br>
      · <b>Umfeld:</b> Reden Menschen ohne Marktbezug ungefragt über Aktien — oder sagen sie, Aktien seien Zockerei?<br>
      · <b>Deine eigene Reaktion:</b> Fühlt sich Kaufen mühelos an oder unmöglich? Das ist der ehrlichste Indikator.</div></div>`;
}

const L12=D.long.filter(r=>r.signal_type==="breakout"||r.signal_type==="pre_breakout");
const LPB=D.long.filter(r=>r.signal_type==="pullback");
const LBL=D.long.filter(r=>r.signal_type==="base_low");
const nNew=a=>a.filter(r=>r.is_new).length;
const lbl=(t,a)=>`${t} (${a.length}${nNew(a)?" · "+nNew(a)+" neu":""})`;
const TABS=[
 {id:"macro",label:`MARKTLAGE${D.macro?" · "+(D.macro.score>0?"+":"")+Math.round(D.macro.score):""}`,
  render:()=>macroPanel()},
 {id:"stage12",label:lbl("LONG · Stage 1→2",L12),
  render:()=>`<p class="note"><b>Breakout</b>: Ausbruch auf 26W-Hoch aus valider Basis, max. 20% über Basis-Top, Volumen ≥ 1,5× in einer der letzten 4 Wochen. <b>PRE-BO</b>: noch in der Basis, ≤ 5% unter dem Range-Hoch, MA flach, RS positiv oder klar verbessernd — Kandidaten vor dem Pivot.</p>`+
   filterBar(L12,"stage12")+table(applyFilter(L12),sigCols,r=>mansfieldPanel(r))},
 {id:"stage2",label:lbl("LONG · Stage-2-Pullback",LPB),
  render:()=>`<p class="note">Stage 2 bestätigt: Retest ≤ 8% über steigendem 30W-MA nach frischem 26W-Hoch. VOL-Flag = Volumen trocknet im Rücksetzer aus (gesund). Stop-Logik: Wochenschluss unter dem 30W-MA.</p>`+
   filterBar(LPB,"stage2")+table(applyFilter(LPB),sigCols,r=>mansfieldPanel(r))},
 {id:"baselow",label:lbl("BASIS-TIEF",LBL),
  render:()=>`<p class="note">Akkumulations-Range-Einstieg: gereifte Basis, Kurs im unteren Drittel der 26W-Range, Tief ≥ 8 Wochen alt, <b>MRS über 8 Wochen steigend</b> (Akkumulations-Beweis). Stop-Logik: unter dem Range-Tief. Kein Weinstein-Signal — Location-Edge mit RS-Filter.</p>`+
   filterBar(LBL,"baselow")+table(applyFilter(LBL),sigCols,r=>mansfieldPanel(r))},
 {id:"short",label:lbl("SHORT · Stage 3→4",D.short),
  render:()=>`<p class="note"><b>Breakdown</b>: frischer Bruch auf 26W-Tief, max. 40% unter dem 52W-Hoch (keine Wasserfall-Fortsetzung), Kurs &lt; kippendem 30W-MA, vorheriger Stage-2-Markup. <b>RALLY</b>: etablierter Abwärtstrend, Kurs ≤ 8% unter fallendem 30W-MA nach Erholung vom Tief — die Weinstein-Short-Zone. Beide: MRS &lt; 0.</p>`+
   filterBar(D.short,"short")+table(applyFilter(D.short),sigCols,r=>mansfieldPanel(r))},
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
  m.querySelectorAll("[data-set]").forEach(el=>el.addEventListener("click",ev=>{
    ev.stopPropagation();
    const cell=el.closest("[data-tk]"), tk=cell.dataset.tk;
    setFlag(tk, el.dataset.set);
    const s=flagOf(tk);
    // gezielt diese Zelle aktualisieren — kein Re-Render, Zeile bleibt sichtbar
    cell.querySelectorAll(".fb").forEach(fb=>{
      fb.className = "fb" + (fb.dataset.set===s ? " on "+FLAG_CLS[s] : "");
    });
    const tr=el.closest("tr"); if(tr)tr.classList.toggle("reviewed", s==="skip");
    updateCounts(id);
  }));
  m.querySelectorAll("[data-fm]").forEach(el=>el.addEventListener("click",()=>{
    filterMode=el.dataset.fm; show(id);
  }));
  const rs=m.querySelector("[data-reset]");
  if(rs)rs.addEventListener("click",()=>{
    if(confirm("Alle Markierungen in diesem Browser löschen?")){
      FLAGS={}; saveFlags(); show(id);
    }
  });
  m.querySelectorAll("tr.row").forEach(tr=>tr.addEventListener("click",ev=>{
    if(ev.target.closest("[data-flag]"))return;
    const d=m.querySelector(`tr.detail[data-k="${tr.dataset.k}"]`);
    if(d)d.style.display=d.style.display==="none"?"":"none";
  }));
  // Sortierpfeile aus persistentem Zustand wiederherstellen
  m.querySelectorAll("th").forEach(th=>{
    const st=sortState[id];
    if(st&&st.col===+th.dataset.i)
      th.querySelector(".arr").textContent=st.dir==="asc"?"\u25B2":"\u25BC";
  });
  m.querySelectorAll("th").forEach(th=>th.addEventListener("click",()=>{
    const tabRows={stage12:L12,stage2:LPB,baselow:LBL,short:D.short,sectors:D.sectors,watch:D.watchlists}[id];
    const colsets={stage12:sigCols,stage2:sigCols,baselow:sigCols,short:sigCols,sectors:secCols,watch:wlCols};
    if(!tabRows||!colsets[id])return;
    const i=+th.dataset.i, col=colsets[id][i];
    if(!col||!col.k)return;
    const prev=sortState[id];
    const dir=(prev&&prev.col===i&&prev.dir==="desc")?"asc":"desc";
    sortState[id]={col:i,dir};
    const val=r=>{const v=col.k(r);
      return (v==null||(typeof v==="number"&&Number.isNaN(v)))?-Infinity:v;};
    tabRows.sort((a,b)=>{const x=val(a),y=val(b);
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
show("macro");
</script>
</body>
</html>
"""
