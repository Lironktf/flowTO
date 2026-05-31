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
  copilotStream,
  type AgentStepLog,
  type CopilotResponse,
  type DayStreamSpec,
  type EdgeMeta,
  type Intervention,
  type ScenarioSummary,
  type ViewDirective,
} from "../api/client";
import {
  buildGraph,
  corridorBetween,
  nearestEdge,
  nearestNode,
  streetsByDirection,
  withReverseTwins,
  type RoadGraph,
  type Segment,
} from "../api/graph";
import {
  buildRoadIndex,
  resolveQuery,
  retrievePlace,
  type RoadIndexEntry,
  type SearchHit,
} from "../lib/search";
import { COPILOT_CHIPS, DEFAULT_DAY_OF_YEAR, TIMELINE } from "../config";

// Cache the omnibox road index so the copilot can reuse the SAME resolver as the
// search bar without rescanning every edge per call. Rebuilt only when the graph
// instance changes (graph is effectively load-once).
let _idxGraph: RoadGraph | null = null;
let _idxCache: RoadIndexEntry[] = [];
function roadIndexFor(g: RoadGraph | null): RoadIndexEntry[] {
  if (!g) return [];
  if (g !== _idxGraph) {
    _idxCache = buildRoadIndex(g);
    _idxGraph = g;
  }
  return _idxCache;
}
import {
  getArrays,
  ingestBaselineDay,
  readyCount,
  resizeTickStore,
  setEpoch,
  setSelectedHour,
  writeRecords,
} from "./tickStore";
import { buildTimeContext } from "../lib/timeContext";

/** Demand model the day-stream / simulate path runs with (the Edit-mode toggle). */
export type DemandModel = "xgboost" | "gnn";

export type View = "sim" | "edit";
export type EditTool = "select" | "closure" | "surge";
export type StatusState = "nominal" | "recomputing" | "surge" | "blocked";

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
  kind?: "restricted"; // restricted-road closure guardrail (shown in the left menu)
}

export type CopilotMode = "plan" | "chat" | "agent";

export interface CopilotMessage {
  role: "user" | "bot";
  text: string;
  steps?: string[];
  citations?: { ref: string; note: string }[];
  blocked?: boolean;
  // A previewed, confirmable plan (preview-before-apply): the ops to apply.
  interventions?: Intervention[];
  // Severity-coded warnings from the SSOT assess pass (warn-don't-block).
  warnings?: { severity?: string; title?: string; detail?: string; ref?: string | null }[];
  applied?: boolean;
  reverted?: boolean;
  // Post-confirm result for the metric card (Δ vs baseline).
  result?: {
    summaryDelta: Record<string, number>;
    mostImpacted: { edge_id: string; road_name?: string | null }[];
  };
  // Agent-mode investigation trace + live-streaming flag.
  agentSteps?: AgentStepLog[];
  streaming?: boolean;
  // Which mode produced this reply (badge), and whether it was aborted.
  mode?: CopilotMode;
  aborted?: boolean;
}

interface CopilotLatency {
  ms: number;
  firstTokenMs?: number;
  mode: CopilotMode;
}

/** An archived chat — its full message log, with a title for the history list. */
export interface CopilotSession {
  id: string;
  title: string;
  log: CopilotMessage[];
}

const COPILOT_SESSIONS_KEY = "flowto.copilot.sessions";
const COPILOT_SESSION_SEQ_KEY = "flowto.copilot.sessionSeq";

/** Persist sessions + the id counter to localStorage (best-effort). */
function persistSessions(sessions: CopilotSession[], seq: number) {
  try {
    localStorage.setItem(COPILOT_SESSIONS_KEY, JSON.stringify(sessions));
    localStorage.setItem(COPILOT_SESSION_SEQ_KEY, String(seq));
  } catch {
    /* storage unavailable (private mode / SSR) — keep going in-memory */
  }
}

/** Rehydrate sessions + the id counter from localStorage on load. */
function loadSessions(): { sessions: CopilotSession[]; seq: number } {
  try {
    const raw = localStorage.getItem(COPILOT_SESSIONS_KEY);
    const sessions = raw ? (JSON.parse(raw) as CopilotSession[]) : [];
    const seq = Number(localStorage.getItem(COPILOT_SESSION_SEQ_KEY) ?? "0") || 0;
    return { sessions: Array.isArray(sessions) ? sessions : [], seq };
  } catch {
    return { sessions: [], seq: 0 };
  }
}

/** First user message, truncated — used as a session title. */
function sessionTitle(log: CopilotMessage[]): string {
  const firstUser = log.find((m) => m.role === "user")?.text?.trim();
  const base = firstUser || "Untitled chat";
  return base.length > 40 ? base.slice(0, 40) + "…" : base;
}

// A staged (previewed, not-yet-applied) copilot plan. Single source of truth so
// the chat confirm and the map preview act on the same plan + edges — one apply.
interface StagedPlan {
  msgIndex: number; // the bot message in copilotLog carrying this plan
  interventions: Intervention[];
  edgeIds: string[]; // close_edge targets — drives the map preview overlay
}

// Non-reactive holder for the in-flight request's abort controller.
let copilotAbort: AbortController | null = null;

// Rehydrated once at module load (localStorage), seeds the store's initial state.
const INITIAL_SESSIONS = loadSessions();

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
  // machine
  loaded: boolean;
  loading: boolean;
  error: string | null;
  recomputing: boolean;
  recomputeStep: number;
  recomputeTitle: string;
  stagedPlan: StagedPlan | null; // a previewed copilot plan awaiting confirm (single source)
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
  copilotSessions: CopilotSession[]; // archived chats (history menu)
  copilotSessionSeq: number; // incrementing counter for session ids (no Date.now/Math.random)
  deepMode: boolean; // 🧠 Deep → force the Agent investigate-loop; else auto-route
  copilotReady: boolean; // false until the backend's compare baseline is warm
  copilotThinking: boolean;
  copilotPendingMode: CopilotMode | null; // resolved mode while thinking → labels the one loader
  copilotChips: string[]; // suggestion prompts (dynamic from /copilot/suggestions; static fallback)
  copilotLatency: CopilotLatency | null;
  scrubberMinute: number;
  dayOfYear: number;
  playing: boolean;
  speed: number;
  // day-stream playback (24-hour precomputed series)
  demandModel: DemandModel; // which model the Run/day-stream uses (Edit toggle)
  modelActual: string; // model that actually ran (exposes the heuristic fallback)
  simStale: boolean; // params/edits changed since the last Run
  dayFill: { ready: number; total: number }; // how many of the 24 hourly frames have landed
  telemetry: Telemetry;
  // camera nonces (watched by MapCanvas)
  recenterNonce: number;
  tiltOn: boolean;
  flyTarget: { lng: number; lat: number; zoom?: number } | null;
  flyNonce: number;
  fitTarget: [[number, number], [number, number]] | null;
  fitNonce: number;
  flyPin: [number, number] | null; // a searched place, marked on the map

  setTheme: (t: "light" | "dark") => void;
  setDensity: (d: "comfortable" | "compact") => void;
  toggleDock: (which: "left" | "right" | "bottom") => void;
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
  copilotConfirm: (msgIndex: number) => Promise<void>;
  copilotRevert: (msgIndex: number) => Promise<void>;
  toggleDeep: () => void;
  copilotStop: () => void;
  copilotNewChat: () => void;
  copilotLoadSession: (id: string) => void;
  // editor
  selectTool: (id: EditTool) => void;
  placeAt: (coord: [number, number]) => Promise<void>;
  selectObject: (id: string | null) => void;
  deleteObject: (id: string) => void;
  toggleObjectVis: (id: string) => void;
  setSurgeParams: (id: string, patch: Partial<SurgeParams>) => void;
  applyEdits: () => Promise<void>;
  clearPending: () => void;
  // search → close: seal an entire named street, or arm the corridor tool over it
  closeStreet: (roadName: string) => Promise<void>;
  spanOnStreet: (bounds: [[number, number], [number, number]]) => void;
  // simulate
  selectRoad: (edgeId: string | null) => void;
  setScrubber: (m: number) => void;
  setDayOfYear: (d: number) => void;
  setPlaying: (p: boolean) => void;
  setSpeed: (s: number) => void;
  // day-stream playback controls
  setDemandModel: (m: DemandModel) => void;
  /** Run the current view: ML day-stream if there are edits, else the predicted baseline day. */
  runSimulate: () => Promise<void>;
  /** Speculatively warm the day-stream for the current edits (non-blocking). */
  prewarm: () => void;
  /** Load the full-coverage GNN-predicted baseline day (no edits) into the day store. */
  loadBaselineDay: () => Promise<void>;
  recenter: () => void;
  flyToLocation: (lng: number, lat: number, zoom?: number) => void;
  fitToBounds: (bounds: [[number, number], [number, number]]) => void;
  /** Move the camera to a resolved search hit — the shared omnibox/copilot path. */
  flyToHit: (hit: SearchHit) => Promise<void>;
  /** Resolve free text (road, else place) via the omnibox resolver and fly to it.
   *  Returns true if something was found. Used by the copilot's focus fallback. */
  focusQuery: (query: string) => Promise<boolean>;
  /** Rebuild the baseline demand at the current scrubber time + selected date so the
   *  simulation reflects that time-of-day (commute direction + rush factor). Heavy. */
  retimeBaseline: () => Promise<void>;
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

/**
 * Guardrail warnings for closures placed on restricted roads — the "Completely
 * Prohibited" provincial highways (MTO) and the City of Toronto municipal
 * expressways. The restricted flag rides on each segment from `/edges` (derived
 * from the Toronto Centreline). One warning per distinct restricted road.
 */
function restrictedClosureWarnings(objects: SceneObject[], graph: RoadGraph | null): Warning[] {
  if (!graph) return [];
  const seen = new Map<string, Warning>();
  for (const o of objects) {
    if (!o.visible || o.type !== "closure") continue;
    for (const edgeId of o.edgeIds ?? []) {
      const seg = graph.byId.get(edgeId);
      const r = seg?.restricted;
      if (!r) continue;
      const label = r.label || seg?.road_name || o.roadName || "this expressway";
      const key = `${r.category}:${label}`;
      if (seen.has(key)) continue;
      const isMto = r.category === "mto_prohibited";
      seen.set(key, {
        id: `restricted:${key}`,
        kind: "restricted",
        severity: "danger",
        title: `Closure not permitted · ${label}`,
        detail: r.reason,
        ref: isMto ? "MTO · Completely Prohibited highway" : "City of Toronto · Municipal expressway",
      });
    }
  }
  return [...seen.values()];
}

/** Restricted-road guardrails first, then the live pressure risk bands. */
function composeWarnings(objects: SceneObject[], graph: RoadGraph | null): Warning[] {
  return [...restrictedClosureWarnings(objects, graph), ...buildWarnings()];
}

/** Push per-edge records into the tick store and trigger a deck.gl recolor. */
function paintRecords(set: SetFn, records: [number, number, number, number, number][]) {
  writeRecords(records);
  set((s) => ({
    pressureSeq: s.pressureSeq + 1,
    warnings: composeWarnings(s.objects, s.graph),
  }));
}

/** Repaint the twin from a scenario's last run (fetch records → paint). */
async function paintScenario(set: SetFn, sid: string) {
  const rec = await api.scenarioRecords(sid);
  paintRecords(set, rec.records);
}

/** Poll /healthz until the backend's compare baseline is warm, then ungate the
 *  copilot. The full baseline is ~minutes on the 81k graph; this hides that
 *  behind a "warming up" state instead of a hung first request. */
function pollBaselineReady(set: SetFn) {
  let tries = 0;
  const tick = async () => {
    try {
      const h = await api.health();
      if (h.baseline_ready) return set({ copilotReady: true });
    } catch {
      /* ignore — retry */
    }
    if (++tries < 120) setTimeout(tick, 3000); // give up after ~6 min
  };
  void tick();
}

/** Map-frame bounds [[minLng,minLat],[maxLng,maxLat]] for a copilot ViewDirective.
 *  Prefers the resolved edge_ids; falls back to matching the road_name across the
 *  graph. Returns null when nothing resolves (the camera just stays put). */
function bboxForView(
  graph: RoadGraph | null,
  view: ViewDirective,
): [[number, number], [number, number]] | null {
  if (!graph) return null;
  // Frame the exact backend-resolved segments. (Name-only / place views never
  // reach here — applyView routes those through the shared omnibox resolver.)
  const ids = view.edge_ids ?? [];
  if (!ids.length) return null;
  let minLng = Infinity,
    minLat = Infinity,
    maxLng = -Infinity,
    maxLat = -Infinity,
    n = 0;
  for (const id of ids) {
    const seg = graph.byId.get(id);
    if (!seg?.geometry) continue;
    for (const [lat, lng] of seg.geometry) {
      minLng = Math.min(minLng, lng);
      maxLng = Math.max(maxLng, lng);
      minLat = Math.min(minLat, lat);
      maxLat = Math.max(maxLat, lat);
      n++;
    }
  }
  if (!n) return null;
  return [
    [minLng, minLat],
    [maxLng, maxLat],
  ];
}

/** Build an Edit-mode closure scene object from copilot-proposed edge_ids, so a
 *  copilot closure shows identically to a manual one (marker, inspector, sealed
 *  edges) and applies through the same applyEdits → /scenarios + /run path. */
function closureObjectFromEdges(graph: RoadGraph | null, edgeIds: string[], n: number): SceneObject {
  const segs = edgeIds.map((id) => graph?.byId.get(id)).filter((s): s is Segment => !!s);
  const roadName = segs[0]?.road_name;
  let sLat = 0;
  let sLng = 0;
  let npts = 0;
  for (const sg of segs) for (const [la, ln] of sg.geometry) {
    sLat += la;
    sLng += ln;
    npts += 1;
  }
  const coord: [number, number] = npts ? [sLng / npts, sLat / npts] : [-79.4, 43.65];
  return {
    id: `obj-copilot-${n}`,
    type: "closure",
    name: `Closure${roadName ? " · " + roadName : ""}`,
    visible: true,
    n,
    coord,
    roadName,
    edgeIds,
  };
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
      // Demand surge (relief = negative) → OD injection at the placed point.
      const signed = o.surge.kind === "relief" ? -Math.abs(o.surge.amount) : Math.abs(o.surge.amount);
      out.push({
        op: "demand_surge",
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
// open a new one. The backend fills the day (current hour first) and each hour's
// frame repaints the map only when it's the visible hour. Frames from a stale
// epoch are dropped in the tick store and ignored here.
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
    // is wedged. Generous margin — a cold first request pays a one-time model load
    // before the first hour; once any hour lands this is moot (progressive).
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
 * in a single pass). Always the GNN regardless of the model toggle (the toggle is
 * the EDIT demand model). Placing an edit switches to the equilibrium day-stream. */
async function loadBaselineDayInternal(set: SetFn, get: GetFn): Promise<void> {
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

export const useAppStore = create<AppState>((set, get) => ({
  theme: "light",
  density: "comfortable",
  intensity: 1.0,
  view: "sim",
  showLeft: true,
  showRight: true,
  showBottom: true,
  loaded: false,
  loading: false,
  error: null,
  recomputing: false,
  recomputeStep: 0,
  recomputeTitle: "",
  stagedPlan: null,
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
  copilotSessions: INITIAL_SESSIONS.sessions,
  copilotSessionSeq: INITIAL_SESSIONS.seq,
  deepMode: false,
  copilotReady: false,
  copilotThinking: false,
  copilotPendingMode: null,
  copilotChips: [...COPILOT_CHIPS], // replaced by graph-grounded chips once loaded
  copilotLatency: null,
  scrubberMinute: TIMELINE.defaultMin,
  dayOfYear: DEFAULT_DAY_OF_YEAR,
  playing: false,
  speed: 1,
  demandModel: "xgboost",
  modelActual: "",
  simStale: false,
  dayFill: { ready: 0, total: 24 },
  telemetry: { ...IDLE },
  recenterNonce: 0,
  flyTarget: null,
  flyNonce: 0,
  flyPin: null,
  fitTarget: null,
  fitNonce: 0,
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
    })),

  setView: (v) => {
    if (v === get().view) return;
    set({
      view: v,
      showBottom: v === "sim",
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
      try {
        const base = await api.demoRun("baseline");
        paintRecords(set, base.records);
        set({ status: { state: "nominal", label: "Baseline · nominal" } });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        set({
          error: `Toronto graph loaded, but the baseline simulation failed (${msg}).`,
          status: { state: "blocked", label: "Graph loaded · baseline unavailable" },
        });
      }
      // Populate the 24-hour predicted day so the timeline becomes a true playback
      // axis (scrub/▶play select precomputed hours — no recompute). Best-effort: the
      // single-frame demo baseline above already painted, so a failure here is benign.
      void get().loadBaselineDay();
      void get().loadSavedSims();
      // Graph-grounded suggestion chips (real road names); static fallback on failure.
      void api
        .copilotSuggestions()
        .then((s) => {
          if (s.prompts?.length) set({ copilotChips: s.prompts });
        })
        .catch(() => {});
      pollBaselineReady(set); // ungate the copilot once the compare baseline is warm
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
        paintRecords(set, rec.records);
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

  toggleDeep: () => set((s) => ({ deepMode: !s.deepMode })),

  copilotStop: () => {
    copilotAbort?.abort();
    copilotAbort = null;
    set((s) => {
      const log = s.copilotLog.slice();
      const last = log[log.length - 1];
      if (last && last.role === "bot" && last.streaming) {
        log[log.length - 1] = { ...last, streaming: false, aborted: true };
      }
      return { copilotLog: log, copilotThinking: false, copilotPendingMode: null };
    });
  },

  // Archive the live chat (if any messages) into sessions, then clear the log.
  copilotNewChat: () =>
    set((s) => {
      if (s.copilotLog.length === 0) return {};
      const seq = s.copilotSessionSeq + 1;
      const session: CopilotSession = {
        id: `chat-${seq}`,
        title: sessionTitle(s.copilotLog),
        log: s.copilotLog,
      };
      const sessions = [session, ...s.copilotSessions];
      persistSessions(sessions, seq);
      return { copilotSessions: sessions, copilotSessionSeq: seq, copilotLog: [] };
    }),

  // Swap to a past session's log — archiving the live one first (so nothing is lost).
  copilotLoadSession: (id) =>
    set((s) => {
      const target = s.copilotSessions.find((x) => x.id === id);
      if (!target) return {};
      let sessions = s.copilotSessions;
      let seq = s.copilotSessionSeq;
      if (s.copilotLog.length > 0) {
        seq = seq + 1;
        const archived: CopilotSession = {
          id: `chat-${seq}`,
          title: sessionTitle(s.copilotLog),
          log: s.copilotLog,
        };
        sessions = [archived, ...sessions];
      }
      // Pull the target out of the (possibly newly-extended) list and load it live.
      sessions = sessions.filter((x) => x.id !== id);
      persistSessions(sessions, seq);
      return { copilotSessions: sessions, copilotSessionSeq: seq, copilotLog: target.log };
    }),

  copilotAsk: async (text) => {
    // Single classifier routes (replaces the old isQuestion regex). Deep mode is a
    // manual override that forces the agent loop; otherwise /copilot/route runs one
    // intent classification and tells us the surface (and, for plan intents, returns
    // the dispatched plan inline so we don't make a second call).
    set((s) => ({
      copilotLog: [...s.copilotLog, { role: "user", text }],
      copilotThinking: true,
      copilotPendingMode: get().deepMode ? "agent" : null, // deep is known upfront
      stagedPlan: null, // a new ask supersedes any previously staged plan
    }));
    const controller = new AbortController();
    copilotAbort = controller;
    const { signal } = controller;

    const flashBlocked = (detail: string, ref?: string) => {
      set((s) => ({
        status: { state: "blocked", label: "Action blocked · bylaw conflict" },
        warnings: [
          { id: "copilot-bylaw", severity: "danger", title: "Bylaw conflict", detail, ref },
          ...s.warnings.filter((w) => w.id !== "copilot-bylaw"),
        ],
      }));
    };
    // Stage the plan as the single source of truth: capture the bot message it
    // rode on (just pushed → last index), its interventions, and the close_edge
    // targets for the map preview. Both confirm surfaces act on this.
    // Push copilot warnings into the shared RightDock warnings panel (replacing
    // any from a prior copilot turn), so they sit alongside clickops/risk flags.
    type W = { severity?: string; title?: string; detail?: string; ref?: string | null };
    const pushWarnings = (ws?: W[]) => {
      if (!ws?.length) return;
      set((s) => ({
        warnings: [
          ...ws.map((w, k) => ({
            id: `copilot-${k}`,
            severity: (w.severity as "info" | "warn" | "danger") ?? "warn",
            title: w.title ?? "Advisory",
            detail: w.detail ?? "",
            ref: w.ref ?? undefined,
          })),
          ...s.warnings.filter((x) => !x.id.startsWith("copilot-")),
        ],
      }));
    };
    const afterPlan = (interventions: Intervention[] | undefined, blocked: boolean, detail = "", ref?: string) => {
      if (blocked) return flashBlocked(detail, ref);
      if (!interventions || interventions.length === 0) return;
      const edgeIds = interventions
        .filter((iv) => iv.op === "close_edge" && iv.edge_id)
        .map((iv) => iv.edge_id as string);
      set((s) => ({ stagedPlan: { msgIndex: s.copilotLog.length - 1, interventions, edgeIds } }));
    };
    // Execute a read-only camera move from the copilot (auto-focus on the road it
    // proposes / the place you asked to see). No confirm — it only moves the view.
    // `highlight` = also blue-select the framed road (like the search bar). Off for
    // confirmable plans, where the amber staged preview is the highlight instead.
    const applyView = (view?: ViewDirective | null, highlight = true) => {
      if (!view) return;
      if (view.action === "recenter") return get().recenter();
      if (view.action === "tilt") return get().toggleTilt();
      if (view.action === "time" && view.minute != null) return get().setScrubber(view.minute);
      if (view.action === "fly" && view.lng != null && view.lat != null)
        return get().flyToLocation(view.lng, view.lat, view.zoom ?? undefined);
      const ids = view.edge_ids ?? [];
      if (ids.length) {
        const bbox = bboxForView(get().graph, view);
        if (bbox) get().fitToBounds(bbox);
        if (highlight) get().selectRoad(ids[0]); // highlights the whole road by name
        return;
      }
      // No backend edge_ids → resolve through the SAME omnibox chain (local roads,
      // then Mapbox places): a street frames + highlights, a place flies + pins. So
      // the copilot can show anything the search bar can ("High Park", "CN Tower").
      if (view.road_name) void get().focusQuery(view.road_name);
    };
    const renderPlan = (resp: CopilotResponse) => {
      const confirmable = resp.requires_user_confirmation && (resp.interventions?.length ?? 0) > 0;
      set((s) => ({
        copilotLog: [
          ...s.copilotLog,
          {
            role: "bot",
            text: resp.rationale,
            citations: resp.citations,
            blocked: resp.blocked,
            interventions: confirmable ? resp.interventions : undefined,
            warnings: resp.warnings,
            mode: "plan",
          },
        ],
        copilotLatency: { ms: Math.round(performance.now() - t0), mode: "plan" },
      }));
      applyView(resp.view, !confirmable); // amber staged preview owns the highlight for plans
      pushWarnings(resp.warnings);
      afterPlan(
        confirmable ? resp.interventions : undefined,
        resp.blocked,
        resp.rationale,
        resp.citations?.[0]?.ref,
      );
    };
    // After each reply lands, refresh the suggestion chips to reflect this
    // exchange. Degrade gracefully: on error/404, keep the existing chips.
    const refreshFollowups = async (reply: string, intent: string) => {
      try {
        const { prompts } = await api.copilotFollowups(text, reply, intent, signal);
        if (prompts?.length) set({ copilotChips: prompts });
      } catch {
        /* keep the existing graph-grounded copilotChips */
      }
    };
    const t0 = performance.now();

    try {
      // Deep override → agent; else classify once via /route.
      let mode: CopilotMode = "agent";
      let intent = "";
      let routedPlan: CopilotResponse | undefined;
      if (!get().deepMode) {
        // Recent turns (excluding the just-pushed current message) so referential
        // asks ('the worst road', 'that road', 'it') resolve against context.
        const recent = get()
          .copilotLog.slice(-7, -1)
          .filter((m) => m.text)
          .map((m) => `${m.role === "user" ? "You" : "Copilot"}: ${m.text.slice(0, 200)}`)
          .join("\n");
        const routed = await api.copilotRoute(text, recent, signal);
        mode = routed.mode;
        intent = routed.intent ?? "";
        routedPlan = routed.result;
      }
      set({ copilotPendingMode: mode }); // now the single loader can label itself

      if (mode === "agent") {
        const res = await api.copilotAgent(text, signal);
        const hasPlan = res.requires_user_confirmation && res.interventions.length > 0;
        set((s) => ({
          copilotLog: [
            ...s.copilotLog,
            {
              role: "bot",
              text: res.answer,
              citations: res.citations,
              blocked: res.blocked,
              agentSteps: res.steps,
              interventions: hasPlan ? res.interventions : undefined,
              warnings: res.warnings,
              mode: "agent",
            },
          ],
          copilotLatency: { ms: Math.round(performance.now() - t0), mode: "agent" },
        }));
        pushWarnings(res.warnings);
        afterPlan(
          hasPlan ? res.interventions : undefined,
          res.blocked,
          res.answer,
          res.citations?.[0]?.ref,
        );
        await refreshFollowups(res.answer, intent || "agent");
      } else if (mode === "chat") {
        // Don't push the streaming bubble upfront — keep the single "thinking"
        // loader visible until the first token, then start the reply. This way
        // chat uses the same loader as plan/agent (no separate cursor symbol).
        let first: number | undefined;
        let started = false;
        const patchLast = (fn: (m: CopilotMessage) => CopilotMessage) =>
          set((s) => {
            const log = s.copilotLog.slice();
            const last = log[log.length - 1];
            if (last) log[log.length - 1] = fn(last);
            return { copilotLog: log };
          });
        await copilotStream(
          text,
          (tok) => {
            if (first === undefined) first = Math.round(performance.now() - t0);
            if (!started) {
              started = true;
              set((s) => ({
                copilotLog: [...s.copilotLog, { role: "bot", text: tok, streaming: true, mode: "chat" }],
              }));
            } else {
              patchLast((m) => ({ ...m, text: m.text + tok }));
            }
          },
          (done) => {
            if (started) patchLast((m) => ({ ...m, streaming: false }));
            else
              set((s) => ({
                copilotLog: [...s.copilotLog, { role: "bot", text: "(no response)", mode: "chat" }],
              }));
            set({
              copilotLatency: {
                ms: done.total_ms ?? Math.round(performance.now() - t0),
                firstTokenMs: done.first_token_ms ?? first,
                mode: "chat",
              },
            });
          },
          signal,
        );
        // Chips reflect the completed chat reply (its final accumulated text).
        const last = get().copilotLog[get().copilotLog.length - 1];
        await refreshFollowups(last?.role === "bot" ? last.text : "", intent || "chat");
      } else {
        // plan mode — /route already dispatched the plan; fall back to /plan only
        // if the inline result is somehow missing (defensive).
        const resp = routedPlan ?? (await api.copilotPlan(text, signal));
        renderPlan(resp);
        await refreshFollowups(resp.rationale, intent || "plan");
      }
    } catch (e) {
      // User-initiated Stop (AbortError) is handled in copilotStop — stay quiet.
      if (signal.aborted || (e instanceof DOMException && e.name === "AbortError")) return;
      // Raw detail (e.g. "POST /copilot/plan → 500") goes to the console, never the chat.
      console.error("[copilot] request failed:", e);
      const detail = e instanceof Error ? e.message : String(e);
      const offline = /Failed to fetch|NetworkError|→ 5\d\d/.test(detail);
      const text = offline
        ? "Copilot is offline — the Nemotron model backend isn't reachable. Check the API server and try again."
        : "Copilot couldn't complete that request. Please try again.";
      set((s) => ({ copilotLog: [...s.copilotLog, { role: "bot", text }] }));
    } finally {
      if (copilotAbort === controller) copilotAbort = null;
      set({ copilotThinking: false, copilotPendingMode: null });
    }
  },

  copilotConfirm: async (msgIndex) => {
    const msg = get().copilotLog[msgIndex];
    const interventions = msg?.interventions;
    if (!interventions || !interventions.length || msg.applied) return;

    const markApplied = (text: string, result?: CopilotMessage["result"]) =>
      set((s) => ({
        copilotLog: s.copilotLog
          .map((m, i) => (i === msgIndex ? { ...m, applied: true } : m))
          .concat({ role: "bot", text, result }),
        status: { state: "surge", label: "Plan applied · twin updated" },
        stagedPlan: null, // applied → no longer staged (clears the map preview/banner)
      }));

    set({ status: { state: "recomputing", label: "Applying plan · running sim" } });
    try {
      // All-closure plans → materialize as an Edit scene object and apply through
      // the shared applyEdits path (managed marker + sealed edges + repaint).
      const closeIds = interventions
        .filter((iv) => iv.op === "close_edge" && iv.edge_id)
        .map((iv) => iv.edge_id as string);
      if (closeIds.length === interventions.length) {
        const obj = closureObjectFromEdges(get().graph, closeIds, get().objects.length + 1);
        set((s) => ({ objects: [...s.objects, obj], selectedId: obj.id, activeTool: "select", dirty: true }));
        await get().applyEdits(); // creates scenario → run(blast) → paints map + marker
        const sid = get().scenarioId;
        let result: CopilotMessage["result"];
        if (sid) {
          try {
            const cmp = await api.compareScenario(sid);
            result = {
              summaryDelta: cmp.summary_delta ?? {},
              mostImpacted: (cmp.most_impacted_edges ?? []).map((e) => ({ edge_id: e.edge_id })),
            };
          } catch {
            /* card is best-effort */
          }
        }
        markApplied(`${obj.name} applied — twin recomputed.`, result);
        void get().loadSavedSims(); // register the applied closure in the Simulate rail
        return;
      }

      // Mixed / capacity changes → server-side confirm (create → run → compare → explain).
      const res = await api.copilotConfirm(interventions as Intervention[]);
      await paintScenario(set, res.scenario_id);
      set({ scenarioId: res.scenario_id });
      markApplied(res.explanation, {
        summaryDelta: res.summary_delta,
        mostImpacted: res.most_impacted_edges,
      });
      void get().loadSavedSims(); // make the applied scenario selectable in Sim
    } catch (e) {
      const emsg = e instanceof Error ? e.message : String(e);
      set((s) => ({
        copilotLog: [...s.copilotLog, { role: "bot", text: `Apply failed: ${emsg}` }],
        status: { state: "nominal", label: "Baseline · nominal" },
      }));
    }
  },

  copilotRevert: async (msgIndex) => {
    set({ status: { state: "recomputing", label: "Reverting to baseline…" } });
    try {
      const base = await api.demoRun("baseline");
      paintRecords(set, base.records); // repaint the twin back to baseline
      set((s) => ({
        copilotLog: s.copilotLog.map((m, i) => (i === msgIndex ? { ...m, reverted: true } : m)),
        scenarioId: null,
        status: { state: "nominal", label: "Reverted · baseline" },
      }));
    } catch (e) {
      const emsg = e instanceof Error ? e.message : String(e);
      set((s) => ({
        copilotLog: [...s.copilotLog, { role: "bot", text: `Revert failed: ${emsg}` }],
        status: { state: "nominal", label: "Baseline · nominal" },
      }));
    }
  },

  // Apply the staged plan through the ONE correct path (copilotConfirm on the
  // message that carries it) — not applyEdits-on-objects, which ignored the plan.
  applyPlan: async () => {
    const sp = get().stagedPlan;
    if (!sp) return;
    await get().copilotConfirm(sp.msgIndex);
  },
  discardPlan: () => set({ stagedPlan: null }),

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
      await get().applyEdits();
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
    set((s) => {
      const objects = [...s.objects, obj];
      // Surface the restricted-road guardrail immediately, before the recompute.
      return {
        objects,
        selectedId: obj.id,
        activeTool: "select",
        pendingVertices: [],
        dirty: true,
        warnings: composeWarnings(objects, s.graph),
      };
    });
    await get().applyEdits();
  },

  selectObject: (id) => set({ selectedId: id, activeTool: "select" }),
  deleteObject: (id) =>
    set((s) => {
      const objects = s.objects.filter((o) => o.id !== id);
      return {
        objects,
        selectedId: s.selectedId === id ? null : s.selectedId,
        dirty: true,
        warnings: composeWarnings(objects, s.graph),
      };
    }),
  toggleObjectVis: (id) =>
    set((s) => {
      const objects = s.objects.map((o) => (o.id === id ? { ...o, visible: !o.visible } : o));
      return { objects, dirty: true, warnings: composeWarnings(objects, s.graph) };
    }),
  setSurgeParams: (id, patch) =>
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
    })),
  clearPending: () => set({ pendingVertices: [] }),

  // Search → close the whole named street (every segment, both directions) as one
  // closure, applied through the shared scenario→blast→repaint path.
  closeStreet: async (roadName) => {
    const graph = get().graph;
    if (!graph) return;
    const segs = graph.edges.filter((e) => e.road_name === roadName);
    if (segs.length === 0) return;
    const edgeIds = Array.from(new Set(withReverseTwins(graph, segs).map((e) => e.edge_id)));
    const seq = get().objects.length + 1;
    const obj: SceneObject = { ...closureObjectFromEdges(graph, edgeIds, seq), id: `obj${Date.now()}` };
    set((s) => ({ objects: [...s.objects, obj], selectedId: obj.id, activeTool: "select", dirty: true }));
    await get().applyEdits();
  },

  // Search → frame the street and arm the two-click corridor tool for a precise span.
  spanOnStreet: (bounds) => {
    get().fitToBounds(bounds);
    get().selectTool("closure"); // also clears any pending vertices
  },

  applyEdits: async () => {
    await recomputeAround(set, "Reassigning affected subgraph…", async () => {
      try {
        const interventions = interventionsFromObjects(get().objects);
        let sid = get().scenarioId;
        if (!sid) {
          const created = await api.createScenario({ name: get().currentName, interventions });
          sid = created.id;
          set({ scenarioId: sid });
        } else {
          await api.patchScenario(sid, { interventions });
        }
        await api.run(sid, { recompute: "blast", congestion_model: "bpr" });
        await paintScenario(set, sid);
        set((s) => ({ telemetry: { ...s.telemetry, subEdges: 1284 } }));
      } catch {
        /* keep the placement even if the recompute call fails */
      }
    });
    set({ status: { state: "nominal", label: "Edited · recomputed" } });
    // Also (re)fill the 24-hour day-stream for the new edits so the timeline plays
    // back the edited day; falls back to the predicted baseline when no edits remain.
    if (hasEdits(get())) get().prewarm();
    else void get().loadBaselineDay();
  },

  selectRoad: (edgeId) => set({ selectedRoadId: edgeId }),
  setScrubber: (m) => {
    const next = Math.max(TIMELINE.startMin, Math.min(TIMELINE.endMin, m));
    set({ scrubberMinute: next });
    // Day-stream playback: time is a selection axis — pick the precomputed hour's
    // frame and repaint from the buffer (no network / recompute). When the day
    // store is empty (no day loaded) this is a no-op and the legacy single-frame
    // baseline / retime path stays in control.
    const hour = Math.min(23, Math.floor(next / 60));
    if (setSelectedHour(hour)) set((s) => ({ pressureSeq: s.pressureSeq + 1, warnings: buildWarnings() }));
  },
  setDayOfYear: (d) => {
    set({ dayOfYear: Math.max(1, Math.min(366, Math.round(d))) });
    // Day/month picks a different measured/predicted day → refill the day-stream
    // (re-run the ML day if editing, else reload the predicted baseline day).
    if (hasEdits(get())) startDayCompute(set, get);
    else void get().loadBaselineDay();
  },
  setPlaying: (p) => set({ playing: p }),
  setSpeed: (sp) => set({ speed: sp }),

  setDemandModel: (m) => {
    if (m === get().demandModel) return;
    set({ demandModel: m });
    // The toggle is the EDIT demand model only — the baseline is always the GNN
    // prediction — so re-run the equilibrium day-stream only when there are edits.
    if (hasEdits(get())) startDayCompute(set, get);
  },
  runSimulate: async () => {
    if (hasEdits(get())) {
      if (!_dayWs || _dayWs.readyState !== WebSocket.OPEN) startDayCompute(set, get, { immediate: true });
    } else {
      await loadBaselineDayInternal(set, get);
    }
  },
  prewarm: () => {
    if (hasEdits(get())) startDayCompute(set, get); // nothing to prewarm for the baseline
  },
  loadBaselineDay: async () => {
    await loadBaselineDayInternal(set, get);
  },

  recenter: () => set((s) => ({ recenterNonce: s.recenterNonce + 1, flyPin: null })),
  flyToLocation: (lng, lat, zoom) =>
    set((s) => ({ flyTarget: { lng, lat, zoom }, flyNonce: s.flyNonce + 1, flyPin: [lng, lat] })),
  fitToBounds: (bounds) => set((s) => ({ fitTarget: bounds, fitNonce: s.fitNonce + 1, flyPin: null })),
  toggleTilt: () => set((s) => ({ tiltOn: !s.tiltOn })),

  // Shared camera move for a resolved search hit — the SAME logic the omnibox
  // pick uses (street → frame + highlight; place → retrieve coords + fly + pin).
  flyToHit: async (hit) => {
    if (hit.bbox) {
      get().fitToBounds(hit.bbox);
      if (hit.edgeId) get().selectRoad(hit.edgeId);
    } else if (hit.mapboxId) {
      const coord = await retrievePlace(hit.mapboxId, new AbortController().signal);
      if (coord) get().flyToLocation(coord[0], coord[1], 14.5);
    } else {
      get().flyToLocation(hit.coord[0], hit.coord[1], 14.5);
    }
  },
  focusQuery: async (query) => {
    const hit = await resolveQuery(
      roadIndexFor(get().graph),
      query,
      new AbortController().signal,
    ).catch(() => null);
    if (!hit) return false;
    await get().flyToHit(hit);
    return true;
  },

  retimeBaseline: async () => {
    const { scrubberMinute, dayOfYear } = get();
    await recomputeAround(set, "Re-deriving demand for this time…", async () => {
      try {
        const res = await api.retimeBaseline(scrubberMinute, dayOfYear);
        paintRecords(set, res.records); // repaint the map at the new time's baseline
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        set({ error: `Retime failed (${msg}).` });
      }
    });
  },

  reset: async () => {
    set({
      objects: [],
      selectedId: null,
      pendingVertices: [],
      scenarioId: null,
      activeSavedSimId: null,
      currentName: "Untitled simulation",
      dirty: false,
      stagedPlan: null,
      selectedRoadId: null,
      copilotLog: [],
      scrubberMinute: TIMELINE.defaultMin,
      playing: false,
      status: { state: "nominal", label: "Baseline · nominal" },
      telemetry: { ...IDLE },
      recenterNonce: get().recenterNonce + 1,
      flyPin: null,
      simStale: false,
    });
    closeDayStream(); // drop any in-flight edit day-stream before reverting to baseline
    try {
      const base = await api.demoRun("baseline");
      paintRecords(set, base.records);
    } catch {
      /* ignore */
    }
    // Repopulate the predicted day so playback works after a reset.
    void get().loadBaselineDay();
  },
}));
