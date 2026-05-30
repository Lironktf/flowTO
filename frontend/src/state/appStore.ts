/**
 * Warm app state (Zustand). Drives the 6-state machine from design/README.md,
 * but every traffic number is **real engine output** from the backend:
 *   loadTwin   → GET /edges (real graph) + /demo/run?scenario=baseline
 *   fireSurge  → /demo/run?scenario=wc_surge
 *   applyPlan  → /demo/run?scenario=wc_fix
 *   copilotSend→ POST /copilot/plan
 * Pressures land in the tick-store typed arrays (out of React); a bumped
 * pressureSeq drives the deck.gl updateTriggers recolor.
 */
import { create } from "zustand";
import { api, type CopilotResponse, type EdgeMeta } from "../api/client";
import { resizeTickStore, writeRecords } from "./tickStore";

export type Phase = "first-run" | "baseline" | "recomputing" | "surge" | "mitigated" | "blocked";
export type NetworkState = "base" | "surge" | "mit";

interface CopilotMessage {
  role: "user" | "bot";
  text: string;
  citations?: { ref: string; note: string }[];
  blocked?: boolean;
}

interface Telemetry {
  recompute: number; // measured /demo/run wall-clock (ms)
  affected: number;
  llm: number;
  fps: number;
}

const RECOMPUTE_STEPS = ["Demand model", "Trip assignment", "Edge pressure", "Bylaw check", "Render"];

interface AppState {
  theme: "light" | "dark";
  intensity: number;
  tilt: number;
  phase: Phase;
  networkState: NetworkState;
  recomputing: boolean;
  recomputeStep: number;
  blocked: boolean;
  loading: boolean;
  error: string | null;

  edges: EdgeMeta[];
  pressureSeq: number; // bump → deck recolor
  summaries: Partial<Record<NetworkState, Record<string, number>>>;

  showTransit: boolean;
  selectedEdges: Set<string>;
  scrubberMinute: number;
  copilotLog: CopilotMessage[];
  telemetry: Telemetry;

  setTheme: (t: "light" | "dark") => void;
  setIntensity: (n: number) => void;
  toggleTransit: () => void;
  selectEdge: (id: string, additive?: boolean) => void;
  setScrubber: (m: number) => void;
  loadTwin: () => Promise<void>;
  fireSurge: () => Promise<void>;
  applyPlan: () => Promise<void>;
  copilotSend: (text: string) => Promise<void>;
  reset: () => Promise<void>;
}

const IDLE: Telemetry = { recompute: 0, affected: 0, llm: 0, fps: 60 };

type Run = { records: number[][]; summary: Record<string, number> };

function applyRun(
  set: (partial: Partial<AppState> | ((s: AppState) => Partial<AppState>)) => void,
  state: NetworkState,
  run: Run,
) {
  writeRecords(run.records as [number, number, number, number, number][]);
  set((s: AppState) => ({
    networkState: state,
    pressureSeq: s.pressureSeq + 1,
    summaries: { ...s.summaries, [state]: run.summary },
  }));
}

async function recomputeAround(
  set: (partial: Partial<AppState> | ((s: AppState) => Partial<AppState>)) => void,
  fn: () => Promise<void>,
) {
  set({ recomputing: true, recomputeStep: 0 });
  const start = performance.now();
  const stepper = setInterval(
    () =>
      set((s: AppState) => ({
        recomputeStep: Math.min(s.recomputeStep + 1, RECOMPUTE_STEPS.length - 1),
      })),
    260,
  );
  try {
    await fn();
  } finally {
    clearInterval(stepper);
    const ms = Math.round(performance.now() - start);
    set((s: AppState) => ({
      recomputing: false,
      recomputeStep: RECOMPUTE_STEPS.length,
      telemetry: { ...s.telemetry, recompute: ms, fps: 60 },
    }));
  }
}

export const useAppStore = create<AppState>((set, get) => ({
  theme: "light",
  intensity: 1.0,
  tilt: 52,
  phase: "first-run",
  networkState: "base",
  recomputing: false,
  recomputeStep: 0,
  blocked: false,
  loading: false,
  error: null,
  edges: [],
  pressureSeq: 0,
  summaries: {},
  showTransit: true,
  selectedEdges: new Set<string>(),
  scrubberMinute: 14 * 60,
  copilotLog: [],
  telemetry: { ...IDLE },

  setTheme: (t) => {
    document.documentElement.setAttribute("data-theme", t);
    set({ theme: t });
  },
  setIntensity: (n) => set({ intensity: n }),
  toggleTransit: () => set((s) => ({ showTransit: !s.showTransit })),
  selectEdge: (id, additive = false) =>
    set((s) => {
      const next = new Set(additive ? s.selectedEdges : []);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return { selectedEdges: next };
    }),
  setScrubber: (m) => {
    set({ scrubberMinute: m });
    const s = get();
    if (m >= 17 * 60 + 5 && s.phase === "baseline" && !s.recomputing) {
      void s.fireSurge();
    }
  },

  loadTwin: async () => {
    set({ loading: true, error: null });
    try {
      const { edges } = await api.edges();
      resizeTickStore(edges.length);
      set({ edges });
      const run = await api.demoRun("baseline");
      applyRun(set, "base", run);
      set({ phase: "baseline", networkState: "base", telemetry: { ...IDLE } });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: `Could not reach the API (${msg}). Start scripts/run_api.sh.` });
    } finally {
      set({ loading: false });
    }
  },

  fireSurge: async () => {
    set({ phase: "recomputing" });
    await recomputeAround(set, async () => {
      applyRun(set, "surge", await api.demoRun("wc_surge"));
    });
    set({ phase: "surge" });
  },

  applyPlan: async () => {
    set({ phase: "recomputing" });
    await recomputeAround(set, async () => {
      applyRun(set, "mit", await api.demoRun("wc_fix"));
    });
    set({ phase: "mitigated" });
  },

  copilotSend: async (text) => {
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
      set({ phase: "blocked", blocked: true });
    } else {
      const s = get();
      if (s.networkState === "base" && !s.recomputing) await s.fireSurge();
    }
  },

  reset: async () => {
    set({
      phase: "baseline",
      blocked: false,
      selectedEdges: new Set<string>(),
      copilotLog: [],
      scrubberMinute: 14 * 60,
      telemetry: { ...IDLE },
    });
    applyRun(set, "base", await api.demoRun("baseline"));
  },
}));

export { RECOMPUTE_STEPS };
