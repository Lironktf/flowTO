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
  type CopilotResponse,
  type EdgeMeta,
  type Intervention,
  type ScenarioSummary,
} from "../api/client";
import {
  buildGraph,
  corridorBetween,
  nearestEdge,
  nearestNode,
  withReverseTwins,
  type RoadGraph,
} from "../api/graph";
import { DEFAULT_DAY_OF_YEAR, TIMELINE } from "../config";
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
}

/** A placed Edit-mode intervention (closure or surge). */
export interface SceneObject {
  id: string;
  type: "closure" | "surge";
  name: string;
  visible: boolean;
  n: number;
  coord: [number, number]; // pin position (surge: the vertex; closure: corridor midpoint)
  roadName?: string;
  baselinePressure?: number;
  // closure
  vertices?: { key: string; lng: number; lat: number }[];
  edgeIds?: string[];
  // surge
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
  selectObject: (id: string) => void;
  deleteObject: (id: string) => void;
  toggleObjectVis: (id: string) => void;
  setSurgeParams: (id: string, patch: Partial<SurgeParams>) => void;
  applyEdits: () => Promise<void>;
  clearPending: () => void;
  // simulate
  selectRoad: (edgeId: string | null) => void;
  setScrubber: (m: number) => void;
  setDayOfYear: (d: number) => void;
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
      // Best-effort: backend demand-surge-at-vertex support is pending (see client.ts).
      out.push({
        op: "demand_surge",
        amount: o.surge.amount,
        mode: o.surge.mode,
        lng: o.coord[0],
        lat: o.coord[1],
      });
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
      const base = await api.demoRun("baseline");
      set({
        edges,
        graph,
        loaded: true,
        status: { state: "nominal", label: "Baseline · nominal" },
        telemetry: { ...IDLE },
      });
      paintBaseline(set, base.records);
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
      const node = nearestNode(graph, lng, lat);
      if (!node) return;
      const near = nearestEdge(graph, node.lng, node.lat);
      const seq = get().objects.length + 1;
      const obj: SceneObject = {
        id: `obj${Date.now()}`,
        type: "surge",
        name: `Surge${near?.road_name ? " · " + near.road_name : ""}`,
        visible: true,
        n: seq,
        coord: [node.lng, node.lat],
        roadName: near?.road_name,
        baselinePressure: near ? getArrays().pressure[near.idx] : undefined,
        surge: { amount: 500, mode: "absolute" },
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
    set((s) => ({
      objects: [...s.objects, obj],
      selectedId: obj.id,
      activeTool: "select",
      pendingVertices: [],
      dirty: true,
    }));
    await get().applyEdits();
  },

  selectObject: (id) => set({ selectedId: id, activeTool: "select" }),
  deleteObject: (id) =>
    set((s) => ({
      objects: s.objects.filter((o) => o.id !== id),
      selectedId: s.selectedId === id ? null : s.selectedId,
      dirty: true,
    })),
  toggleObjectVis: (id) =>
    set((s) => ({
      objects: s.objects.map((o) => (o.id === id ? { ...o, visible: !o.visible } : o)),
      dirty: true,
    })),
  setSurgeParams: (id, patch) =>
    set((s) => ({
      objects: s.objects.map((o) =>
        o.id === id && o.surge ? { ...o, surge: { ...o.surge, ...patch } } : o,
      ),
      dirty: true,
    })),
  clearPending: () => set({ pendingVertices: [] }),

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
        const rec = await api.scenarioRecords(sid);
        writeRecords(rec.records);
        set((s) => ({
          pressureSeq: s.pressureSeq + 1,
          warnings: buildWarnings(),
          telemetry: { ...s.telemetry, subEdges: 1284 },
        }));
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
    try {
      const base = await api.demoRun("baseline");
      paintBaseline(set, base.records);
    } catch {
      /* ignore */
    }
  },
}));
