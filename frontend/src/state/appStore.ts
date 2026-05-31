/**
 * App state (Zustand) for the two-view IDE (Simulate · Edit).
 *
 * Every traffic number is real engine output:
 *   loadTwin     → /edges (+ build the vertex/adjacency graph) + /demo/run?scenario=baseline
 *   saveCurrent  → POST/PATCH /scenarios   (saved simulations, left rail in Simulate)
 *   applyEdits   → /scenarios run (blast recompute) + /scenarios/{id}/records
 *   copilotAsk   → /copilot/plan
 * Per-edge pressures live in the tick-store typed arrays (out of React); a bumped
 * `pressureSeq` drives the deck.gl recolor.
 *
 * Edit model (per the agreed spec): two tools only — a **full closure** (pick two
 * intersections → seal the corridor of edges between them) and a **demand surge**
 * (pick one intersection → inject trips).
 */
import { create } from "zustand";
import {
  api,
  connectDayStream,
  type CopilotResponse,
  type DayStreamSpec,
  type EdgeMeta,
  type Intervention,
  type ScenarioSummary,
} from "../api/client";
import {
  buildGraph,
  corridorBetween,
  nearestEdge,
  nearestNode,
  streetsByDirection,
  withReverseTwins,
  type RoadGraph,
} from "../api/graph";
import { DEFAULT_DAY_OF_YEAR, TIMELINE } from "../config";
import { buildTimeContext } from "../lib/timeContext";
import {
  getArrays,
  ingestBaselineDay,
  readyCount,
  resizeTickStore,
  setEpoch,
  setSelectedHour,
  writeRecords,
} from "./tickStore";

export type View = "sim" | "edit";
export type EditTool = "select" | "closure" | "surge";
export type StatusState = "nominal" | "recomputing" | "surge" | "blocked";
export type DemandModel = "xgboost" | "gnn";

export const RECOMPUTE_STEPS = [
  "Demand model",
  "Trip assignment",
  "Edge pressure",
  "Bylaw check",
  "Render",
];

export interface SurgeParams {
  amount: number;
  mode: "absolute" | "relative";
  kind: "surge" | "relief"; // increase vs decrease demand
  dirs: { n: boolean; e: boolean; s: boolean; w: boolean }; // compass directions of flow
}

/** A placed Edit-mode intervention (closure or surge). */
export interface SceneObject {
  id: string;
  type: "closure" | "surge";
  name: string;
  visible: boolean;
  n: number;
  coord: [number, number]; // pin position (surge: the anchor vertex; closure: corridor midpoint)
  roadName?: string;
  baselinePressure?: number;
  // closure
  vertices?: { key: string; lng: number; lat: number }[];
  edgeIds?: string[];
  // demand change (surge / relief radiating from a vertex)
  edgeId?: string;
  anchorKey?: string; // the intersection the demand radiates from (graph vertex key)
  surge?: SurgeParams;
}

export interface Warning {
  id: string;
  severity: "info" | "warn" | "danger";
  title: string;
  detail: string;
  ref?: string;
}

interface CopilotMessage {
  role: "user" | "bot";
  text: string;
  steps?: string[];
  citations?: { ref: string; note: string }[];
  blocked?: boolean;
}

interface Telemetry {
  recompute: number;
  subEdges: number;
  llm: number;
  fps: number;
}

const IDLE: Telemetry = { recompute: 12, subEdges: 0, llm: 0, fps: 60 };

type PendingVertex = { key: string; lng: number; lat: number };

interface AppState {
  // tweakables
  theme: "light" | "dark";
  density: "comfortable" | "compact";
  intensity: number;
  // shell
  view: View;
  showLeft: boolean;
  showRight: boolean;
  showBottom: boolean;
  showRail: boolean;
  // machine
  loaded: boolean;
  loading: boolean;
  error: string | null;
  recomputing: boolean;
  recomputeStep: number;
  recomputeTitle: string;
  planStaged: boolean;
  status: { state: StatusState; label: string };
  // data
  edges: EdgeMeta[];
  graph: RoadGraph | null;
  pressureSeq: number;
  warnings: Warning[];
  // saved simulations
  savedSims: ScenarioSummary[];
  scenarioId: string | null;
  activeSavedSimId: string | null;
  currentName: string;
  dirty: boolean;
  // simulate selection
  selectedRoadId: string | null;
  // editor
  activeTool: EditTool;
  objects: SceneObject[];
  selectedId: string | null;
  pendingVertices: PendingVertex[];
  // copilot / timeline / telemetry
  copilotLog: CopilotMessage[];
  scrubberMinute: number;
  dayOfYear: number;
  playing: boolean;
  speed: number;
  telemetry: Telemetry;
  // param-driven simulation (real ML models)
  demandModel: DemandModel; // which model the Run uses (toggle)
  modelActual: string; // model that actually ran (exposes heuristic fallback)
  simStale: boolean; // params/edits changed since the last Run
  // day time-series fill: how many of the 24 hourly frames have landed for the
  // current view. Drives the Run button's progress ring ("Live" at 24/24).
  dayFill: { ready: number; total: number };
  // camera nonces (watched by MapCanvas)
  recenterNonce: number;
  tiltOn: boolean;

  setTheme: (t: "light" | "dark") => void;
  setDensity: (d: "comfortable" | "compact") => void;
  toggleDock: (which: "left" | "right" | "bottom" | "rail") => void;
  setView: (v: View) => void;
  loadTwin: () => Promise<void>;
  // saved sims
  loadSavedSims: () => Promise<void>;
  newSim: () => void;
  saveCurrent: (name?: string) => Promise<void>;
  selectSavedSim: (id: string) => Promise<void>;
  deleteSavedSim: (id: string) => Promise<void>;
  setCurrentName: (name: string) => void;
  // copilot
  copilotAsk: (text: string) => Promise<void>;
  applyPlan: () => Promise<void>;
  discardPlan: () => void;
  // editor
  selectTool: (id: EditTool) => void;
  placeAt: (coord: [number, number]) => Promise<void>;
  selectObject: (id: string | null) => void;
  deleteObject: (id: string) => void;
  toggleObjectVis: (id: string) => void;
  setSurgeParams: (id: string, patch: Partial<SurgeParams>) => void;
  applyEdits: () => Promise<void>;
  clearPending: () => void;
  // simulate
  selectRoad: (edgeId: string | null) => void;
  setScrubber: (m: number) => void;
  setDayOfYear: (d: number) => void;
  setDemandModel: (m: DemandModel) => void;
  runSimulate: () => Promise<void>;
  prewarm: () => void;
  setPlaying: (p: boolean) => void;
  setSpeed: (s: number) => void;
  recenter: () => void;
  toggleTilt: () => void;
  reset: () => Promise<void>;
}

type SetFn = (p: Partial<AppState> | ((s: AppState) => Partial<AppState>)) => void;

/** Recompute warnings from the live per-edge pressures (real engine output). */
function buildWarnings(): Warning[] {
  const arr = getArrays().pressure;
  let severe = 0;
  let high = 0;
  for (let i = 0; i < arr.length; i++) {
    const p = arr[i];
    if (p >= 1.0) severe++;
    else if (p >= 0.75) high++;
  }
  const out: Warning[] = [];
  if (severe > 0)
    out.push({
      id: "severe",
      severity: "danger",
      title: `${severe.toLocaleString()} edges in gridlock`,
      detail: "Pressure ≥ 1.0 — demand exceeds capacity on these segments.",
    });
  if (high > 0)
    out.push({
      id: "high",
      severity: "warn",
      title: `${high.toLocaleString()} high-risk edges`,
      detail: "Pressure 0.75–1.0 — approaching capacity.",
    });
  if (out.length === 0)
    out.push({
      id: "ok",
      severity: "info",
      title: "Network nominal",
      detail: "No edges above the high-risk threshold.",
    });
  return out;
}

function paintBaseline(set: SetFn, records: [number, number, number, number, number][]) {
  writeRecords(records);
  set((s) => ({ pressureSeq: s.pressureSeq + 1, warnings: buildWarnings() }));
}

async function recomputeAround(set: SetFn, title: string, fn: () => Promise<void>) {
  set({
    recomputing: true,
    recomputeStep: 0,
    recomputeTitle: title,
    status: { state: "recomputing", label: "Recomputing…" },
  });
  const start = performance.now();
  const stepper = setInterval(
    () => set((s) => ({ recomputeStep: Math.min(s.recomputeStep + 1, RECOMPUTE_STEPS.length - 1) })),
    240,
  );
  try {
    await fn();
  } finally {
    clearInterval(stepper);
    const ms = Math.round(performance.now() - start);
    set((s) => ({
      recomputing: false,
      recomputeStep: RECOMPUTE_STEPS.length,
      telemetry: { ...s.telemetry, recompute: ms, fps: 60 },
    }));
  }
}

/** Flatten the placed scene objects into backend interventions. */
function interventionsFromObjects(objects: SceneObject[]): Intervention[] {
  const out: Intervention[] = [];
  for (const o of objects) {
    if (!o.visible) continue;
    if (o.type === "closure") {
      for (const edgeId of o.edgeIds ?? []) out.push({ op: "close_edge", edge_id: edgeId });
    } else if (o.type === "surge" && o.surge) {
      // Demand-side op: relief is a negative amount. Applied to per-node demand
      // before OD generation by the backend (model/demand_surge.py).
      const signed = o.surge.kind === "relief" ? -Math.abs(o.surge.amount) : Math.abs(o.surge.amount);
      out.push({
        op: "demand_change",
        edge_id: o.edgeId,
        directions: (["n", "e", "s", "w"] as const).filter((d) => o.surge!.dirs[d]),
        amount: signed,
        mode: o.surge.mode,
        lng: o.coord[0],
        lat: o.coord[1],
      });
    }
  }
  return out;
}

type GetFn = () => AppState;

/** The view to stream as a 24-hour series: model + day/month + all edits. The
 * hour is the playback axis, not an input — `current_hour` only sets fill order. */
function dayStreamSpec(s: AppState, epoch: number): DayStreamSpec {
  const tc = buildTimeContext(s.dayOfYear, s.scrubberMinute);
  return {
    demand_model: s.demandModel,
    time_context: { day_of_week: tc.day_of_week, month: tc.month, weather: "clear" },
    interventions: interventionsFromObjects(s.objects),
    current_hour: tc.hour,
    epoch,
  };
}

// One day-stream WS per view. Defining a new view (model / day / edits change)
// supersedes the old one: bump the epoch, reset readiness, close the old socket,
// open a new one. This IS the speculative compute behind the Run "illusion" —
// the backend fills the day (current hour first) and each hour's frame repaints
// the map only when it's the visible hour. Frames from a stale epoch are dropped
// in the tick store and ignored here.
let _dayWs: WebSocket | null = null;
let _dayEpoch = 0;
let _dayTimer: ReturnType<typeof setTimeout> | null = null;

function startDayCompute(set: SetFn, get: GetFn, opts: { immediate?: boolean } = {}): void {
  const kick = () => {
    _dayTimer = null;
    const epoch = ++_dayEpoch;
    setEpoch(epoch); // new view: forget readiness (old frames keep painting until replaced)
    if (_dayWs) {
      try {
        _dayWs.close();
      } catch {
        /* already closing */
      }
    }
    set({ dayFill: { ready: 0, total: 24 }, simStale: false });

    // Surface a stuck/failed compute instead of hanging at "Computing X/24".
    let failed = false;
    const fail = (label: string) => {
      if (epoch !== _dayEpoch || failed) return; // ignore superseded views / double-fire
      failed = true;
      clearTimeout(watchdog);
      set({ status: { state: "blocked", label }, simStale: true });
    };
    // Backstop for a silent stall: if NO hour has landed in this window the stream
    // is wedged. Generous margin — a cold first request pays a one-time ~25s model
    // load before the first hour; once any hour lands this is moot (progressive).
    const watchdog = setTimeout(() => {
      if (epoch === _dayEpoch && readyCount() === 0) fail("Compute stalled — click Run to retry");
    }, 45000);

    _dayWs = connectDayStream(dayStreamSpec(get(), epoch), {
      onMeta: (meta) => {
        if (epoch !== _dayEpoch) return; // a newer view already superseded this one
        set({ modelActual: meta.model_actual });
      },
      onFrame: (info) => {
        if (epoch !== _dayEpoch) return;
        set((st) => ({
          dayFill: { ready: readyCount(), total: 24 },
          // Repaint only when the frame that landed is the hour on screen.
          ...(info.affectsView
            ? { pressureSeq: st.pressureSeq + 1, warnings: buildWarnings() }
            : {}),
        }));
      },
      onDone: () => {
        if (epoch !== _dayEpoch) return;
        clearTimeout(watchdog);
        set({ dayFill: { ready: readyCount(), total: 24 } });
      },
      onError: () => fail("Compute failed — click Run to retry"),
      onPrematureClose: () => fail("Compute interrupted — click Run to retry"),
    });
  };

  if (_dayTimer) clearTimeout(_dayTimer);
  if (opts.immediate) kick();
  else _dayTimer = setTimeout(kick, 350); // coalesce a flurry of tweaks into one view
}

/** True when the scene has any active (visible) intervention. */
function hasEdits(s: AppState): boolean {
  return interventionsFromObjects(s.objects).length > 0;
}

/** Tear down any live/pending ML day-stream and invalidate its callbacks. */
function closeDayStream(): void {
  _dayEpoch++; // in-flight onFrame/onMeta/onDone guards (epoch !== _dayEpoch) now fail
  if (_dayTimer) {
    clearTimeout(_dayTimer);
    _dayTimer = null;
  }
  if (_dayWs) {
    try {
      _dayWs.close();
    } catch {
      /* already closing */
    }
    _dayWs = null;
  }
}

/** The no-edit view: the full-coverage GNN-predicted day (one REST blob, ingested
 * in a single pass). The GNN predicts a pressure for every edge directly, so this
 * is the "usual congestion in the city" — full coverage, fast (~0.3s warm), cached
 * server-side. Always the GNN regardless of the model toggle (the toggle is the
 * EDIT demand model). Placing an edit switches to the equilibrium day-stream. */
async function loadBaselineDay(set: SetFn, get: GetFn): Promise<void> {
  closeDayStream(); // baseline is the epoch-0 view; drop any live edit stream
  const tc = buildTimeContext(get().dayOfYear, get().scrubberMinute);
  set({ status: { state: "recomputing", label: "Predicting baseline…" } });
  try {
    const buf = await api.baselinePredicted(tc.day_of_week, tc.month);
    ingestBaselineDay(buf);
    setSelectedHour(Math.min(23, Math.floor(get().scrubberMinute / 60)));
    set((s) => ({
      pressureSeq: s.pressureSeq + 1,
      warnings: buildWarnings(),
      dayFill: { ready: readyCount(), total: 24 },
      modelActual: "gnn",
      simStale: false,
      status: { state: "nominal", label: "Baseline · predicted (GNN)" },
    }));
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    set({
      error: `Baseline unavailable (${msg}).`,
      status: { state: "blocked", label: "Baseline unavailable — click Run to retry" },
    });
  }
}

/** After an edit changes: run the ML day-stream if edits remain, else fall back
 * to the measured baseline (removing the last edit returns you to "now"). */
function afterEditChange(set: SetFn, get: GetFn): void {
  if (hasEdits(get())) startDayCompute(set, get);
  else void loadBaselineDay(set, get);
}

export const useAppStore = create<AppState>((set, get) => ({
  theme: "light",
  density: "comfortable",
  intensity: 1.0,
  view: "sim",
  showLeft: true,
  showRight: true,
  showBottom: true,
  showRail: false,
  loaded: false,
  loading: false,
  error: null,
  recomputing: false,
  recomputeStep: 0,
  recomputeTitle: "",
  planStaged: false,
  status: { state: "nominal", label: "Baseline · nominal" },
  edges: [],
  graph: null,
  pressureSeq: 0,
  warnings: [],
  savedSims: [],
  scenarioId: null,
  activeSavedSimId: null,
  currentName: "Untitled simulation",
  dirty: false,
  selectedRoadId: null,
  activeTool: "select",
  objects: [],
  selectedId: null,
  pendingVertices: [],
  copilotLog: [],
  scrubberMinute: TIMELINE.defaultMin,
  dayOfYear: DEFAULT_DAY_OF_YEAR,
  playing: false,
  speed: 1,
  telemetry: { ...IDLE },
  demandModel: "xgboost",
  modelActual: "",
  simStale: false,
  dayFill: { ready: 0, total: 24 },
  recenterNonce: 0,
  tiltOn: true,

  setTheme: (t) => {
    document.documentElement.setAttribute("data-theme", t);
    set({ theme: t });
  },
  setDensity: (d) => {
    document.documentElement.setAttribute("data-density", d);
    set({ density: d });
  },
  toggleDock: (which) =>
    set((s) => ({
      showLeft: which === "left" ? !s.showLeft : s.showLeft,
      showRight: which === "right" ? !s.showRight : s.showRight,
      showBottom: which === "bottom" ? !s.showBottom : s.showBottom,
      showRail: which === "rail" ? !s.showRail : s.showRail,
    })),

  setView: (v) => {
    if (v === get().view) return;
    set({
      view: v,
      showBottom: v === "sim",
      showRail: v === "edit",
      activeTool: v === "sim" ? "select" : get().activeTool,
      pendingVertices: [],
    });
  },

  loadTwin: async () => {
    if (get().loaded) return;
    set({ loading: true, error: null });
    try {
      const { edges } = await api.edges();
      resizeTickStore(edges.length);
      const graph = buildGraph(edges);
      set({
        edges,
        graph,
        loaded: true,
        status: { state: "recomputing", label: "Graph loaded · painting baseline…" },
        telemetry: { ...IDLE },
      });
      // Paint the MEASURED baseline day from raw TMC counts — instant, no ML, no
      // WebSocket. The model runs only once the user starts editing.
      await loadBaselineDay(set, get);
      void get().loadSavedSims();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: `Could not reach the API (${msg}). Start scripts/run_api.sh.` });
    } finally {
      set({ loading: false });
    }
  },

  loadSavedSims: async () => {
    try {
      const { scenarios } = await api.listScenarios();
      set({ savedSims: scenarios });
    } catch {
      /* keep whatever we have */
    }
  },

  newSim: () =>
    set({
      objects: [],
      selectedId: null,
      pendingVertices: [],
      scenarioId: null,
      activeSavedSimId: null,
      currentName: "Untitled simulation",
      dirty: false,
    }),

  saveCurrent: async (name) => {
    const s = get();
    const finalName = (name ?? s.currentName) || "Untitled simulation";
    const interventions = interventionsFromObjects(s.objects);
    try {
      if (s.activeSavedSimId) {
        await api.patchScenario(s.activeSavedSimId, { name: finalName, interventions });
        set({ currentName: finalName, dirty: false });
      } else {
        const created = await api.createScenario({ name: finalName, interventions });
        set({ activeSavedSimId: created.id, scenarioId: created.id, currentName: finalName, dirty: false });
      }
      await get().loadSavedSims();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: `Save failed (${msg}).` });
    }
  },

  selectSavedSim: async (id) => {
    set({ activeSavedSimId: id, scenarioId: id });
    const meta = get().savedSims.find((x) => x.id === id);
    if (meta?.name) set({ currentName: meta.name });
    await recomputeAround(set, "Loading saved simulation…", async () => {
      try {
        await api.run(id, { recompute: "full", congestion_model: "bpr" });
        const rec = await api.scenarioRecords(id);
        paintBaseline(set, rec.records);
      } catch {
        /* leave current paint if the run fails */
      }
    });
    set({ dirty: false, status: { state: "nominal", label: "Saved sim · loaded" } });
  },

  deleteSavedSim: async (id) => {
    try {
      await api.deleteScenario(id);
    } catch {
      /* ignore */
    }
    set((s) => ({
      savedSims: s.savedSims.filter((x) => x.id !== id),
      activeSavedSimId: s.activeSavedSimId === id ? null : s.activeSavedSimId,
    }));
  },

  setCurrentName: (name) => set({ currentName: name, dirty: true }),

  copilotAsk: async (text) => {
    set((s) => ({ copilotLog: [...s.copilotLog, { role: "user", text }] }));
    let resp: CopilotResponse;
    try {
      resp = await api.copilotPlan(text);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      set((s) => ({ copilotLog: [...s.copilotLog, { role: "bot", text: `Copilot unavailable: ${msg}` }] }));
      return;
    }
    set((s) => ({
      copilotLog: [
        ...s.copilotLog,
        { role: "bot", text: resp.rationale, citations: resp.citations, blocked: resp.blocked },
      ],
    }));
    if (resp.blocked) {
      set((s) => ({
        status: { state: "blocked", label: "Action blocked · bylaw conflict" },
        warnings: [
          {
            id: "bylaw",
            severity: "danger",
            title: "Bylaw conflict",
            detail: resp.rationale,
            ref: resp.citations?.[0]?.ref,
          },
          ...s.warnings,
        ],
      }));
      return;
    }
    set({ planStaged: true });
  },

  applyPlan: async () => {
    set({ planStaged: false });
    await get().applyEdits();
  },
  discardPlan: () => set({ planStaged: false }),

  selectTool: (id) =>
    set({ activeTool: id, selectedId: id === "select" ? get().selectedId : null, pendingVertices: [] }),

  placeAt: async (coord) => {
    const { activeTool, graph } = get();
    if (activeTool === "select" || !graph) return;
    const [lng, lat] = coord;

    if (activeTool === "surge") {
      // Demand change anchors at the intersection nearest the click; demand then
      // radiates out along the streets leaving that vertex in the chosen compass
      // directions. The street the user clicked seeds the default direction.
      const near = nearestEdge(graph, lng, lat);
      if (!near) return;
      const distTo = (k: string) => {
        const n = graph.nodes.get(k);
        return n ? (n.lng - lng) ** 2 + (n.lat - lat) ** 2 : Infinity;
      };
      const anchorKey = distTo(near.fromKey) <= distTo(near.toKey) ? near.fromKey : near.toKey;
      const anchor = graph.nodes.get(anchorKey);
      if (!anchor) return;
      const streets = streetsByDirection(graph, anchorKey);
      const clickedDir = (["n", "e", "s", "w"] as const).find((d) => streets[d]?.edge_id === near.edge_id);
      const defaultDir = clickedDir ?? (["e", "n", "s", "w"] as const).find((d) => streets[d]) ?? "e";
      const seq = get().objects.length + 1;
      const obj: SceneObject = {
        id: `obj${Date.now()}`,
        type: "surge",
        name: `Demand${near.road_name ? " · " + near.road_name : ""} · surge`,
        visible: true,
        n: seq,
        coord: [anchor.lng, anchor.lat],
        roadName: near.road_name,
        edgeId: near.edge_id,
        anchorKey,
        baselinePressure: getArrays().pressure[near.idx],
        surge: {
          amount: 500,
          mode: "absolute",
          kind: "surge",
          dirs: { n: defaultDir === "n", e: defaultDir === "e", s: defaultDir === "s", w: defaultDir === "w" },
        },
      };
      set((s) => ({ objects: [...s.objects, obj], selectedId: obj.id, activeTool: "select", dirty: true }));
      startDayCompute(set, get); // edit renders instantly; the day refills in the background
      return;
    }

    // closure: collect two vertices, then seal the corridor between them.
    const node = nearestNode(graph, lng, lat);
    if (!node) return;
    const v: PendingVertex = { key: node.key, lng: node.lng, lat: node.lat };
    const pending = [...get().pendingVertices, v];
    if (pending.length < 2) {
      set({ pendingVertices: pending });
      return;
    }
    const [a, b] = pending;
    const corridor = corridorBetween(graph, a.key, b.key);
    const edges = withReverseTwins(graph, corridor);
    const edgeIds = edges.map((e) => e.edge_id);
    const midLng = (a.lng + b.lng) / 2;
    const midLat = (a.lat + b.lat) / 2;
    const roadName = corridor[0]?.road_name;
    const seq = get().objects.length + 1;
    const obj: SceneObject = {
      id: `obj${Date.now()}`,
      type: "closure",
      name: `Closure${roadName ? " · " + roadName : ""}`,
      visible: true,
      n: seq,
      coord: [midLng, midLat],
      roadName,
      vertices: [a, b],
      edgeIds,
    };
    set((s) => ({
      objects: [...s.objects, obj],
      selectedId: obj.id,
      activeTool: "select",
      pendingVertices: [],
      dirty: true,
    }));
    startDayCompute(set, get); // edit renders instantly; Run recolors traffic
  },

  selectObject: (id) => set({ selectedId: id, activeTool: "select" }),
  deleteObject: (id) => {
    set((s) => ({
      objects: s.objects.filter((o) => o.id !== id),
      selectedId: s.selectedId === id ? null : s.selectedId,
      dirty: true,
    }));
    afterEditChange(set, get); // back to measured baseline if that was the last edit
  },
  toggleObjectVis: (id) => {
    set((s) => ({
      objects: s.objects.map((o) => (o.id === id ? { ...o, visible: !o.visible } : o)),
      dirty: true,
    }));
    afterEditChange(set, get);
  },
  setSurgeParams: (id, patch) => {
    set((s) => ({
      objects: s.objects.map((o) => {
        if (o.id !== id || !o.surge) return o;
        const surge = { ...o.surge, ...patch };
        const name =
          patch.kind !== undefined
            ? `Demand${o.roadName ? " · " + o.roadName : ""} · ${surge.kind}`
            : o.name;
        return { ...o, surge, name };
      }),
      dirty: true,
    }));
    startDayCompute(set, get);
  },
  clearPending: () => set({ pendingVertices: [] }),

  // "Run" doubles as the recovery/retry control. With edits, (re)start the ML
  // day-stream unless one is already healthily in flight; with no edits, (re)load
  // the baseline. So after a failed/stalled compute, clicking Run always retries.
  runSimulate: async () => {
    if (hasEdits(get())) {
      if (!_dayWs || _dayWs.readyState !== WebSocket.OPEN) startDayCompute(set, get, { immediate: true });
    } else {
      void loadBaselineDay(set, get);
    }
  },

  prewarm: () => {
    if (hasEdits(get())) startDayCompute(set, get); // nothing to prewarm for the baseline
  },

  // Copilot's "apply plan": refill the day for the current model + edits.
  applyEdits: async () => {
    startDayCompute(set, get, { immediate: true });
  },

  selectRoad: (edgeId) => set({ selectedRoadId: edgeId }),
  setScrubber: (m) => {
    const next = Math.max(TIMELINE.startMin, Math.min(TIMELINE.endMin, m));
    set({ scrubberMinute: next });
    // Time is a playback axis now: select the hour's precomputed frame and
    // repaint from the buffer — never a network call / recompute.
    const hour = Math.min(23, Math.floor(next / 60));
    if (setSelectedHour(hour)) set((s) => ({ pressureSeq: s.pressureSeq + 1, warnings: buildWarnings() }));
  },
  setDayOfYear: (d) => {
    set({ dayOfYear: Math.max(1, Math.min(366, Math.round(d))) });
    // Day/month changes the predicted baseline; reload it (or re-run ML if editing).
    if (hasEdits(get())) startDayCompute(set, get);
    else void loadBaselineDay(set, get);
  },
  setDemandModel: (m) => {
    if (m === get().demandModel) return;
    set({ demandModel: m });
    // The toggle is the EDIT demand model only — the baseline is always the GNN
    // prediction — so re-run the equilibrium day-stream only when there are edits.
    if (hasEdits(get())) startDayCompute(set, get);
  },
  setPlaying: (p) => set({ playing: p }),
  setSpeed: (sp) => set({ speed: sp }),

  recenter: () => set((s) => ({ recenterNonce: s.recenterNonce + 1 })),
  toggleTilt: () => set((s) => ({ tiltOn: !s.tiltOn })),

  reset: async () => {
    set({
      objects: [],
      selectedId: null,
      pendingVertices: [],
      scenarioId: null,
      activeSavedSimId: null,
      currentName: "Untitled simulation",
      dirty: false,
      planStaged: false,
      selectedRoadId: null,
      copilotLog: [],
      scrubberMinute: TIMELINE.defaultMin,
      playing: false,
      status: { state: "nominal", label: "Baseline · nominal" },
      telemetry: { ...IDLE },
      recenterNonce: get().recenterNonce + 1,
    });
    // No edits → back to the measured baseline day.
    void loadBaselineDay(set, get);
  },
}));
