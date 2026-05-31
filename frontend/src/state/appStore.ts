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
  deepMode: boolean; // 🧠 Deep → force the Agent investigate-loop; else auto-route
  copilotThinking: boolean;
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
  // simulate
  selectRoad: (edgeId: string | null) => void;
  setScrubber: (m: number) => void;
  setDayOfYear: (d: number) => void;
  setPlaying: (p: boolean) => void;
  setSpeed: (s: number) => void;
  recenter: () => void;
  flyToLocation: (lng: number, lat: number, zoom?: number) => void;
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

/** Push per-edge records into the tick store and trigger a deck.gl recolor. */
function paintRecords(set: SetFn, records: [number, number, number, number, number][]) {
  writeRecords(records);
  set((s) => ({ pressureSeq: s.pressureSeq + 1, warnings: buildWarnings() }));
}

/** Repaint the twin from a scenario's last run (fetch records → paint). */
async function paintScenario(set: SetFn, sid: string) {
  const rec = await api.scenarioRecords(sid);
  paintRecords(set, rec.records);
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
  deepMode: false,
  copilotThinking: false,
  copilotLatency: null,
  scrubberMinute: TIMELINE.defaultMin,
  dayOfYear: DEFAULT_DAY_OF_YEAR,
  playing: false,
  speed: 1,
  telemetry: { ...IDLE },
  recenterNonce: 0,
  flyTarget: null,
  flyNonce: 0,
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
      return { copilotLog: log, copilotThinking: false };
    });
  },

  copilotAsk: async (text) => {
    // Auto-route: Deep → agent; a question → chat (stream); else → plan (which
    // internally resolves close/segment/congestion commands or makes a plan).
    const isQuestion =
      /\?\s*$/.test(text) ||
      /^(why|what|how|when|where|who|which|is|are|does|do|can|could|should|tell|explain)\b/i.test(text.trim());
    const mode: CopilotMode = get().deepMode ? "agent" : isQuestion ? "chat" : "plan";
    set((s) => ({ copilotLog: [...s.copilotLog, { role: "user", text }], copilotThinking: true }));
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
    const afterPlan = (hasPlan: boolean, blocked: boolean, detail = "", ref?: string) => {
      if (blocked) return flashBlocked(detail, ref);
      if (hasPlan) set({ planStaged: true });
    };
    const t0 = performance.now();

    try {
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
        afterPlan(hasPlan, res.blocked, res.answer, res.citations?.[0]?.ref);
      } else if (mode === "chat") {
        set((s) => ({ copilotLog: [...s.copilotLog, { role: "bot", text: "", streaming: true, mode: "chat" }] }));
        let first: number | undefined;
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
            patchLast((m) => ({ ...m, text: m.text + tok }));
          },
          (done) => {
            patchLast((m) => ({ ...m, streaming: false }));
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
        const resp: CopilotResponse = await api.copilotPlan(text, signal);
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
        afterPlan(confirmable, resp.blocked, resp.rationale, resp.citations?.[0]?.ref);
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
      set({ copilotThinking: false });
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

  recenter: () => set((s) => ({ recenterNonce: s.recenterNonce + 1 })),
  flyToLocation: (lng, lat, zoom) =>
    set((s) => ({ flyTarget: { lng, lat, zoom }, flyNonce: s.flyNonce + 1 })),
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
      paintRecords(set, base.records);
    } catch {
      /* ignore */
    }
  },
}));
