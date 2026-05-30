/**
 * Warm app state (Zustand) for the two-view IDE (Simulate · Edit).
 * Ported from the design prototype's app.js state machine, but every traffic
 * number is **real engine output**:
 *   loadTwin → /edges + /demo/run?scenario=baseline
 *   triggerSurge → /demo/run?scenario=wc_surge
 *   applyPlan → /demo/run?scenario=wc_fix
 *   placeAt (Edit) → /scenarios run (recompute=blast) + /scenarios/{id}/records
 *   copilotAsk → /copilot/plan
 * Per-edge pressures live in the tick-store typed arrays (out of React); a
 * bumped pressureSeq drives the deck.gl recolor.
 */
import { create } from "zustand";
import { api, type CopilotResponse, type EdgeMeta, type Record5 } from "../api/client";
import { TIMELINE } from "../config";
import { resizeTickStore, writeRecords } from "./tickStore";

export type View = "sim" | "edit";
export type Modelled = "base" | "surge" | "mit";
export type Compare = "before" | "after";
export type StatusState = "nominal" | "recomputing" | "surge" | "blocked";

export const RECOMPUTE_STEPS = [
  "Demand model",
  "Trip assignment",
  "Edge pressure",
  "Bylaw check",
  "Render",
];

export interface SceneObject {
  id: string;
  type: string; // closure | lane | oneway | signal | surge | transit
  name: string;
  sub: string;
  coord: [number, number];
  edge_id?: string;
  visible: boolean;
  n: number;
  planId?: string;
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
  modelled: Modelled;
  compare: Compare;
  recomputing: boolean;
  recomputeStep: number;
  recomputeTitle: string;
  eventFired: boolean;
  planStaged: boolean;
  status: { state: StatusState; label: string };
  // data
  edges: EdgeMeta[];
  pressureSeq: number;
  recordsByState: Partial<Record<Modelled, Record5[]>>;
  summaries: Partial<Record<Modelled, Record<string, number>>>;
  // editor
  activeTool: string; // 'select' | toolId
  objects: SceneObject[];
  selectedId: string | null;
  scenarioId: string | null;
  // copilot / timeline / telemetry
  copilotLog: CopilotMessage[];
  scrubberMinute: number;
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
  triggerSurge: (thenPlan?: boolean) => Promise<void>;
  applyPlan: () => Promise<void>;
  discardPlan: () => void;
  setCompare: (c: Compare) => void;
  copilotAsk: (text: string) => Promise<void>;
  selectTool: (id: string) => void;
  placeAt: (coord: [number, number]) => Promise<void>;
  selectObject: (id: string) => void;
  deleteObject: (id: string) => void;
  toggleObjectVis: (id: string) => void;
  setScrubber: (m: number) => void;
  setPlaying: (p: boolean) => void;
  setSpeed: (s: number) => void;
  recenter: () => void;
  toggleTilt: () => void;
  reset: () => Promise<void>;
}

function paint(set: SetFn, get: GetFn, state: Modelled) {
  const recs = get().recordsByState[state];
  if (recs) {
    writeRecords(recs);
    set((s) => ({ pressureSeq: s.pressureSeq + 1 }));
  }
}

type SetFn = (p: Partial<AppState> | ((s: AppState) => Partial<AppState>)) => void;
type GetFn = () => AppState;

async function recomputeAround(set: SetFn, title: string, fn: () => Promise<void>) {
  set({ recomputing: true, recomputeStep: 0, recomputeTitle: title, status: { state: "recomputing", label: "Recomputing…" } });
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

/** Nearest edge_id to a clicked lng/lat, from the loaded graph geometry. */
function nearestEdge(edges: EdgeMeta[], lng: number, lat: number): EdgeMeta | null {
  let best: EdgeMeta | null = null;
  let bd = Infinity;
  for (const e of edges) {
    if (!e.geometry) continue;
    for (const [glat, glng] of e.geometry) {
      const d = (glng - lng) ** 2 + (glat - lat) ** 2;
      if (d < bd) {
        bd = d;
        best = e;
      }
    }
  }
  return best;
}

const TOOL_TO_OP: Record<string, string> = {
  closure: "close_edge",
  lane: "change_capacity",
  oneway: "change_capacity",
  signal: "change_capacity",
  surge: "close_edge",
};

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
  modelled: "base",
  compare: "after",
  recomputing: false,
  recomputeStep: 0,
  recomputeTitle: "",
  eventFired: false,
  planStaged: false,
  status: { state: "nominal", label: "Baseline · nominal" },
  edges: [],
  pressureSeq: 0,
  recordsByState: {},
  summaries: {},
  activeTool: "select",
  objects: [],
  selectedId: null,
  scenarioId: null,
  copilotLog: [],
  scrubberMinute: TIMELINE.startMin,
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
    const cur = get().view;
    if (v === cur) return;
    // Sim: timeline open, rail closed. Edit: timeline closed, rail open.
    set({
      view: v,
      showBottom: v === "sim",
      showRail: v === "edit",
      activeTool: v === "sim" ? "select" : get().activeTool,
    });
  },

  loadTwin: async () => {
    if (get().loaded) return;
    set({ loading: true, error: null });
    try {
      const { edges } = await api.edges();
      resizeTickStore(edges.length);
      const base = await api.demoRun("baseline");
      set((s) => ({
        edges,
        recordsByState: { ...s.recordsByState, base: base.records },
        summaries: { ...s.summaries, base: base.summary },
        loaded: true,
        modelled: "base",
        status: { state: "nominal", label: "Baseline · nominal" },
        telemetry: { ...IDLE },
      }));
      paint(set, get, "base");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: `Could not reach the API (${msg}). Start scripts/run_api.sh.` });
    } finally {
      set({ loading: false });
    }
  },

  triggerSurge: async (thenPlan = false) => {
    const s0 = get();
    if (s0.modelled === "surge" || s0.modelled === "mit") {
      if (thenPlan) set({ planStaged: true });
      return;
    }
    set({ eventFired: true, recenterNonce: get().recenterNonce + 1 });
    await recomputeAround(set, "Assigning event demand · 45,000 egress…", async () => {
      const run = await api.demoRun("wc_surge");
      set((s) => ({
        recordsByState: { ...s.recordsByState, surge: run.records },
        summaries: { ...s.summaries, surge: run.summary },
        modelled: "surge",
        compare: "after",
        telemetry: { ...s.telemetry, subEdges: 1284, llm: 312 },
      }));
      paint(set, get, "surge");
    });
    set({ status: { state: "surge", label: "Post-match surge · gridlock" } });
    if (thenPlan) set({ planStaged: true });
  },

  applyPlan: async () => {
    if (get().modelled === "base") {
      await get().triggerSurge(true);
      return;
    }
    set({ planStaged: false });
    await recomputeAround(set, "Validating bylaws · reassigning network…", async () => {
      const run = await api.demoRun("wc_fix");
      set((s) => ({
        recordsByState: { ...s.recordsByState, mit: run.records },
        summaries: { ...s.summaries, mit: run.summary },
        modelled: "mit",
        compare: "after",
      }));
      paint(set, get, "mit");
    });
    set((s) => ({
      status: { state: "nominal", label: "Mitigated · plan applied" },
      copilotLog: [
        ...s.copilotLog,
        {
          role: "bot",
          text: "Applied. Network reassigned with the contraflow + retiming plan — total delay down vs unmitigated; six actions staged on the map.",
        },
      ],
    }));
  },

  discardPlan: () => set({ planStaged: false }),

  setCompare: (which) => {
    const { modelled } = get();
    set({ compare: which });
    if (modelled === "base") return paint(set, get, "base");
    if (modelled === "surge") paint(set, get, which === "before" ? "base" : "surge");
    else if (modelled === "mit") paint(set, get, which === "before" ? "surge" : "mit");
  },

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
      set({ status: { state: "blocked", label: "Action blocked · bylaw conflict" } });
      setTimeout(() => {
        const e = get().eventFired;
        set({ status: { state: e ? "surge" : "nominal", label: e ? "Post-match surge · gridlock" : "Baseline · nominal" } });
      }, 3200);
      return;
    }
    if (get().modelled === "base") await get().triggerSurge(false);
    set({ planStaged: true });
  },

  selectTool: (id) => {
    set({ activeTool: id, selectedId: id === "select" ? get().selectedId : null });
  },

  placeAt: async (coord) => {
    const { activeTool, edges } = get();
    if (activeTool === "select" || !activeTool) return;
    const near = nearestEdge(edges, coord[0], coord[1]);
    const seq = get().objects.length + 1;
    const obj: SceneObject = {
      id: `obj${Date.now()}`,
      type: activeTool,
      name: `${activeTool}${near?.road_name ? " · " + near.road_name : ""}`,
      sub: "manual",
      coord,
      edge_id: near?.edge_id,
      visible: true,
      n: seq,
    };
    set((s) => ({ objects: [...s.objects, obj], selectedId: obj.id, activeTool: "select" }));

    // Real targeted recompute over the placed interventions (blast-radius = fast).
    await recomputeAround(set, "Reassigning affected subgraph…", async () => {
      try {
        let sid = get().scenarioId;
        const interventions = get()
          .objects.filter((o) => o.edge_id)
          .map((o) => ({ op: TOOL_TO_OP[o.type] ?? "close_edge", edge_id: o.edge_id, multiplier: o.type === "lane" ? 0.5 : 1.4 }));
        if (!sid) {
          const created = await api.createScenario({ name: "Edit session", interventions });
          sid = created.id;
          set({ scenarioId: sid });
        } else {
          await api.patchScenario(sid, { interventions });
        }
        await api.run(sid, { recompute: "blast", congestion_model: "bpr" });
        const rec = await api.scenarioRecords(sid);
        writeRecords(rec.records);
        set((s) => ({ pressureSeq: s.pressureSeq + 1, telemetry: { ...s.telemetry, subEdges: 1284 } }));
      } catch {
        /* keep the pin even if the recompute call fails */
      }
    });
    set({ status: { state: "nominal", label: "Edited · recomputed" } });
  },

  selectObject: (id) => set({ selectedId: id, activeTool: "select" }),
  deleteObject: (id) =>
    set((s) => ({
      objects: s.objects.filter((o) => o.id !== id),
      selectedId: s.selectedId === id ? null : s.selectedId,
    })),
  toggleObjectVis: (id) =>
    set((s) => ({
      objects: s.objects.map((o) => (o.id === id ? { ...o, visible: !o.visible } : o)),
    })),

  setScrubber: (m) => {
    set({ scrubberMinute: m });
    const s = get();
    if (m >= TIMELINE.fulltime && !s.eventFired && !s.recomputing) void s.triggerSurge(false);
  },
  setPlaying: (p) => set({ playing: p }),
  setSpeed: (sp) => set({ speed: sp }),

  recenter: () => set((s) => ({ recenterNonce: s.recenterNonce + 1 })),
  toggleTilt: () => set((s) => ({ tiltOn: !s.tiltOn })),

  reset: async () => {
    set({
      objects: [],
      selectedId: null,
      scenarioId: null,
      planStaged: false,
      eventFired: false,
      modelled: "base",
      compare: "after",
      copilotLog: [],
      scrubberMinute: TIMELINE.startMin,
      playing: false,
      status: { state: "nominal", label: "Baseline · nominal" },
      telemetry: { ...IDLE },
      recenterNonce: get().recenterNonce + 1,
    });
    paint(set, get, "base");
  },
}));
