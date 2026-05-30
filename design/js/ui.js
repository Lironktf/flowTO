/* ============================================================
   FlowTO — UI widgets & rendering (vanilla)
   ============================================================ */
window.FlowTO = window.FlowTO || {};

FlowTO.ui = (function () {
  const D = FlowTO.data;
  const $ = s => document.querySelector(s);
  const el = (tag, cls, html) => { const e=document.createElement(tag); if(cls)e.className=cls; if(html!=null)e.innerHTML=html; return e; };
  const fmt = n => n.toLocaleString('en-US');

  const ICONS = {
    closure:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="8.2"/><path d="M6.5 6.5 17.5 17.5"/></svg>',
    lane:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M6 3v18M18 3v6"/><path d="M18 9c0 5-4 5-4 12" stroke-dasharray="2.4 2.4"/></svg>',
    oneway:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 12h13M12 7l6 5-6 5"/></svg>',
    signal:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="8" y="3" width="8" height="18" rx="3"/><circle cx="12" cy="7.5" r="1.3" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none"/><circle cx="12" cy="16.5" r="1.3" fill="currentColor" stroke="none"/></svg>',
    surge:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="2.6"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6 7.7 7.7M16.3 16.3l2.1 2.1M18.4 5.6 16.3 7.7M7.7 16.3l-2.1 2.1"/></svg>',
  };

  let scrubMin = D.timeline.fulltime, playing = false, playTimer = null;
  let sparkVals = Array(20).fill(60);

  /* ---------- build static lists ---------- */
  function buildTools() {
    const g = $('#iv-grid');
    D.tools.forEach(t => {
      const b = el('button','iv-tool');
      b.dataset.tool = t.id;
      b.innerHTML = `<span class="ico">${ICONS[t.id]}</span><span class="nm">${t.name}</span><span class="ds">${t.desc}</span>`;
      b.onclick = () => FlowTO.app.selectTool(t.id);
      g.appendChild(b);
    });
  }
  function setActiveTool(id) {
    document.querySelectorAll('.iv-tool').forEach(b => b.classList.toggle('active', b.dataset.tool===id));
  }

  function buildScenarios() {
    const list = $('#scn-list');
    D.scenarios.forEach(s => {
      const it = el('div','scn-item'+(s.active?' active':''));
      it.dataset.scn = s.id;
      it.innerHTML = `<span class="badge">${s.badge}</span><span class="grow"><div class="nm">${s.name}</div><div class="mt">${s.meta}</div></span>`;
      it.onclick = () => { document.querySelectorAll('.scn-item').forEach(x=>x.classList.remove('active')); it.classList.add('active'); $('#tb-scenario').textContent = s.name; };
      list.appendChild(it);
    });
  }

  /* ---------- scrubber ---------- */
  function buildScrubber() {
    const tl = D.timeline;
    const ticks = $('#scrub-ticks'); ticks.innerHTML='';
    for (let h = tl.startMin; h <= tl.endMin; h += 60) {
      ticks.appendChild(el('span',null, String(Math.floor(h/60)).padStart(2,'0')+':00'));
    }
    // keyframes
    const kfs = $('#scrub-kfs'); kfs.innerHTML='';
    [['kickoff',tl.kickoff,false],['full-time',tl.fulltime,true]].forEach(([nm,m,match])=>{
      const k = el('div','scrub-kf'+(match?' match':''));
      k.style.left = pct(m)+'%'; k.title = nm; kfs.appendChild(k);
    });
    // heat gradient across timeline: calm → red at full-time → easing
    const heat = $('#scrub-heat');
    const stops = [];
    for (let m=tl.startMin; m<=tl.endMin; m+=15) {
      let p; const ft = tl.fulltime;
      if (m < tl.kickoff) p = .28;
      else if (m < ft-20) p = .35 + (m-tl.kickoff)/(ft-20-tl.kickoff)*.15;
      else if (m <= ft+15) p = .5 + (m-(ft-20))/35*.45;
      else p = Math.max(.3, .95 - (m-(ft+15))/(tl.endMin-(ft+15))*.6);
      stops.push(`${FlowTO.map.rampCSS(Math.min(1,p))} ${pct(m)}%`);
    }
    heat.style.background = `linear-gradient(90deg, ${stops.join(',')})`;
    setTime(scrubMin);

    const track = $('#scrub-track');
    const seek = clientX => {
      const r = track.getBoundingClientRect();
      const f = Math.max(0, Math.min(1, (clientX-r.left)/r.width));
      const m = tl.startMin + Math.round(f*(tl.endMin-tl.startMin)/tl.step)*tl.step;
      setTime(m); FlowTO.app.onScrub(m);
    };
    track.onpointerdown = e => { seek(e.clientX);
      const mv = ev => seek(ev.clientX);
      const up = () => { window.removeEventListener('pointermove',mv); window.removeEventListener('pointerup',up); };
      window.addEventListener('pointermove',mv); window.addEventListener('pointerup',up); };
    $('#btn-play').onclick = togglePlay;
  }
  function pct(m){ const tl=D.timeline; return ((m-tl.startMin)/(tl.endMin-tl.startMin))*100; }
  function setTime(m) {
    scrubMin = m;
    $('#scrub-handle').style.left = pct(m)+'%';
    const hh = String(Math.floor(m/60)).padStart(2,'0'), mm = String(m%60).padStart(2,'0');
    $('#scrub-time').textContent = `${hh}:${mm}`;
  }
  function togglePlay(){ playing ? stopPlay() : startPlay(); }
  function startPlay() {
    playing = true; $('#btn-play').classList.add('on');
    $('#btn-play').innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>';
    if (scrubMin >= D.timeline.endMin) setTime(D.timeline.startMin);
    playTimer = setInterval(()=>{
      let m = scrubMin + D.timeline.step;
      if (m > D.timeline.endMin) { stopPlay(); return; }
      setTime(m); FlowTO.app.onScrub(m);
    }, 520);
  }
  function stopPlay() {
    playing = false; clearInterval(playTimer); $('#btn-play').classList.remove('on');
    $('#btn-play').innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
  }

  /* ---------- status ---------- */
  function setStatus(state, text) {
    $('#statuschip').dataset.state = state;
    $('#status-text').textContent = text;
  }

  /* ---------- metrics / before-after ---------- */
  const M = D.metrics, ML = D.metricLabels;
  function deltaPct(cur, base){ return base ? Math.round((cur-base)/base*100) : 0; }
  function deltaTag(cur, base, lowerBetter=true) {
    const dp = deltaPct(cur, base);
    if (dp === 0) return `<span class="delta flat">±0%</span>`;
    const good = lowerBetter ? dp < 0 : dp > 0;
    const arrow = dp < 0 ? '↓' : '↑';
    return `<span class="delta ${good?'good':'bad'}">${arrow} ${Math.abs(dp)}%</span>`;
  }
  function metricsEmpty() {
    $('#metrics-body').innerHTML =
      `<div class="metrics-empty"><div class="big serif">Network nominal</div>
       <div class="sm">Run a scenario or ask the Copilot to model an intervention.<br>Before/after deltas appear here.</div></div>`;
    $('#ba-compare').textContent = 'baseline';
  }
  // mode: 'surge' (baseline→event) | 'mit' (event→mitigated)
  function renderMetrics(mode) {
    const cur = mode==='mit' ? M.mit : M.surge;
    const ref = mode==='mit' ? M.surge : M.base;
    $('#ba-compare').textContent = mode==='mit' ? 'event → mitigated' : 'baseline → event';
    const small = ['mean','p95','congested','infil'].map(k=>{
      return `<div class="metric"><div class="lab"><span>${ML[k]}</span></div>
        <div class="val">${cur[k].v}<span class="u">${cur[k].u}</span></div>
        ${deltaTag(cur[k].v, ref[k].v)}</div>`;
    }).join('');
    const dMax = M.surge.delay.v;
    const bw = v => Math.max(4, Math.min(100, v/dMax*100));
    const body = `
      <div class="metric wide">
        <div class="lab"><span>${ML.delay}</span>${deltaTag(cur.delay.v, ref.delay.v)}</div>
        <div class="val">${fmt(cur.delay.v)}<span class="u">${cur.delay.u}</span></div>
        <div class="barpair">
          <div class="barrow"><span class="bl">${mode==='mit'?'event':'base'}</span>
            <div class="bartrack"><div class="barfill" style="width:${bw(ref.delay.v)}%;background:${mode==='mit'?'var(--c-sev)':'var(--c-light)'}"></div></div>
            <span class="bv">${fmt(ref.delay.v)}</span></div>
          <div class="barrow"><span class="bl">${mode==='mit'?'mitig.':'event'}</span>
            <div class="bartrack"><div class="barfill" style="width:${bw(cur.delay.v)}%;background:${mode==='mit'?'var(--c-mod)':'var(--c-sev)'}"></div></div>
            <span class="bv">${fmt(cur.delay.v)}</span></div>
        </div>
      </div>
      <div class="metrics-grid" style="margin-top:9px">${small}</div>
      ${mode==='mit'
        ? `<div class="warn-row ok"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m5 12 5 5L20 6"/></svg><div class="wt"><b>Plan valid.</b> No hard-constraint conflicts · within event TMP budget · emergency access retained.</div></div>`
        : `<div class="warn-row"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 9v4M12 17h.01M10.3 3.9 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg><div class="wt"><b>34% cut-through</b> into Parkdale &amp; Liberty Village local streets. Unmitigated.</div></div>`}
    `;
    $('#metrics-body').innerHTML = body;
  }

  /* ---------- preview card ---------- */
  function showPreview(title, steps) {
    $('#preview-ttl').textContent = title;
    $('#preview-list').innerHTML = steps.map(s=>`<li>${s}</li>`).join('');
    $('#preview-card').classList.add('show');
  }
  function hidePreview(){ $('#preview-card').classList.remove('show'); }

  /* ---------- copilot ---------- */
  function buildChips() {
    const c = $('#copilot-chips');
    D.copilotChips.forEach(t=>{
      const b = el('button','chip', t.length>42 ? t.slice(0,40)+'…' : t);
      b.title = t; b.onclick = ()=> FlowTO.app.copilotAsk(t);
      c.appendChild(b);
    });
  }
  function logEl(){ return $('#copilot-log'); }
  function scrollLog(){ const l=logEl(); l.scrollTop = l.scrollHeight; }
  function addUser(text) {
    const m = el('div','msg user', `<span class="who">Planner</span><div class="bub">${text}</div>`);
    logEl().appendChild(m); scrollLog();
  }
  function addTyping() {
    const m = el('div','msg bot', `<span class="who">Nemotron</span><div class="bub"><span class="typing"><i></i><i></i><i></i></span></div>`);
    logEl().appendChild(m); scrollLog(); return m;
  }
  function botHTML(script) {
    let h = `<div>${script.botLead}</div><ul style="margin:8px 0 0;padding-left:16px">`;
    h += script.steps.map(s=>`<li style="font-size:12px;line-height:1.5;margin-bottom:3px">${s}</li>`).join('');
    h += `</ul>`;
    if (script.citations && script.citations.length) {
      h += `<div class="cite">`;
      script.citations.forEach(c=> h += `<div><span class="ref">${c.ref}</span> — ${c.note}</div>`);
      h += `</div>`;
    }
    if (script.botTail) h += `<div style="margin-top:9px">${script.botTail}</div>`;
    return h;
  }
  function resolveTyping(node, script) {
    node.querySelector('.bub').innerHTML = botHTML(script);
    scrollLog();
  }

  /* ---------- recompute overlay ---------- */
  function buildRecomputeSteps() {
    $('#rc-steps').innerHTML = D.recomputeSteps.map(s=>`<span class="rc-step"><span class="sd"></span>${s}</span>`).join('');
  }
  function showRecompute(title){ $('#rc-title').textContent = title||'Recomputing assignment…'; $('#recompute').classList.add('show'); buildRecomputeSteps(); }
  function updateRecompute(progress, stepIdx) {
    $('#rc-bar').style.width = progress+'%';
    $('#rc-sub').textContent = Math.round(progress)+'%';
    document.querySelectorAll('.rc-step').forEach((s,i)=>{
      s.classList.toggle('done', i<stepIdx);
      s.classList.toggle('active', i===stepIdx);
    });
  }
  function hideRecompute(){ $('#recompute').classList.remove('show'); }

  /* ---------- perf strip ---------- */
  function setPerf(p) {
    if ('recompute' in p) $('#pf-recompute').innerHTML = `${p.recompute} <span class="pu">ms</span>`;
    if ('subEdges' in p)  $('#pf-sub').innerHTML = `${fmt(p.subEdges)} <span class="pu">/ ${fmt(p.subNodes)} nd</span>`;
    if ('llm' in p)       $('#pf-llm').innerHTML = (p.llm==='—') ? '—' : `${p.llm} <span class="pu">ms</span>`;
    if ('fps' in p) {
      $('#pf-fps').innerHTML = `${p.fps} <span class="pu">fps</span>`;
      sparkVals.push(p.fps); sparkVals.shift(); drawSpark();
    }
  }
  function drawSpark() {
    const s = $('#pf-spark');
    s.innerHTML = sparkVals.map(v=>`<i style="height:${Math.max(2,(v/60)*14)}px"></i>`).join('');
  }

  function init() {
    buildTools(); buildScenarios(); buildScrubber(); buildChips(); buildRecomputeSteps(); drawSpark();
    $('#btn-theme').onclick = ()=> FlowTO.app.toggleTheme();
    $('#btn-reset').onclick = ()=> FlowTO.app.reset();
    $('#btn-recenter').onclick = ()=> FlowTO.map.flyTo({ center:D.center, zoom:14.1, pitch:52, bearing:-18, duration:900 });
    $('#btn-apply').onclick = ()=> FlowTO.app.applyPlan();
    $('#btn-discard').onclick = ()=> FlowTO.app.discardPlan();
    $('#btn-load').onclick = ()=> FlowTO.app.loadTwin();
    $('#copilot-send').onclick = ()=> { const v=$('#copilot-input').value.trim(); if(v){ $('#copilot-input').value=''; FlowTO.app.copilotAsk(v); } };
    $('#copilot-input').onkeydown = e => { if(e.key==='Enter'){ const v=e.target.value.trim(); if(v){ e.target.value=''; FlowTO.app.copilotAsk(v); } } };
  }

  return { init, setActiveTool, setStatus, metricsEmpty, renderMetrics, showPreview, hidePreview,
           addUser, addTyping, resolveTyping, setTime, stopPlay, startPlay,
           showRecompute, updateRecompute, hideRecompute, setPerf,
           get scrubMin(){ return scrubMin; } };
})();
