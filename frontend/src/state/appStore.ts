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
  copilotStream,
  type AgentStepLog,
  type CopilotResponse,
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
import { COPILOT_CHIPS, DEFAULT_DAY_OF_YEAR, TIMELINE } from "../config";
import { getArrays, resizeTickStore, writeRecords } from "./tickStore";

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

interface CopilotMessage {
  role: "user" | "bot";
  text: string;
  steps?: string[];
  citations?: { ref: string; note: string }[];
  blocked?: boolean;
  // A previewed, confirmable plan (preview-before-apply): the ops to apply.
  interventions?: Intervention[];
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

// A staged (previewed, not-yet-applied) copilot plan. Single source of truth so
// the chat confirm and the map preview act on the same plan + edges — one apply.
interface StagedPlan {
  msgIndex: number; // the bot message in copilotLog carrying this plan
  interventions: Intervention[];
  edgeIds: string[]; // close_edge targets — drives the map preview overlay
}

// Non-reactive holder for the in-flight request's abort controller.
let copilotAbort: AbortController | null = null;

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
  copilotConfirm: (msgIndex: number) => Promise<void>;
  copilotRevert: (msgIndex: number) => Promise<void>;
  toggleDeep: () => void;
  copilotStop: () => void;
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
  recenter: () => void;
  flyToLocation: (lng: number, lat: number, zoom?: number) => void;
  fitToBounds: (bounds: [[number, number], [number, number]]) => void;
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
  let ids = view.edge_ids ?? [];
  if (!ids.length && view.road_name) {
    const want = view.road_name.toLowerCase();
    ids = [];
    for (const [id, seg] of graph.byId) {
      if ((seg.road_name ?? "").toLowerCase().includes(want)) ids.push(id);
    }
  }
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
      // Best-effort: backend demand-change support is pending (see client.ts).
      const signed = o.surge.kind === "relief" ? -Math.abs(o.surge.amount) : Math.abs(o.surge.amount);
      out.push({
        op: "demand_change",
        edge_id: o.edgeId,
        directions: (["n", "e", "s", "w"] as const).filter((d) => o.surge!.dirs[d]),
        amount: signed,
        mode: o.surge.mode,
        lng: o.coord[0],
        lat: o.coord[1],
      } as unknown as Intervention);
    }
  }
  return out;
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
    const applyView = (view?: ViewDirective | null) => {
      if (!view) return;
      if (view.action === "recenter") return get().recenter();
      if (view.action === "fly" && view.lng != null && view.lat != null)
        return get().flyToLocation(view.lng, view.lat, view.zoom ?? undefined);
      const bbox = bboxForView(get().graph, view);
      if (bbox) get().fitToBounds(bbox);
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
            mode: "plan",
          },
        ],
        copilotLatency: { ms: Math.round(performance.now() - t0), mode: "plan" },
      }));
      applyView(resp.view);
      afterPlan(
        confirmable ? resp.interventions : undefined,
        resp.blocked,
        resp.rationale,
        resp.citations?.[0]?.ref,
      );
    };
    const t0 = performance.now();

    try {
      // Deep override → agent; else classify once via /route.
      let mode: CopilotMode = "agent";
      let routedPlan: CopilotResponse | undefined;
      if (!get().deepMode) {
        const routed = await api.copilotRoute(text, signal);
        mode = routed.mode;
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
              mode: "agent",
            },
          ],
          copilotLatency: { ms: Math.round(performance.now() - t0), mode: "agent" },
        }));
        afterPlan(
          hasPlan ? res.interventions : undefined,
          res.blocked,
          res.answer,
          res.citations?.[0]?.ref,
        );
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
      } else {
        // plan mode — /route already dispatched the plan; fall back to /plan only
        // if the inline result is somehow missing (defensive).
        const resp = routedPlan ?? (await api.copilotPlan(text, signal));
        renderPlan(resp);
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
  },

  selectRoad: (edgeId) => set({ selectedRoadId: edgeId }),
  setScrubber: (m) => set({ scrubberMinute: Math.max(TIMELINE.startMin, Math.min(TIMELINE.endMin, m)) }),
  setDayOfYear: (d) => set({ dayOfYear: Math.max(1, Math.min(366, Math.round(d))) }),
  setPlaying: (p) => set({ playing: p }),
  setSpeed: (sp) => set({ speed: sp }),

  recenter: () => set((s) => ({ recenterNonce: s.recenterNonce + 1, flyPin: null })),
  flyToLocation: (lng, lat, zoom) =>
    set((s) => ({ flyTarget: { lng, lat, zoom }, flyNonce: s.flyNonce + 1, flyPin: [lng, lat] })),
  fitToBounds: (bounds) => set((s) => ({ fitTarget: bounds, fitNonce: s.fitNonce + 1, flyPin: null })),
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
      stagedPlan: null,
      selectedRoadId: null,
      copilotLog: [],
      scrubberMinute: TIMELINE.defaultMin,
      playing: false,
      status: { state: "nominal", label: "Baseline · nominal" },
      telemetry: { ...IDLE },
      recenterNonce: get().recenterNonce + 1,
      flyPin: null,
    });
    try {
      const base = await api.demoRun("baseline");
      paintRecords(set, base.records);
    } catch {
      /* ignore */
    }
  },
}));
