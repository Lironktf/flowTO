/* ============================================================
   FlowTO — map engine (MapLibre GL basemap + 3-D extruded
   buildings; corridor network drawn on an own 2-D canvas)
   ============================================================ */
window.FlowTO = window.FlowTO || {};

FlowTO.map = (function () {
  const D = FlowTO.data;
  const STYLES = {
    light: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
    dark:  'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
  };

  let map = null, overlay = null;
  let theme = 'light';
  let state = 'base';          // base | surge | mit
  let intensity = 1.0;         // congestion color intensity tweak
  let extrudeMult = 1.0;       // building height tweak
  let highlightOn = false;     // blast-radius halo
  let actionsOn = false;       // action markers visible
  let stadiumMarker = null;
  let actionMarkers = [];
  let onReady = null;

  // ---- congestion color ramp (the ONLY semantic color) ----
  const STOPS = [
    [0.00, [31,157,87]],   // free  green
    [0.35, [138,175,31]],  // light
    [0.55, [224,162,26]],  // moderate amber
    [0.75, [224,112,27]],  // heavy orange
    [1.00, [210,58,50]],   // severe red
  ];
  function lerp(a,b,t){ return a+(b-a)*t; }
  function rampRGB(pRaw) {
    // intensity expands/contracts contrast around the midpoint
    let p = (pRaw - 0.5) * intensity + 0.5;
    p = Math.max(0, Math.min(1, p));
    let lo = STOPS[0], hi = STOPS[STOPS.length-1];
    for (let i=0;i<STOPS.length-1;i++){
      if (p >= STOPS[i][0] && p <= STOPS[i+1][0]) { lo = STOPS[i]; hi = STOPS[i+1]; break; }
    }
    const span = (hi[0]-lo[0]) || 1;
    const t = (p - lo[0]) / span;
    let c = [ Math.round(lerp(lo[1][0],hi[1][0],t)),
              Math.round(lerp(lo[1][1],hi[1][1],t)),
              Math.round(lerp(lo[1][2],hi[1][2],t)) ];
    if (theme === 'dark') c = c.map(v => Math.min(255, Math.round(v*1.18 + 18)));
    return c;
  }
  // exposed for legend/scrubber
  function rampCSS(p){ const c = rampRGB(p); return `rgb(${c[0]},${c[1]},${c[2]})`; }

  const PXW = { expressway:6, arterial:4.6, collector:3.2, local:2.4, transit:3 };
  function pressureOf(d){ return d[state]; }

  // ---- corridor renderer: own 2D canvas over the map (full control, no lazy redraw) ----
  let cctx = null, ccanvas = null;
  function ensureCanvas() {
    if (ccanvas || !map) return;
    ccanvas = document.createElement('canvas');
    ccanvas.id = 'flowto-corridors';
    ccanvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none';
    map.getContainer().appendChild(ccanvas);
    cctx = ccanvas.getContext('2d');
    resizeCanvas();
    map.on('move', drawCorridors);
    map.on('render', drawCorridors);
    map.on('resize', () => { resizeCanvas(); drawCorridors(); });
  }
  function resizeCanvas() {
    if (!ccanvas) return;
    const r = map.getContainer().getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    ccanvas.width = Math.round(r.width*dpr); ccanvas.height = Math.round(r.height*dpr);
    ccanvas.style.width = r.width+'px'; ccanvas.style.height = r.height+'px';
    cctx.setTransform(dpr,0,0,dpr,0,0);
  }
  function zoomScale(){ return Math.max(0.55, Math.min(2.3, (map.getZoom()-11)/3.1)); }
  function pxWidth(c){ return (PXW[c.cls]||3) * zoomScale(); }
  function strokePath(path, color, w) {
    cctx.beginPath();
    for (let i=0;i<path.length;i++){ const p = map.project(path[i]); if (i===0) cctx.moveTo(p.x,p.y); else cctx.lineTo(p.x,p.y); }
    cctx.strokeStyle = color; cctx.lineWidth = w; cctx.stroke();
  }
  function drawCorridors() {
    if (!cctx || !map) return;
    const r = map.getContainer().getBoundingClientRect();
    cctx.clearRect(0,0,r.width,r.height);
    cctx.lineCap = 'round'; cctx.lineJoin = 'round';
    try {
      // blast-radius halo
      if (highlightOn) {
        cctx.save();
        D.corridors.filter(c => D.blastRadius.includes(c.id)).forEach(c =>
          strokePath(c.path, theme==='dark' ? 'rgba(111,155,255,.34)' : 'rgba(36,85,214,.26)', pxWidth(c)+10));
        cctx.restore();
      }
      // corridor pressure
      D.corridors.forEach(c => strokePath(c.path, rampCSS(pressureOf(c)), pxWidth(c)));
      // transit dashes
      cctx.save(); cctx.setLineDash([4,4]);
      D.corridors.filter(c => c.transit).forEach(c =>
        strokePath(c.path, theme==='dark' ? 'rgba(233,236,241,.55)' : 'rgba(27,26,22,.5)', 2));
      cctx.restore();
    } catch (e) { /* projection not ready */ }
  }
  function refresh(){ drawCorridors(); }

  // ---- markers ----
  function makeStadium() {
    if (!map || stadiumMarker) return;
    const el = document.createElement('div');
    el.innerHTML = `<div style="display:flex;align-items:center;gap:7px;background:var(--surface);
      border:1px solid var(--cobalt-line);border-radius:8px;padding:5px 9px;box-shadow:var(--shadow);
      font-family:'IBM Plex Mono',monospace;font-size:10.5px;color:var(--ink);white-space:nowrap;transform:translateY(-6px)">
      <span style="width:9px;height:9px;border-radius:2px;background:var(--cobalt);display:inline-block"></span>
      <b style="font-family:'Public Sans';font-weight:600">${D.stadium.name}</b>
      <span style="color:var(--ink-3)">${D.stadium.sub}</span></div>
      <div style="width:1px;height:14px;background:var(--cobalt-line);margin:0 auto"></div>
      <div style="width:9px;height:9px;border-radius:50%;background:var(--cobalt);margin:-4px auto 0;box-shadow:0 0 0 4px var(--cobalt-wash)"></div>`;
    el.style.cursor = 'default';
    stadiumMarker = new maplibregl.Marker({ element: el, anchor:'bottom' })
      .setLngLat(D.stadium.coord).addTo(map);
  }

  const TYPE_DOT = { oneway:'var(--cobalt)', signal:'var(--cobalt)', closure:'var(--c-heavy)',
                     transit:'var(--c-free)', surge:'var(--c-sev)' };
  function showActions(on) {
    actionsOn = on;
    actionMarkers.forEach(m => m.remove()); actionMarkers = [];
    if (!on || !map) return;
    let n = 0;
    D.actions.forEach((a,i) => {
      if (a.type === 'surge') return; // stadium already marked
      n++;
      const el = document.createElement('div');
      el.className = 'map-action';
      el.innerHTML = `<div style="display:flex;align-items:center;gap:7px;background:var(--surface);
        border:1px solid var(--cobalt-line);border-radius:7px;padding:4px 8px 4px 4px;box-shadow:var(--shadow);
        font-family:'IBM Plex Mono',monospace;font-size:9.5px;color:var(--ink-2);white-space:nowrap;animation:fadeUp .4s ${i*0.06}s both">
        <span style="display:grid;place-items:center;width:16px;height:16px;border-radius:50%;background:var(--cobalt);color:#fff;font-weight:700;font-size:9px;flex:none">${n}</span>
        <span style="width:7px;height:7px;border-radius:50%;background:${TYPE_DOT[a.type]};flex:none"></span>
        <b style="font-family:'Public Sans';font-weight:600;color:var(--ink)">${a.name}</b>
        <span style="color:var(--ink-3)">${a.sub}</span></div>`;
      const m = new maplibregl.Marker({ element: el, anchor:'left' })
        .setLngLat(a.coord).addTo(map);
      actionMarkers.push(m);
    });
  }

  // ---- building extrusion ----
  function addBuildings() {
    try {
      const style = map.getStyle();
      let srcKey = null;
      for (const k in style.sources) { if (style.sources[k].type === 'vector') { srcKey = k; break; } }
      if (!srcKey) return;
      let beforeId;
      for (const l of style.layers) { if (l.type === 'symbol') { beforeId = l.id; break; } }
      if (map.getLayer('flowto-buildings')) map.removeLayer('flowto-buildings');
      map.addLayer({
        id:'flowto-buildings', type:'fill-extrusion', source: srcKey, 'source-layer':'building',
        paint:{
          'fill-extrusion-color': theme==='dark' ? '#1c2533' : '#ddd6c6',
          'fill-extrusion-height': ['*', ['coalesce', ['get','render_height'], 12], extrudeMult],
          'fill-extrusion-base':   ['coalesce', ['get','render_min_height'], 0],
          'fill-extrusion-opacity': theme==='dark' ? 0.82 : 0.72,
        },
      }, beforeId);
    } catch (e) { /* tiles without building layer — fine */ }
  }

  function retintBasemap(){
    try {
      const style = map.getStyle();
      for (const l of style.layers) {
        const id = l.id.toLowerCase();
        if (id.includes('water') && l.type === 'fill') {
          map.setPaintProperty(l.id, 'fill-color', theme==='dark' ? '#0c1422' : '#dde6ee');
        }
        if ((id === 'background') && l.type === 'background') {
          map.setPaintProperty(l.id, 'background-color', theme==='dark' ? '#0b0e13' : '#efeadd');
        }
      }
    } catch(e){}
  }

  // ---- public ----
  let readyFired = false, setupDone = false;
  function setup() {
    if (setupDone || !map) return; setupDone = true;
    try { retintBasemap(); } catch(e){}
    try { addBuildings(); } catch(e){}
    ensureCanvas();
    try { makeStadium(); } catch(e){}
    refresh();
  }
  function init(opts) {
    theme = opts.theme || 'light';
    onReady = opts.onReady;
    if (!window.maplibregl) { console.warn('maplibre missing'); return; }
    document.body.classList.add('map-pending');
    map = new maplibregl.Map({
      container: 'map',
      style: STYLES[theme],
      center: D.center, zoom: 14.1, pitch: 52, bearing: -18,
      attributionControl: false, antialias: true,
    });
    const fireReady = () => { if (readyFired) return; readyFired = true; if (onReady) onReady(); };
    // set up deck + buildings as soon as the STYLE is parsed (does not wait for all tiles)
    map.on('style.load', () => { setup(); fireReady(); });
    map.on('load', () => { document.body.classList.remove('map-pending'); setup(); fireReady(); });
    map.on('idle', () => document.body.classList.remove('map-pending'));
    map.on('error', () => {}); // swallow tile errors; UI stays usable
    // network fallback: bring the workspace up even if the basemap is slow/blocked
    setTimeout(fireReady, 1600);
    return map;
  }

  function setState(s){ state = s; refresh(); }
  function setTheme(t) {
    if (t === theme || !map) return;
    theme = t;
    map.setStyle(STYLES[t]);
    map.once('styledata', () => { retintBasemap(); addBuildings(); refresh(); });
  }
  function setIntensity(v){ intensity = v; refresh(); }
  function setExtrude(mult){ extrudeMult = mult; if (map && map.getLayer('flowto-buildings'))
    map.setPaintProperty('flowto-buildings','fill-extrusion-height',
      ['*', ['coalesce',['get','render_height'],12], mult]); }
  function setTilt(p){ if (map) map.easeTo({ pitch: p, duration: 400 }); }
  function setHighlight(on){ highlightOn = on; refresh(); }
  function flyTo(o){ if (map) map.flyTo(o); }

  return { init, setState, setTheme, setIntensity, setExtrude, setTilt, setHighlight,
           showActions, refresh, flyTo, rampCSS, get pressureState(){ return state; } };
})();

/* fade-up keyframe for markers (injected once) */
(function(){ const s=document.createElement('style');
  s.textContent='@keyframes fadeUp{from{opacity:0;transform:translateX(-6px)}to{opacity:1;transform:translateX(0)}}';
  document.head.appendChild(s); })();
