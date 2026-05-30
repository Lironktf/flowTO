/* ============================================================
   FlowTO — domain data (no lorem; real Toronto geography & copy)
   Corridors around Exhibition Place / Toronto Stadium (BMO Field).
   ============================================================ */
window.FlowTO = window.FlowTO || {};

FlowTO.data = (function () {
  // pressure: 0 (free flow) .. 1 (gridlock), per network state
  // states: base = nominal weekday eve · surge = post-match, unmitigated · mit = after recommended plan
  const corridors = [
    // ---- Expressway / arterials (egress spine) ----
    { id:'G1',  name:'Gardiner Expressway',     cls:'expressway', lanes:6, base:.58, surge:.92, mit:.64,
      path:[[-79.4450,43.6398],[-79.4320,43.6382],[-79.4180,43.6388],[-79.4040,43.6398],[-79.3920,43.6408]] },
    { id:'L1',  name:'Lake Shore Blvd W',       cls:'arterial', lanes:4, base:.40, surge:.97, mit:.55,
      path:[[-79.4430,43.6362],[-79.4300,43.6353],[-79.4170,43.6359],[-79.4040,43.6366],[-79.3920,43.6373]] },
    { id:'D1',  name:'Dufferin St',             cls:'arterial', lanes:4, base:.50, surge:.95, mit:.60,
      path:[[-79.4268,43.6340],[-79.4280,43.6402],[-79.4300,43.6452],[-79.4318,43.6505]] },
    { id:'S1',  name:'Strachan Ave',            cls:'arterial', lanes:4, base:.42, surge:.93, mit:.50,
      path:[[-79.4085,43.6345],[-79.4092,43.6402],[-79.4100,43.6452]] },
    { id:'B1',  name:'Bathurst St',             cls:'arterial', lanes:4, base:.46, surge:.82, mit:.58,
      path:[[-79.4022,43.6360],[-79.4030,43.6420],[-79.4038,43.6490]] },
    { id:'K1',  name:'King St W',               cls:'arterial', lanes:2, base:.52, surge:.80, mit:.58, transitPriority:true,
      path:[[-79.4270,43.6400],[-79.4180,43.6420],[-79.4080,43.6440],[-79.3980,43.6458]] },
    { id:'Q1',  name:'Queen St W',              cls:'arterial', lanes:4, base:.48, surge:.74, mit:.55,
      path:[[-79.4290,43.6432],[-79.4180,43.6448],[-79.4070,43.6462]] },
    { id:'SP1', name:'Spadina Ave',             cls:'arterial', lanes:4, base:.50, surge:.72, mit:.56,
      path:[[-79.3955,43.6385],[-79.3962,43.6448]] },
    { id:'LA1', name:'Lansdowne Ave',           cls:'collector', lanes:2, base:.38, surge:.66, mit:.44,
      path:[[-79.4427,43.6372],[-79.4432,43.6438],[-79.4438,43.6500]] },
    { id:'P1',  name:"Princes' Blvd",           cls:'collector', lanes:2, base:.30, surge:.95, mit:.30,
      path:[[-79.4225,43.6342],[-79.4170,43.6345],[-79.4120,43.6350],[-79.4075,43.6356]] },
    { id:'FY1', name:'Fort York Blvd',          cls:'collector', lanes:2, base:.34, surge:.78, mit:.42,
      path:[[-79.4075,43.6356],[-79.4040,43.6372],[-79.4010,43.6388]] },
    // ---- Local streets — cut-through infiltration ----
    { id:'LOC1', name:'Liberty St',             cls:'local', lanes:2, base:.30, surge:.88, mit:.34, local:true,
      path:[[-79.4225,43.6378],[-79.4150,43.6392],[-79.4095,43.6402]] },
    { id:'LOC2', name:'Atlantic Ave',           cls:'local', lanes:2, base:.26, surge:.84, mit:.30, local:true,
      path:[[-79.4205,43.6385],[-79.4185,43.6418]] },
    { id:'LOC3', name:'Springhurst Ave',        cls:'local', lanes:2, base:.28, surge:.90, mit:.32, local:true,
      path:[[-79.4310,43.6360],[-79.4330,43.6388],[-79.4345,43.6410]] },
    { id:'LOC4', name:'Dunn Ave',               cls:'local', lanes:2, base:.24, surge:.80, mit:.28, local:true,
      path:[[-79.4360,43.6362],[-79.4375,43.6398]] },
    // ---- Transit (509 Harbourfront / 511 Bathurst) ----
    { id:'T509', name:'509 Harbourfront',       cls:'transit', lanes:2, base:.35, surge:.70, mit:.45, transit:true,
      path:[[-79.4120,43.6348],[-79.4040,43.6360],[-79.3960,43.6372]] },
    { id:'T511', name:'511 Bathurst',           cls:'transit', lanes:2, base:.33, surge:.64, mit:.42, transit:true,
      path:[[-79.4030,43.6362],[-79.4035,43.6428],[-79.4040,43.6492]] },
  ];

  // corridors that light up in the "blast radius" of the egress event
  const blastRadius = ['L1','D1','S1','G1','P1','FY1','LOC1','LOC2','LOC3','LOC4','T509'];

  // intervention markers placed by the recommended plan
  const actions = [
    { id:'a1', type:'surge',   name:'Toronto Stadium egress', sub:'45,000 · full-time 17:05', coord:[-79.4185,43.6332] },
    { id:'a2', type:'oneway',  name:'Lake Shore W contraflow', sub:'EB egress · Strachan → Bathurst', coord:[-79.4060,43.6362] },
    { id:'a3', type:'signal',  name:'Dufferin × Lake Shore',   sub:'Retime · 110s · egress split', coord:[-79.4268,43.6354] },
    { id:'a4', type:'signal',  name:'Strachan × Lake Shore',   sub:'Retime · 110s · egress split', coord:[-79.4088,43.6350] },
    { id:'a5', type:'closure', name:"Princes' Blvd",           sub:'Pedestrian egress only', coord:[-79.4150,43.6348] },
    { id:'a6', type:'transit', name:'509 / 511 priority hold',  sub:'Signal pre-emption · Exhibition Loop', coord:[-79.4045,43.6360] },
  ];

  const stadium = { name:'Toronto Stadium', sub:'BMO Field · Exhibition Place', coord:[-79.4185,43.6332] };

  // ---- Scenarios ----
  const scenarios = [
    { id:'sc1', badge:'JUN 12', active:true,  name:'FIFA WC26 — Post-match egress',
      meta:'Canada vs UEFA-A · 45,000 · FT 17:05' },
    { id:'sc2', badge:'PLAN',   name:'Gardiner — Jarvis ramp closure', meta:'Capital works · 6 wks' },
    { id:'sc3', badge:'DRAFT',  name:'TTC Line 1 — bus bridge',        meta:'St George ↔ Bloor-Yonge' },
    { id:'sc4', badge:'STUDY',  name:'King St transit-priority ext.',  meta:'Bathurst → Dufferin' },
  ];

  // ---- Intervention tools ----
  const tools = [
    { id:'closure', name:'Full closure',     desc:'Close a segment to all traffic' },
    { id:'lane',    name:'Lane reduction',   desc:'Reduce corridor capacity' },
    { id:'oneway',  name:'Temporary one-way', desc:'Set contraflow / directional egress' },
    { id:'signal',  name:'Signal retiming',  desc:'Adjust cycle splits & offsets' },
    { id:'surge',   name:'Demand surge',     desc:'Inject an event trip spike' },
  ];

  // ---- Metrics, per network state ----
  // value, unit, and direction semantics for delta coloring
  const metrics = {
    base: {
      delay:    { v:1240, u:'veh·h' },
      mean:     { v:11.4, u:'min' },
      p95:      { v:19.2, u:'min' },
      congested:{ v:14,   u:'edges' },
      infil:    { v:6,    u:'%' },
    },
    surge: {
      delay:    { v:4180, u:'veh·h' },
      mean:     { v:28.7, u:'min' },
      p95:      { v:62.5, u:'min' },
      congested:{ v:41,   u:'edges' },
      infil:    { v:34,   u:'%' },
    },
    mit: {
      delay:    { v:2590, u:'veh·h' },
      mean:     { v:17.9, u:'min' },
      p95:      { v:34.1, u:'min' },
      congested:{ v:22,   u:'edges' },
      infil:    { v:10,   u:'%' },
    },
  };
  const metricLabels = {
    delay:    'Total network delay',
    mean:     'Mean travel time',
    p95:      '95th-pct travel time',
    congested:'Congested edges',
    infil:    'Local-road infiltration',
  };

  // ---- Scrubber timeline (match day) ----
  const timeline = {
    startMin: 14*60, endMin: 20*60, step: 15,
    kickoff: 15*60, fulltime: 17*60+5,
    dow: 'FRI · 12 JUN 2026',
    label: 'Matchday replay',
  };

  // ---- Perf / telemetry baselines (on-device, DGX Spark) ----
  const perf = {
    device: 'DGX Spark · GB10',
    base:  { recompute: 0,   subEdges: 0,    subNodes: 0,   llm: 0,   fps: 60 },
    live:  { recompute: 84,  subEdges: 1284, subNodes: 612, llm: 312, fps: 60 },
  };
  const recomputeSteps = ['Demand model','Trip assignment','Edge pressure','Bylaw check','Render'];

  // ---- Copilot scripts ----
  // The hero request → validated, preview-first plan with cited constraints.
  const copilotHero = {
    user: 'Ease post-match gridlock near BMO Field without breaking bylaws.',
    botLead: "Full-time at Toronto Stadium releases <b>~45,000</b> over 25 minutes. I assigned egress demand to the Lake Shore / Strachan / Dufferin spine and found severe spill-over into Parkdale and Liberty Village local streets. A bylaw-valid mitigation:",
    steps: [
      'Eastbound contraflow on Lake Shore Blvd W (Strachan → Bathurst), 17:00–18:30',
      'Retime Dufferin and Strachan signals — 110 s cycle, egress-biased splits',
      "Close Princes' Blvd to general traffic (pedestrian egress); hold 509 / 511 transit priority",
    ],
    citations: [
      { ref:'Toronto Municipal Code Ch. 950', note:'temporary traffic regulation under an approved event TMP' },
      { ref:'King St Transit Priority Corridor', note:'through-traffic restriction preserved' },
      { ref:'Toronto Municipal Code Ch. 880', note:'fire-route / emergency access lanes maintained' },
      { ref:'AODA 2005', note:"accessible pedestrian route on Princes' Blvd retained" },
    ],
    botTail: "Projected vs. unmitigated: total delay <b>−38%</b>, local infiltration <b>−71%</b>, zero hard-constraint conflicts. Preview on the map?",
  };

  // Constraint-blocked path (manual or chip).
  const copilotBlocked = {
    user: 'Just close Lake Shore both ways.',
    botLead: "I can't apply that — it breaches two <b>hard</b> constraints:",
    steps: [
      'Removes the only emergency corridor to Stadium South — Toronto Fire access lost',
      '509 / 511 replacement-bus routing requires a westbound Lake Shore lane',
    ],
    citations: [
      { ref:'Toronto Municipal Code Ch. 880', note:'designated fire route may not be fully closed' },
      { ref:'TTC service bylaw', note:'streetcar-replacement bus lane must be retained' },
    ],
    botTail: "Action <b>blocked</b>. The eastbound-contraflow alternative clears 84% of the same demand without these conflicts — apply that instead?",
    blocked: true,
  };

  const copilotChips = [
    'Ease post-match gridlock near BMO Field without breaking bylaws.',
    'Just close Lake Shore both ways.',
    'Protect Parkdale local streets from cut-through.',
  ];

  return {
    corridors, blastRadius, actions, stadium, scenarios, tools,
    metrics, metricLabels, timeline, perf, recomputeSteps,
    copilotHero, copilotBlocked, copilotChips,
    center: [-79.4163, 43.6362],
  };
})();
