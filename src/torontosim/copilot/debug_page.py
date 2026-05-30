"""Self-contained copilot debug console (P09).

Served at ``GET /copilot/debug`` — a single HTML page (no build step) to exercise
the copilot in isolation: pick a mode (Plan / Chat-stream / Agent), send a
prompt, and see the full picture — tool call, interventions, citations, RAG
hits, the agent's per-step reasoning, raw JSON, and latency. For fleshing out
and debugging the copilot without the full deck.gl app.
"""

from __future__ import annotations

DEBUG_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Copilot Debug · Nemotron</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; background:#0d1117; color:#d7dde5; font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; }
  header { padding:14px 18px; border-bottom:1px solid #222a35; display:flex; gap:14px; align-items:center; flex-wrap:wrap; }
  header h1 { font-size:15px; margin:0; font-weight:600; color:#7ee787; }
  header .dim { color:#6b7686; font-size:12px; }
  main { padding:18px; max-width:980px; margin:0 auto; }
  textarea { width:100%; min-height:64px; background:#161b22; color:#d7dde5; border:1px solid #2b3440;
             border-radius:8px; padding:10px 12px; font:inherit; resize:vertical; }
  .controls { display:flex; gap:14px; align-items:center; margin:10px 0 4px; flex-wrap:wrap; }
  label.mode { cursor:pointer; padding:4px 10px; border:1px solid #2b3440; border-radius:999px; }
  label.mode:has(input:checked) { background:#1f6feb33; border-color:#1f6feb; color:#9ecbff; }
  label.mode input { display:none; }
  button { background:#238636; color:#fff; border:0; border-radius:8px; padding:8px 16px; font:inherit; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
  #lat { margin-left:auto; color:#e3b341; font-variant-numeric:tabular-nums; }
  .examples { margin:8px 0 0; display:flex; gap:8px; flex-wrap:wrap; }
  .ex { font-size:12px; color:#9ecbff; background:#161b22; border:1px solid #2b3440; border-radius:999px;
        padding:3px 10px; cursor:pointer; }
  .card { background:#11161d; border:1px solid #222a35; border-radius:10px; margin:12px 0; overflow:hidden; }
  .ct { background:#161b22; padding:6px 12px; font-size:11px; letter-spacing:.08em; text-transform:uppercase;
        color:#8b98a8; border-bottom:1px solid #222a35; }
  .card > div:not(.ct), .card > pre { padding:10px 12px; }
  pre { margin:0; white-space:pre-wrap; word-break:break-word; color:#c9d3df; font-size:12.5px; }
  .step { border-bottom:1px solid #1c232d; padding:8px 12px; }
  .step:last-child { border-bottom:0; }
  .step b { color:#79c0ff; }
  .th { color:#adbac7; margin:3px 0 4px; font-style:italic; }
  .step pre { color:#6e7d8f; font-size:11.5px; }
  .blocked { color:#ff7b72; }
  .cite b { color:#d2a8ff; }
  .dim { color:#6b7686; }
</style></head>
<body>
<header>
  <h1>● Copilot Debug</h1>
  <span class="dim" id="health">checking backend…</span>
  <span id="lat"></span>
</header>
<main>
  <textarea id="prompt" placeholder="Ask the copilot…  (Cmd/Ctrl+Enter to send)"></textarea>
  <div class="controls">
    <label class="mode"><input type="radio" name="mode" value="plan" checked> Plan</label>
    <label class="mode"><input type="radio" name="mode" value="stream"> Chat (stream)</label>
    <label class="mode"><input type="radio" name="mode" value="agent"> Agent</label>
    <button id="send">Send</button>
  </div>
  <div class="examples">
    <span class="ex">Just close Lake Shore both ways.</span>
    <span class="ex">Ease post-match gridlock near BMO Field without breaking bylaws.</span>
    <span class="ex">Reduce capacity on Lake Shore Boulevard eastbound to meter inflow.</span>
    <span class="ex">Why does closing Lake Shore hurt post-match egress?</span>
    <span class="ex">hi</span>
  </div>
  <div id="out"></div>
</main>
<script>
const $ = s => document.querySelector(s);
const out = $('#out'), lat = $('#lat');
const esc = s => (s+'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const mode = () => document.querySelector('input[name=mode]:checked').value;
const card = (t, b) => `<div class="card"><div class="ct">${esc(t)}</div>${b}</div>`;
const cleanIv = i => { const o={}; for (const k in i) if (i[k]!=null) o[k]=i[k]; return o; };

fetch('/healthz').then(r=>r.json()).then(d=>{$('#health').textContent=`backend ok · ${d.edges} edges`;})
  .catch(()=>{$('#health').textContent='backend DOWN';});

document.querySelectorAll('.ex').forEach(e => e.onclick = () => { $('#prompt').value = e.textContent; send(); });

async function send() {
  const p = $('#prompt').value.trim(); if (!p) return;
  out.innerHTML = ''; lat.textContent = '…'; $('#send').disabled = true;
  const t0 = performance.now(), m = mode();
  try {
    if (m === 'stream') {
      out.innerHTML = card('answer (streaming)', '<div id="stream"></div>');
      const sd = $('#stream'); let first;
      const r = await fetch('/copilot/stream', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({prompt:p})});
      const rd = r.body.getReader(), dec = new TextDecoder(); let buf='';
      for (;;) { const {value, done} = await rd.read(); if (done) break;
        buf += dec.decode(value, {stream:true}); let nl;
        while ((nl = buf.indexOf('\n\n')) >= 0) {
          const line = buf.slice(0, nl).split('\n').find(l => l.startsWith('data: ')); buf = buf.slice(nl+2);
          if (!line) continue; const e = JSON.parse(line.slice(6));
          if (e.token) { if (first===undefined) first = Math.round(performance.now()-t0); sd.textContent += e.token; }
          if (e.done) lat.textContent = `first ${e.first_token_ms ?? first}ms · total ${e.total_ms ?? Math.round(performance.now()-t0)}ms · rag ${e.backend||'?'}`;
          if (e.error) sd.innerHTML += `<span class="blocked"> [error: ${esc(e.error)}]</span>`;
        }
      }
      return;
    }
    const ep = m === 'agent' ? '/copilot/agent' : '/copilot/plan';
    const r = await fetch(ep, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({prompt:p})});
    const d = await r.json(); lat.textContent = `${Math.round(performance.now()-t0)}ms · ${m}`;
    let html = '';
    if (m === 'agent') {
      html += card('answer', `<div>${esc(d.answer||'')}</div>`);
      if (d.steps && d.steps.length)
        html += card('reasoning trace', d.steps.map((s,i) =>
          `<div class="step"><b>${i+1}. ${esc(s.tool)}</b>${s.thought?`<div class="th">${esc(s.thought)}</div>`:''}<pre>${esc(JSON.stringify(s.observation)).slice(0,600)}</pre></div>`).join(''));
    } else {
      html += card('tool', `<div class="${d.blocked?'blocked':''}">${esc(d.tool)}${d.blocked?' · BLOCKED':''}</div>`);
      if (d.rationale) html += card('rationale', `<div>${esc(d.rationale)}</div>`);
    }
    if (d.interventions && d.interventions.length)
      html += card(`interventions (${d.interventions.length})`, '<pre>'+esc(JSON.stringify(d.interventions.map(cleanIv), null, 2))+'</pre>');
    if (d.citations && d.citations.length)
      html += card('citations', '<div class="cite">'+d.citations.map(c=>`<div>• <b>${esc(c.ref)}</b> — ${esc(c.note)}</div>`).join('')+'</div>');
    if (d.retrieved_policy && d.retrieved_policy.length)
      html += card('RAG retrieved', d.retrieved_policy.map(h=>`<div>${esc(h.title)} <span class="dim">(${h.score??''})</span></div>`).join(''));
    html += card('raw json', '<pre>'+esc(JSON.stringify(d, null, 2))+'</pre>');
    out.innerHTML = html;
  } catch (e) {
    out.innerHTML = card('error', `<div class="blocked">${esc(e.message||e)}</div>`); lat.textContent = 'error';
  } finally { $('#send').disabled = false; }
}
$('#send').onclick = send;
$('#prompt').addEventListener('keydown', e => { if (e.key==='Enter' && (e.metaKey||e.ctrlKey)) send(); });
</script>
</body></html>
"""
