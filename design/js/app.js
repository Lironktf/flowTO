/* ============================================================
   FlowTO — app orchestration / state machine
   ============================================================ */
window.FlowTO = window.FlowTO || {};

FlowTO.app = (function () {
  const D = FlowTO.data, ui = () => FlowTO.ui, map = () => FlowTO.map;

  let theme = 'light';
  let state = 'base';            // base | surge | mit | blocked
  let recomputing = false;
  let eventFired = false;
  let loaded = false;

  /* ---------- boot (first-run) ---------- */
  function bootSequence() {
    const line = document.getElementById('fr-loadline');
    const lines = [
      '› booting FlowTO runtime…',
      '› loading Toronto network · 1,284 edges · 612 nodes',
      '› warming Nemotron-on-device · GB10…',
      '› ready &nbsp;▸&nbsp; <b>press “Load the twin”</b>',
    ];
    let i = 0;
    (function next(){
      if (i >= lines.length) return;
      line.innerHTML = lines[i]; i++;
      setTimeout(next, i===1?420:760);
    })();
  }

  /* ---------- load ---------- */
  function loadTwin() {
    if (loaded) return; loaded = true;
    const fr = document.getElementById('firstrun');
    fr.classList.add('hide');
    setTimeout(()=> fr.style.display='none', 650);
    map().init({ theme, onReady: enterBaseline });
    startIdlePerf();
  }

  function enterBaseline() {
    state = 'base'; eventFired = false;
    map().setState('base'); map().setHighlight(false); map().showActions(false);
    ui().metricsEmpty();
    ui().setStatus('nominal', 'Baseline · nominal');
    ui().setActiveTool(null);
    ui().setPerf({ recompute: 12, subEdges: 0, subNodes: 0, llm: '—', fps: 60 });
    if (FlowTO._tweaks) applyTweaks(FlowTO._tweaks);
  }

  /* ---------- recompute engine (the hero loop) ---------- */
  function runRecompute(title, dur, onDone) {
    if (recomputing) return;
    recomputing = true;
    ui().setStatus('recomputing', 'Recomputing…');
    ui().showRecompute(title);
    const steps = D.recomputeSteps.length;
    const live = D.perf.live;
    const t0 = performance.now();
    let llmShown = false;
    const iv = setInterval(()=>{
      const e = performance.now() - t0;
      const prog = Math.min(100, e/dur*100);
      const stepIdx = Math.min(steps-1, Math.floor(prog/100*steps));
      ui().updateRecompute(prog, stepIdx);
      ui().setPerf({
        recompute: Math.round(live.recompute*(prog/100) + Math.random()*7),
        subEdges:  Math.round(live.subEdges*Math.min(1, prog/82)),
        subNodes:  Math.round(live.subNodes*Math.min(1, prog/82)),
        fps: 57 + Math.round(Math.random()*3),
      });
      if (stepIdx >= 3 && !llmShown) { llmShown = true; ui().setPerf({ llm: live.llm + Math.round(Math.random()*26-13) }); }
      if (prog >= 100) { clearInterval(iv); finish(); }
    }, 60);
    function finish(){
      ui().updateRecompute(100, steps);
      setTimeout(()=>{
        ui().hideRecompute();
        ui().setPerf({ recompute: live.recompute, subEdges: live.subEdges, subNodes: live.subNodes, llm: live.llm, fps: 60 });
        recomputing = false;
        onDone && onDone();
      }, 280);
    }
  }

  /* ---------- scenario states ---------- */
  function triggerSurge(thenPreview) {
    if (state === 'surge' || state === 'mit') { if (thenPreview) showPlan(); return; }
    eventFired = true;
    map().flyTo({ center:[-79.413,43.638], zoom:14.3, pitch:55, bearing:-18, duration:1100 });
    runRecompute('Assigning event demand · 45,000 egress…', 1700, ()=>{
      state = 'surge';
      map().setState('surge'); map().setHighlight(true); map().showActions(false);
      ui().renderMetrics('surge');
      ui().setStatus('surge', 'Post-match surge · gridlock');
      if (thenPreview) setTimeout(showPlan, 250);
    });
  }

  function showPlan() {
    ui().showPreview('Recommended plan · RL optimizer', D.copilotHero.steps);
  }

  function applyPlan() {
    if (state !== 'surge') { if (state==='base'){ triggerSurge(true); return; } }
    ui().hidePreview();
    runRecompute('Validating bylaws · reassigning network…', 1850, ()=>{
      state = 'mit';
      map().setState('mit'); map().setHighlight(true); map().showActions(true);
      ui().renderMetrics('mit');
      ui().setStatus('nominal', 'Mitigated · plan applied');
      copilotBot({ botLead:"Applied. Network reassigned with the contraflow + retiming plan.", steps:[], citations:[],
        botTail:"Total delay <b>−38%</b> vs unmitigated, local infiltration down to <b>10%</b>. Six actions staged on the map." });
    });
  }
  function discardPlan(){ ui().hidePreview(); }

  function blockedAction(script) {
    state = 'blocked-overlay'; // transient label; underlying network unchanged
    ui().setStatus('blocked', 'Action blocked · bylaw conflict');
    // keep current network; surface the conflict on metrics if event modelled
    setTimeout(()=> ui().setStatus(eventFired ? 'surge':'nominal', eventFired?'Post-match surge · gridlock':'Baseline · nominal'), 3200);
  }

  /* ---------- tool palette ---------- */
  function selectTool(id) {
    ui().setActiveTool(id);
    if (id === 'surge') { triggerSurge(false); return; }
    // any mitigation tool proposes the validated plan (modelling the event first if needed)
    if (state === 'base') triggerSurge(true);
    else showPlan();
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
      setTimeout(()=>{ ui().resolveTyping(node, D.copilotBlocked); blockedAction(D.copilotBlocked); }, 1250);
      return;
    }
    // hero / general → plan, modelling the event first
    if (state === 'base') triggerSurge(false);
    const node = ui().addTyping();
    setTimeout(()=>{
      ui().resolveTyping(node, D.copilotHero);
      setTimeout(showPlan, 400);
    }, 1500);
  }

  /* ---------- scrubber ---------- */
  function onScrub(min) {
    if (min >= D.timeline.fulltime && !eventFired && !recomputing) {
      triggerSurge(false);
    }
  }

  /* ---------- theme + tweaks ---------- */
  function toggleTheme() {
    theme = theme === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', theme);
    map().setTheme(theme);
    if (FlowTO._tweakSetter) FlowTO._tweakSetter('theme', theme);
  }
  function applyTweaks(t) {
    if (t.theme && t.theme !== theme) {
      theme = t.theme;
      document.documentElement.setAttribute('data-theme', theme);
      if (loaded) map().setTheme(theme);
    }
    if (t.density) document.documentElement.setAttribute('data-density', t.density);
    if (typeof t.intensity === 'number') map().setIntensity(t.intensity);
    if (typeof t.extrude === 'number' && loaded) map().setExtrude(t.extrude);
    if (typeof t.tilt === 'number' && loaded) map().setTilt(t.tilt);
  }

  function reset() {
    enterBaseline();
    ui().hidePreview();
    ui().stopPlay();
    ui().setTime(D.timeline.fulltime);
    map().flyTo({ center:D.center, zoom:14.1, pitch:52, bearing:-18, duration:900 });
  }

  /* ---------- idle telemetry ---------- */
  function startIdlePerf() {
    setInterval(()=>{
      if (recomputing) return;
      const j = 59 + (Math.random()<.35?1:0) - (Math.random()<.12?1:0);
      ui().setPerf({ fps: j });
    }, 1100);
  }

  /* ---------- boot on DOM ready ---------- */
  function boot() {
    ui().init();
    bootSequence();
  }

  return { boot, loadTwin, enterBaseline, selectTool, applyPlan, discardPlan,
           copilotAsk, onScrub, toggleTheme, applyTweaks, reset,
           get state(){ return state; } };
})();

document.addEventListener('DOMContentLoaded', () => FlowTO.app.boot());
