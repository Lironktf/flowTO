/* ============================================================
   FlowTO v2 — UI: docked regions, two views, NLE timeline
   ============================================================ */
window.FlowTO = window.FlowTO || {};

FlowTO.ui = (function () {
  const D = FlowTO.data;
  const $ = s => document.querySelector(s);
  const $$ = s => Array.from(document.querySelectorAll(s));
  const el = (tag, cls, html) => { const e=document.createElement(tag); if(cls)e.className=cls; if(html!=null)e.innerHTML=html; return e; };
  const fmt = n => n.toLocaleString('en-US');

  const ICONS = {
    select:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="m4 3 7.5 17 2.2-6.8L20.5 11 4 3Z"/></svg>',
    closure:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="8.2"/><path d="M6.5 6.5 17.5 17.5"/></svg>',
    lane:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M6 3v18M18 3v6"/><path d="M18 9c0 5-4 5-4 12" stroke-dasharray="2.4 2.4"/></svg>',
    oneway:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 12h13M12 7l6 5-6 5"/></svg>',
    signal:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="8" y="3" width="8" height="18" rx="3"/><circle cx="12" cy="7.5" r="1.3" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none"/><circle cx="12" cy="16.5" r="1.3" fill="currentColor" stroke="none"/></svg>',
    surge:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="2.6"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6 7.7 7.7M16.3 16.3l2.1 2.1M18.4 5.6 16.3 7.7M7.7 16.3l-2.1 2.1"/></svg>',
    eye:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="2.6"/></svg>',
    eyeoff:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M10.7 6.2A9 9 0 0 1 12 6c6 0 10 6 10 6a16 16 0 0 1-3 3.3M6.6 6.6A16 16 0 0 0 2 12s4 6 10 6a9 9 0 0 0 3.7-.8M3 3l18 18"/></svg>',
    play:'<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
    cam3d:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 8l9-5 9 5-9 5-9-5Z"/><path d="M3 8v8l9 5 9-5V8"/></svg>',
  };
  const TYPE_COLOR = { closure:'var(--c-heavy)', lane:'var(--c-mod)', oneway:'var(--cobalt)', signal:'var(--cobalt)', surge:'var(--c-sev)', transit:'var(--c-free)' };

  let scrubMin = D.timeline.fulltime, playing = false, playTimer = null, speed = 1, planApplied = false;
  let sparkVals = Array(18).fill(60);

  /* ============================ TOOL RAIL (editor) ============================ */
  function buildRail() {
    const rail = $('#rail');
    rail.innerHTML = '';
    const items = [{ id:'select', name:'Select / inspect' }, '|', ...D.tools.map(t=>({ id:t.id, name:t.name }))];
    items.forEach(it => {
      if (it === '|') { rail.appendChild(el('div','rail-sep')); return; }
      const b = el('button','rail-tool'+(it.id==='select'?' active':''));
      b.dataset.tool = it.id;
      b.innerHTML = `${ICONS[it.id]||''}<span class="rail-tip">${it.name}</span>`;
      b.onclick = () => FlowTO.app.selectTool(it.id);
      rail.appendChild(b);
    });
  }

  /* ============================ TOOL LIST (editor left) ============================ */
  function buildTools() {
    const g = $('#tool-list'); g.innerHTML = '';
    D.tools.forEach((t,i) => {
      const b = el('button','tool-row');
      b.dataset.tool = t.id;
      b.innerHTML = `<span class="ti">${ICONS[t.id]}</span>
        <span class="tt"><span class="nm">${t.name}</span><span class="ds">${t.desc}</span></span>
        <span class="kbd">${i+1}</span>`;
      b.onclick = () => FlowTO.app.selectTool(t.id);
      g.appendChild(b);
    });
  }
  function setActiveTool(id) {
    $$('.tool-row').forEach(b => b.classList.toggle('active', b.dataset.tool===id));
    $$('.rail-tool').forEach(b => b.classList.toggle('active', b.dataset.tool===(id||'select')));
  }

  /* ============================ SCENARIOS (sim left) ============================ */
  function buildScenarios() {
    const list = $('#scn-list'); list.innerHTML = '';
    D.scenarios.forEach(s => {
      const it = el('div','scn-item'+(s.active?' active':''));
      it.dataset.scn = s.id;
      it.innerHTML = `<span class="badge">${s.badge}</span><span class="grow"><div class="nm">${s.name}</div><div class="mt">${s.meta}</div></span>`;
      it.onclick = () => { $$('.scn-item').forEach(x=>x.classList.remove('active')); it.classList.add('active'); $('#tb-scenario').textContent = s.name; };
      list.appendChild(it);
    });
    $('#scn-count').textContent = D.scenarios.length + ' saved';
  }

  /* ============================ TIMELINE (sim bottom) ============================ */
  const TL = D.timeline;
  function pct(m){ return ((m-TL.startMin)/(TL.endMin-TL.startMin))*100; }
  function clamp(v,a,b){ return Math.max(a,Math.min(b,v)); }

  function buildTimeline() {
    // ruler
    const ruler = $('#tl-ruler'); ruler.innerHTML = '';
    for (let m=TL.startMin; m<=TL.endMin; m+=15) {
      const major = (m % 60 === 0);
      const t = el('div','tl-tick'+(major?' major':'')); t.style.left = pct(m)+'%';
      if (major) t.innerHTML = `<span class="tlab">${String(Math.floor(m/60)).padStart(2,'0')}:00</span>`;
      ruler.appendChild(t);
    }
    // keyframe diamonds
    const kf = $('#tl-kfrow'); kf.innerHTML = '';
    [['kickoff',TL.kickoff,'filled'],['full-time',TL.fulltime,'event']].forEach(([nm,m,cls])=>{
      const d = el('div','tl-kf '+cls); d.style.left = pct(m)+'%'; d.title = nm;
      d.onclick = ()=> setTime(m, true);
      kf.appendChild(d);
    });
    renderTracks();
    // scrub interactions
    const zone = $('#tl-playzone'), scrub = $('#tl-scrub'), grip = $('#tl-grip');
    const seek = clientX => {
      const r = zone.getBoundingClientRect();
      const f = clamp((clientX-r.left)/r.width, 0, 1);
      const m = TL.startMin + Math.round(f*(TL.endMin-TL.startMin)/TL.step)*TL.step;
      setTime(m, true);
    };
    const startDrag = e => {
      seek(e.clientX);
      const mv = ev => seek(ev.clientX);
      const up = () => { window.removeEventListener('pointermove',mv); window.removeEventListener('pointerup',up); };
      window.addEventListener('pointermove',mv); window.addEventListener('pointerup',up);
    };
    scrub.onpointerdown = startDrag; grip.onpointerdown = startDrag;
    // transport
    $('#tl-play').onclick = togglePlay;
    $('#tl-start').onclick = ()=> setTime(TL.startMin, true);
    $('#tl-end').onclick   = ()=> setTime(TL.endMin, true);
    $('#tl-back').onclick  = ()=> setTime(Math.max(TL.startMin, scrubMin-TL.step), true);
    $('#tl-fwd').onclick   = ()=> setTime(Math.min(TL.endMin, scrubMin+TL.step), true);
    $('#tl-speed').querySelectorAll('button').forEach(b => b.onclick = ()=>{
      speed = parseFloat(b.dataset.spd);
      $('#tl-speed').querySelectorAll('button').forEach(x=>x.classList.toggle('on', x===b));
    });
    $('#tl-dow').textContent = TL.dow;
    setTime(scrubMin);
  }

  function renderTracks() {
    const tr = $('#tl-tracks'); tr.innerHTML = '';
    // 1 — congestion heat
    const heatStops = [];
    for (let m=TL.startMin; m<=TL.endMin; m+=15) {
      let p; const ft = TL.fulltime;
      if (m < TL.kickoff) p = .28;
      else if (m < ft-20) p = .35 + (m-TL.kickoff)/(ft-20-TL.kickoff)*.15;
      else if (m <= ft+15) p = .5 + (m-(ft-20))/35*.45;
      else p = Math.max(.3, .95 - (m-(ft+15))/(TL.endMin-(ft+15))*(planApplied?.78:.55));
      heatStops.push(`${FlowTO.map.rampCSS(Math.min(1,p))} ${pct(m)}%`);
    }
    tr.appendChild(track('Congest', `<div class="trk-fill"><div class="heat" style="background:linear-gradient(90deg,${heatStops.join(',')})"></div></div>`));
    // 2 — demand (match + egress clip)
    let dem = `<div class="trk-clip" style="left:${pct(TL.kickoff)}%;width:${pct(TL.fulltime)-pct(TL.kickoff)}%"><span class="cl">MATCH 90'</span></div>`;
    dem += `<div class="trk-clip evt" style="left:${pct(TL.fulltime)}%;width:${pct(TL.fulltime+25)-pct(TL.fulltime)}%"><span class="cl">EGRESS 45k</span></div>`;
    tr.appendChild(track('Demand', dem));
    // 3 — plan (appears once mitigated)
    let plan = '';
    if (planApplied) {
      plan += `<div class="trk-clip" style="left:${pct(17*60)}%;width:${pct(18*60+30)-pct(17*60)}%"><span class="cl">CONTRAFLOW</span></div>`;
      plan += `<div class="trk-clip transit" style="left:${pct(17*60)}%;width:${pct(18*60)-pct(17*60)}%;top:auto;bottom:3px;height:7px"></div>`;
    } else {
      plan = `<div style="position:absolute;inset:4px 0;border:1px dashed var(--hair);border-radius:4px;display:grid;place-items:center"><span style="font-family:'IBM Plex Mono';font-size:8.5px;color:var(--ink-4)">no plan staged</span></div>`;
    }
    tr.appendChild(track('Plan', plan));
  }
  function track(name, inner) {
    const t = el('div','tl-track');
    t.innerHTML = `<span class="trk-name">${name}</span><div class="trk-lane">${inner}</div>`;
    return t;
  }
  function setTimelinePlan(on){ planApplied = on; renderTracks(); }

  function setTime(m, fire) {
    scrubMin = m;
    $('#tl-playhead').style.left = pct(m)+'%';
    const hh = String(Math.floor(m/60)).padStart(2,'0'), mm = String(m%60).padStart(2,'0');
    $('#tl-time').textContent = `${hh}:${mm}`;
    $('#tl-frame').textContent = 'f ' + (m-TL.startMin);
    // event hint
    const evtTx = m < TL.kickoff ? 'PRE-MATCH · build-up'
      : m < TL.fulltime ? 'MATCH IN PLAY'
      : m <= TL.fulltime+25 ? 'FULL-TIME · egress release'
      : 'POST-EGRESS · recovery';
    $('#tl-event').textContent = evtTx;
    if (fire && FlowTO.app) FlowTO.app.onScrub(m);
  }
  function togglePlay(){ playing ? stopPlay() : startPlay(); }
  function startPlay() {
    playing = true;
    $('#tl-play').innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>';
    if (scrubMin >= TL.endMin) setTime(TL.startMin);
    const tick = ()=>{
      let m = scrubMin + TL.step;
      if (m > TL.endMin) { stopPlay(); return; }
      setTime(m, true);
    };
    playTimer = setInterval(tick, 520/speed);
  }
  function stopPlay() {
    playing = false; clearInterval(playTimer);
    $('#tl-play').innerHTML = ICONS.play;
  }

  /* ============================ STATUS ============================ */
  function setStatus(state, text) { $('#statuschip').dataset.state = state; $('#status-text').textContent = text; }

  /* ============================ METRICS / BEFORE-AFTER ============================ */
  const M = D.metrics, ML = D.metricLabels;
  function deltaPct(c,b){ return b ? Math.round((c-b)/b*100) : 0; }
  function deltaTag(c,b,lower=true) {
    const dp = deltaPct(c,b);
    if (dp === 0) return `<span class="delta flat">±0%</span>`;
    const good = lower ? dp<0 : dp>0, arrow = dp<0?'↓':'↑';
    return `<span class="delta ${good?'good':'bad'}">${arrow} ${Math.abs(dp)}%</span>`;
  }
  function metricsEmpty() {
    $('#metrics-body').innerHTML = `<div class="metrics-empty"><div class="big serif">Network nominal</div>
      <div class="sm">Scrub to full-time or ask the Copilot to model an intervention.<br>Before / after deltas appear here.</div></div>`;
  }
  function renderMetrics(mode) {
    const cur = mode==='mit' ? M.mit : M.surge, ref = mode==='mit' ? M.surge : M.base;
    const small = ['mean','p95','congested','infil'].map(k=>
      `<div class="metric"><div class="lab"><span>${ML[k]}</span></div>
        <div class="val">${cur[k].v}<span class="u">${cur[k].u}</span></div>${deltaTag(cur[k].v, ref[k].v)}</div>`).join('');
    const dMax = M.surge.delay.v, bw = v => Math.max(4, Math.min(100, v/dMax*100));
    $('#metrics-body').innerHTML = `
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
        : `<div class="warn-row"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 9v4M12 17h.01M10.3 3.9 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg><div class="wt"><b>34% cut-through</b> into Parkdale &amp; Liberty Village local streets. Unmitigated.</div></div>`}`;
  }

  /* ============================ INSPECTOR / OUTLINER (editor) ============================ */
  function inspectorEmpty(toolActive) {
    $('#inspector-body').innerHTML = toolActive && toolActive!=='select'
      ? `<div class="insp-empty"><div class="big serif">Placement mode</div><div class="sm">Click the map to drop a <b style="color:var(--cobalt-ink)">${(D.tools.find(t=>t.id===toolActive)||{}).name||''}</b>. It appears here and in the Scene list.</div></div>`
      : `<div class="insp-empty"><div class="big serif">Nothing selected</div><div class="sm">Pick a tool from the rail and click the map, or select an object in the Scene list.</div></div>`;
  }
  const PARAMS = {
    closure: [{k:'Extent',v:'Full segment'},{k:'Modes',v:'All vehicles'}],
    lane:    [{k:'Reduce by',ctl:'range'},{k:'Direction',v:'Both'}],
    oneway:  [{k:'Direction',ctl:'seg',opts:['EB','WB']},{k:'Window',v:'17:00–18:30'}],
    signal:  [{k:'Cycle',ctl:'range',unit:'s'},{k:'Bias',v:'Egress split'}],
    surge:   [{k:'Volume',v:'45,000'},{k:'Release',v:'25 min'}],
  };
  function renderInspector(obj) {
    if (!obj) return;
    const color = TYPE_COLOR[obj.type]||'var(--cobalt)';
    const rows = (PARAMS[obj.type]||[]).map(p=>{
      let ctl;
      if (p.ctl==='range') ctl = `<input class="range-mini" type="range" min="0" max="100" value="${obj.type==='signal'?60:40}">`;
      else if (p.ctl==='seg') ctl = `<div class="seg-mini">${p.opts.map((o,i)=>`<button class="${i===0?'on':''}">${o}</button>`).join('')}</div>`;
      else ctl = `<span class="pv"><span class="mono">${p.v}</span></span>`;
      return `<div class="prop"><span class="pk">${p.k}</span>${ctl}</div>`;
    }).join('');
    $('#inspector-body').innerHTML = `
      <div class="insp-head">
        <span class="ih-ico" style="background:${color}">${ICONS[obj.type]||''}</span>
        <span class="ih-tx"><span class="a">${obj.name}</span><span class="b">${obj.type} · object</span></span>
      </div>
      <div class="prop"><span class="pk">Location</span><span class="pv"><span class="mono">${obj.coord[1].toFixed(4)}, ${obj.coord[0].toFixed(4)}</span></span></div>
      <div class="prop"><span class="pk">Status</span><span class="pv" style="color:var(--c-free)">● Active</span></div>
      ${rows}
      <div class="insp-actions">
        <button class="btn primary btn-sm" id="insp-recompute">Recompute impact</button>
        <button class="btn ghost btn-sm" id="insp-delete">Delete</button>
      </div>`;
    const del = $('#insp-delete'); if (del) del.onclick = ()=> FlowTO.app.deleteObject(obj.id);
    const rc = $('#insp-recompute'); if (rc) rc.onclick = ()=> FlowTO.app.recomputeFromEditor();
  }
  function renderOutliner(objects, selId) {
    const o = $('#outliner');
    $('#out-count').textContent = objects.length + (objects.length===1?' object':' objects');
    if (!objects.length) { o.innerHTML = `<div class="outliner-empty">No interventions yet.<br>Place one from the rail, or apply a Copilot plan.</div>`; return; }
    o.innerHTML = '';
    objects.forEach(obj=>{
      const row = el('div','out-row'+(obj.id===selId?' sel':''));
      row.innerHTML = `<span class="od" style="background:${TYPE_COLOR[obj.type]||'var(--cobalt)'}"></span>
        <span class="on">${obj.name}</span><span class="otype">${obj.type}</span>
        <span class="ovis">${obj.visible===false?ICONS.eyeoff:ICONS.eye}</span>`;
      row.querySelector('.on').onclick = ()=> FlowTO.app.selectObject(obj.id);
      row.querySelector('.od').onclick = ()=> FlowTO.app.selectObject(obj.id);
      row.querySelector('.ovis').onclick = (e)=>{ e.stopPropagation(); FlowTO.app.toggleObjectVis(obj.id); };
      o.appendChild(row);
    });
  }

  /* ============================ PLAN HUD (both views) ============================ */
  function showPreview(title, steps) {
    $('#preview-ttl').textContent = title;
    $('#preview-sub').textContent = `${steps.length} bylaw-valid actions · −38% delay`;
    $('#plan-hud').style.display = 'block';
  }
  function hidePreview(){ $('#plan-hud').style.display = 'none'; }

  /* ============================ COPILOT ============================ */
  function buildChips() {
    const c = $('#copilot-chips'); c.innerHTML='';
    D.copilotChips.forEach(t=>{
      const b = el('button','chip', t.length>40 ? t.slice(0,38)+'…' : t);
      b.title = t; b.onclick = ()=> FlowTO.app.copilotAsk(t);
      c.appendChild(b);
    });
  }
  function logEl(){ return $('#copilot-log'); }
  function scrollLog(){ const l=logEl(); l.scrollTop = l.scrollHeight; }
  function addUser(text){ logEl().appendChild(el('div','msg user', `<span class="who">Planner</span><div class="bub">${text}</div>`)); scrollLog(); }
  function addTyping(){ const m = el('div','msg bot', `<span class="who">Nemotron</span><div class="bub"><span class="typing"><i></i><i></i><i></i></span></div>`); logEl().appendChild(m); scrollLog(); return m; }
  function botHTML(s) {
    let h = `<div>${s.botLead}</div>`;
    if (s.steps && s.steps.length) h += `<ul style="margin:8px 0 0;padding-left:16px">`+s.steps.map(x=>`<li style="font-size:11.5px;line-height:1.5;margin-bottom:3px">${x}</li>`).join('')+`</ul>`;
    if (s.citations && s.citations.length) { h += `<div class="cite">`; s.citations.forEach(c=> h += `<div><span class="ref">${c.ref}</span> — ${c.note}</div>`); h += `</div>`; }
    if (s.botTail) h += `<div style="margin-top:9px">${s.botTail}</div>`;
    return h;
  }
  function resolveTyping(node, s){ node.querySelector('.bub').innerHTML = botHTML(s); scrollLog(); }

  /* ============================ RECOMPUTE OVERLAY ============================ */
  function buildRecomputeSteps(){ $('#rc-steps').innerHTML = D.recomputeSteps.map(s=>`<span class="rc-step"><span class="sd"></span>${s}</span>`).join(''); }
  function showRecompute(title){ $('#rc-title').textContent = title||'Recomputing assignment…'; $('#recompute').classList.add('show'); buildRecomputeSteps(); }
  function updateRecompute(p, idx){
    $('#rc-bar').style.width = p+'%'; $('#rc-sub').textContent = Math.round(p)+'%';
    $$('.rc-step').forEach((s,i)=>{ s.classList.toggle('done', i<idx); s.classList.toggle('active', i===idx); });
  }
  function hideRecompute(){ $('#recompute').classList.remove('show'); }

  /* ============================ STATUS BAR / PERF ============================ */
  function setPerf(p) {
    if ('recompute' in p) $('#sb-recompute').textContent = `${p.recompute} ms`;
    if ('subEdges' in p)  $('#sb-sub').textContent = `${fmt(p.subEdges)} edges`;
    if ('llm' in p)       $('#sb-llm').textContent = (p.llm==='—') ? '—' : `${p.llm} ms`;
    if ('fps' in p) { $('#sb-fps').textContent = p.fps; sparkVals.push(p.fps); sparkVals.shift(); drawSpark(); }
  }
  function drawSpark(){ $('#sb-spark').innerHTML = sparkVals.map(v=>`<i style="height:${Math.max(2,(v/60)*13)}px"></i>`).join(''); }

  /* ============================ REGION COLLAPSE + DOCK TOGGLES ============================ */
  function wireRegions() {
    $$('.region-hd .chev').forEach(ch=>{
      ch.onclick = ()=> ch.closest('.region').classList.toggle('collapsed');
    });
  }
  function setDockToggle(name, on) {
    document.body.classList.toggle('no-'+name, !on);
    const b = document.querySelector(`.dock-toggles [data-dock="${name}"]`);
    if (b) b.classList.toggle('on', on);
    FlowTO.map && FlowTO.map.resize();
  }

  /* ============================ MODE BANNER ============================ */
  function setMode(view) {
    document.body.setAttribute('data-view', view);
    if (view==='edit') {
      $('#mb-ico').innerHTML = ICONS.select;
      $('#mb-title').textContent = 'Editor'; $('#mb-sub').textContent = 'Top-down · place & inspect';
    } else {
      $('#mb-ico').innerHTML = ICONS.play;
      $('#mb-title').textContent = 'Simulation'; $('#mb-sub').textContent = '3-D camera · replay';
    }
    $$('#viewseg button').forEach(b=> b.classList.toggle('on', b.dataset.view===view));
  }

  /* ============================ PLACEMENT GHOST (editor) ============================ */
  let ghostType = null;
  function setGhost(type) {
    ghostType = type;
    const vp = $('#viewport');
    if (type && type!=='select') {
      vp.classList.add('placing');
      $('#place-ghost-ring').innerHTML = ICONS[type] || '';
    } else { vp.classList.remove('placing'); $('#place-ghost').classList.remove('show'); }
  }
  function wireGhost() {
    const vp = $('#viewport'), g = $('#place-ghost');
    vp.addEventListener('pointermove', e=>{
      if (!ghostType || ghostType==='select') return;
      const r = vp.getBoundingClientRect();
      g.style.left = (e.clientX-r.left)+'px'; g.style.top = (e.clientY-r.top)+'px';
      g.classList.add('show');
    });
    vp.addEventListener('pointerleave', ()=> g.classList.remove('show'));
  }

  /* ============================ INIT ============================ */
  function init() {
    buildRail(); buildTools(); buildScenarios(); buildTimeline(); buildChips(); buildRecomputeSteps(); drawSpark(); wireRegions(); wireGhost();
    inspectorEmpty('select');

    // view switch
    $$('#viewseg button').forEach(b=> b.onclick = ()=> FlowTO.app.setView(b.dataset.view));
    // dock toggles
    $$('.dock-toggles [data-dock]').forEach(b=> b.onclick = ()=>{
      const name = b.dataset.dock, on = !b.classList.contains('on');
      setDockToggle(name, on);
    });
    // before/after
    $$('#ba-toggle button').forEach(b=> b.onclick = ()=>{
      $$('#ba-toggle button').forEach(x=>x.classList.toggle('on', x===b));
      FlowTO.app.setCompare(b.dataset.ba);
    });
    // chrome
    $('#btn-theme').onclick = ()=> FlowTO.app.toggleTheme();
    $('#btn-reset').onclick = ()=> FlowTO.app.reset();
    $('#btn-recenter').onclick = ()=> FlowTO.app.recenter();
    $('#btn-tilt').onclick = ()=> FlowTO.app.toggleTilt();
    $('#btn-apply').onclick = ()=> FlowTO.app.applyPlan();
    $('#btn-discard').onclick = ()=> FlowTO.app.discardPlan();
    $('#btn-load').onclick = ()=> FlowTO.app.loadTwin();
    $('#copilot-send').onclick = ()=>{ const v=$('#copilot-input').value.trim(); if(v){ $('#copilot-input').value=''; FlowTO.app.copilotAsk(v); } };
    $('#copilot-input').onkeydown = e => { if(e.key==='Enter'){ const v=e.target.value.trim(); if(v){ e.target.value=''; FlowTO.app.copilotAsk(v); } } };
    // number keys 1–5 select tools (editor)
    window.addEventListener('keydown', e=>{
      if (document.body.getAttribute('data-view')!=='edit') return;
      if (e.target.tagName==='INPUT') return;
      const n = parseInt(e.key,10);
      if (n>=1 && n<=D.tools.length) FlowTO.app.selectTool(D.tools[n-1].id);
      if (e.key==='Escape') FlowTO.app.selectTool('select');
    });
  }

  return { init, setActiveTool, setStatus, metricsEmpty, renderMetrics, showPreview, hidePreview,
           addUser, addTyping, resolveTyping, setTime, stopPlay, startPlay,
           showRecompute, updateRecompute, hideRecompute, setPerf,
           setMode, setDockToggle, setGhost, renderInspector, inspectorEmpty, renderOutliner,
           setTimelinePlan,
           get scrubMin(){ return scrubMin; } };
})();
