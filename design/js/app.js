/* ============================================================
   FlowTO v2 — app orchestration / state machine
   Two views (sim · edit), scene objects, recompute engine.
   ============================================================ */
window.FlowTO = window.FlowTO || {};

FlowTO.app = (function () {
  const D = FlowTO.data, ui = () => FlowTO.ui, map = () => FlowTO.map;

  let theme = 'light';
  let view = 'sim';              // sim | edit
  let modelled = 'base';         // base | surge | mit  (network state of record)
  let compare = 'after';         // before | after (sim before/after toggle)
  let recomputing = false, eventFired = false, loaded = false;
  let activeTool = 'select';
  let objects = [], selectedId = null, objSeq = 0;

  /* ---------- boot ---------- */
  function bootSequence() {
    const line = document.getElementById('fr-loadline');
    const lines = [
      '› booting FlowTO runtime…',
      '› loading Toronto network · 1,284 edges · 612 nodes',
      '› warming Nemotron-on-device · GB10…',
      '› ready &nbsp;▸&nbsp; <b>press "Load the twin"</b>',
    ];
    let i = 0;
    (function next(){ if (i>=lines.length) return; line.innerHTML = lines[i]; i++; setTimeout(next, i===1?420:760); })();
  }

  function loadTwin() {
    if (loaded) return; loaded = true;
    const fr = document.getElementById('firstrun');
    fr.classList.add('hide'); setTimeout(()=> fr.style.display='none', 620);
    map().init({ theme, onReady: enterBaseline });
    startIdlePerf();
  }

  function enterBaseline() {
    modelled = 'base'; eventFired = false; compare = 'after';
    map().setState('base'); map().setHighlight(false); map().showActions(false);
    map().setView(view);
    ui().metricsEmpty();
    ui().setStatus('nominal', 'Baseline · nominal');
    ui().setMode(view);
    syncViewDocks();
    ui().setPerf({ recompute: 12, subEdges: 0, llm: '—', fps: 60 });
    if (FlowTO._tweaks) applyTweaks(FlowTO._tweaks);
  }

  /* ---------- view switching ---------- */
  function setView(v) {
    if (v === view) return;
    view = v;
    ui().setMode(v);
    if (loaded) map().setView(v);
    syncViewDocks();
    // leaving edit clears placement
    if (v === 'sim') { activeTool = 'select'; ui().setGhost(null); ui().setActiveTool('select'); }
    setTimeout(()=> map().resize(), 280);
  }
  // bottom dock = timeline (sim only by default); rail = tools (edit only)
  function syncViewDocks() {
    if (view === 'sim') {
      ui().setDockToggle('bottom', true);
      ui().setDockToggle('rail', false);
    } else {
      ui().setDockToggle('bottom', false);
      ui().setDockToggle('rail', true);
      refreshEditorPanels();
    }
  }
  function refreshEditorPanels() {
    ui().renderOutliner(objects, selectedId);
    const sel = objects.find(o=>o.id===selectedId);
    if (sel) ui().renderInspector(sel); else ui().inspectorEmpty(activeTool);
  }

  /* ---------- recompute engine ---------- */
  function runRecompute(title, dur, onDone) {
    if (recomputing) return; recomputing = true;
    ui().setStatus('recomputing', 'Recomputing…');
    ui().showRecompute(title);
    const steps = D.recomputeSteps.length, live = D.perf.live, t0 = performance.now();
    let llmShown = false;
    const iv = setInterval(()=>{
      const e = performance.now()-t0, prog = Math.min(100, e/dur*100);
      const stepIdx = Math.min(steps-1, Math.floor(prog/100*steps));
      ui().updateRecompute(prog, stepIdx);
      ui().setPerf({
        recompute: Math.round(live.recompute*(prog/100)+Math.random()*7),
        subEdges:  Math.round(live.subEdges*Math.min(1, prog/82)),
        fps: 57 + Math.round(Math.random()*3),
      });
      if (stepIdx>=3 && !llmShown){ llmShown=true; ui().setPerf({ llm: live.llm + Math.round(Math.random()*26-13) }); }
      if (prog>=100){ clearInterval(iv); finish(); }
    }, 60);
    function finish(){
      ui().updateRecompute(100, steps);
      setTimeout(()=>{
        ui().hideRecompute();
        ui().setPerf({ recompute: live.recompute, subEdges: live.subEdges, llm: live.llm, fps: 60 });
        recomputing = false; onDone && onDone();
      }, 280);
    }
  }

  /* ---------- scenario states ---------- */
  function triggerSurge(thenPreview) {
    if (modelled==='surge' || modelled==='mit') { if (thenPreview) showPlan(); return; }
    eventFired = true;
    map().flyTo({ center:[-79.413,43.638], zoom:14.3, pitch: view==='edit'?0:55, bearing: view==='edit'?0:-18, duration:1100 });
    runRecompute('Assigning event demand · 45,000 egress…', 1700, ()=>{
      modelled = 'surge'; compare = 'after';
      map().setState('surge'); map().setHighlight(true);
      ui().renderMetrics('surge');
      ui().setStatus('surge', 'Post-match surge · gridlock');
      if (thenPreview) setTimeout(showPlan, 250);
    });
  }
  function showPlan(){ ui().showPreview('Recommended plan · RL optimizer', D.copilotHero.steps); }

  function applyPlan() {
    if (modelled === 'base') { triggerSurge(true); return; }
    ui().hidePreview();
    runRecompute('Validating bylaws · reassigning network…', 1850, ()=>{
      modelled = 'mit'; compare = 'after';
      map().setState('mit'); map().setHighlight(true); map().showActions(true);
      ui().renderMetrics('mit');
      ui().setStatus('nominal', 'Mitigated · plan applied');
      ui().setTimelinePlan(true);
      // materialise the staged actions as scene objects
      ingestPlanObjects();
      copilotBot({ botLead:"Applied. Network reassigned with the contraflow + retiming plan.", steps:[], citations:[],
        botTail:"Total delay <b>−38%</b> vs unmitigated, local infiltration down to <b>10%</b>. Six actions staged on the map." });
    });
  }
  function discardPlan(){ ui().hidePreview(); }

  function ingestPlanObjects() {
    D.actions.forEach(a=>{
      if (a.type==='surge') return;
      if (objects.some(o=>o.planId===a.id)) return;
      addObject({ type:a.type, name:a.name, sub:a.sub, coord:a.coord.slice(), planId:a.id });
    });
    if (view==='edit') refreshEditorPanels();
  }

  /* ---------- scene objects (editor) ---------- */
  function addObject(o) {
    const id = 'obj'+(++objSeq);
    const n = objects.filter(x=>x.visible!==false).length+1;
    const obj = Object.assign({ id, visible:true, n }, o);
    objects.push(obj);
    map().addPin({ id, type:obj.type, coord:obj.coord, n, name:obj.name, sub:obj.sub });
    return obj;
  }
  function placeAt(coord) {
    if (activeTool==='select' || !activeTool) return;
    const tool = D.tools.find(t=>t.id===activeTool);
    const near = nearestCorridor(coord);
    const obj = addObject({ type:activeTool, name: tool.name + (near?' · '+near:''), sub:'manual', coord });
    selectObject(obj.id);
    refreshEditorPanels();
    ui().setStatus('recomputing', 'Object placed · recompute pending');
    // small targeted recompute
    runRecompute('Reassigning affected subgraph…', 950, ()=>{
      if (activeTool==='surge' && modelled==='base') { triggerSurge(false); return; }
      ui().setStatus(modelled==='surge'?'surge':'nominal', modelled==='surge'?'Post-match surge · gridlock':'Edited · recomputed');
    });
  }
  function nearestCorridor(coord) {
    let best=null, bd=Infinity;
    D.corridors.forEach(c=> c.path.forEach(p=>{
      const d=(p[0]-coord[0])**2+(p[1]-coord[1])**2; if(d<bd){bd=d;best=c;}
    }));
    return best && bd < 2e-5 ? best.name : null;
  }
  function selectObject(id) {
    selectedId = id; activeTool = 'select';
    ui().setActiveTool('select'); ui().setGhost(null);
    map().selectPin(id);
    const o = objects.find(x=>x.id===id);
    ui().renderInspector(o); ui().renderOutliner(objects, selectedId);
  }
  function deleteObject(id) {
    objects = objects.filter(o=>o.id!==id);
    map().removePin(id);
    if (selectedId===id) selectedId=null;
    refreshEditorPanels();
  }
  function toggleObjectVis(id) {
    const o = objects.find(x=>x.id===id); if(!o) return;
    o.visible = o.visible===false;
    if (o.visible) map().addPin({ id:o.id, type:o.type, coord:o.coord, n:o.n, name:o.name, sub:o.sub });
    else map().removePin(o.id);
    refreshEditorPanels();
  }
  function recomputeFromEditor() {
    runRecompute('Reassigning network · validating bylaws…', 1500, ()=>{
      ui().setStatus('nominal', 'Edited · recomputed');
    });
  }

  /* ---------- tool palette ---------- */
  function selectTool(id) {
    activeTool = id;
    ui().setActiveTool(id);
    if (id==='select') { ui().setGhost(null); selectedId=null; ui().inspectorEmpty('select'); return; }
    // arm placement
    ui().setGhost(id);
    selectedId = null;
    ui().inspectorEmpty(id);
    map().setClickHandler((coord)=> placeAt(coord));
  }

  /* ---------- copilot ---------- */
  function copilotBot(script, delay) {
    const node = ui().addTyping();
    setTimeout(()=> ui().resolveTyping(node, script), delay||1100);
    return node;
  }
  function copilotAsk(text) {
    ui().addUser(text);
    const blocked = /close.*lake\s*shore.*(both|two)|both\s*ways/i.test(text);
    if (blocked) {
      const node = ui().addTyping();
      setTimeout(()=>{ ui().resolveTyping(node, D.copilotBlocked); ui().setStatus('blocked','Action blocked · bylaw conflict');
        setTimeout(()=> ui().setStatus(eventFired?'surge':'nominal', eventFired?'Post-match surge · gridlock':'Baseline · nominal'), 3200); }, 1250);
      return;
    }
    if (modelled==='base') triggerSurge(false);
    const node = ui().addTyping();
    setTimeout(()=>{ ui().resolveTyping(node, D.copilotHero); setTimeout(showPlan, 400); }, 1500);
  }

  /* ---------- scrubber ---------- */
  function onScrub(min) {
    if (min >= D.timeline.fulltime && !eventFired && !recomputing) triggerSurge(false);
  }

  /* ---------- before / after (sim) ---------- */
  function setCompare(which) {
    compare = which;
    if (modelled==='base') { map().setState('base'); return; }
    if (modelled==='surge') map().setState(which==='before' ? 'base' : 'surge');
    else if (modelled==='mit') map().setState(which==='before' ? 'surge' : 'mit');
  }

  /* ---------- camera ---------- */
  function recenter(){ map().flyTo({ center:D.center, zoom:14.1, pitch: view==='edit'?0:52, bearing: view==='edit'?0:-18, duration:900 }); }
  let tilted = true;
  function toggleTilt(){
    tilted = !tilted;
    map().flyTo({ pitch: tilted?52:0, bearing: tilted?-18:0, duration:700 });
  }

  /* ---------- theme + tweaks ---------- */
  function toggleTheme() {
    theme = theme==='light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', theme);
    map().setTheme(theme);
    if (FlowTO._tweakSetter) FlowTO._tweakSetter('theme', theme);
  }
  function applyTweaks(t) {
    if (t.theme && t.theme!==theme) { theme=t.theme; document.documentElement.setAttribute('data-theme', theme); if (loaded) map().setTheme(theme); }
    if (t.density) document.documentElement.setAttribute('data-density', t.density);
    if (typeof t.intensity==='number') map().setIntensity(t.intensity);
    if (typeof t.extrude==='number' && loaded) map().setExtrude(t.extrude);
    if (typeof t.tilt==='number' && loaded && view==='sim') map().setTilt(t.tilt);
  }

  function reset() {
    objects.forEach(o=> map().removePin(o.id)); objects=[]; selectedId=null; objSeq=0;
    ui().setTimelinePlan(false);
    enterBaseline();
    ui().hidePreview(); ui().stopPlay();
    ui().setTime(D.timeline.fulltime);
    recenter();
  }

  function startIdlePerf() {
    setInterval(()=>{ if (recomputing) return; const j=59+(Math.random()<.35?1:0)-(Math.random()<.12?1:0); ui().setPerf({ fps:j }); }, 1100);
  }

  function boot(){ ui().init(); ui().setMode('sim'); bootSequence(); }

  return { boot, loadTwin, enterBaseline, setView, selectTool, applyPlan, discardPlan,
           copilotAsk, onScrub, setCompare, recenter, toggleTilt, toggleTheme, applyTweaks, reset,
           placeAt, selectObject, deleteObject, toggleObjectVis, recomputeFromEditor,
           get state(){ return modelled; }, get view(){ return view; } };
})();

document.addEventListener('DOMContentLoaded', () => FlowTO.app.boot());
