/**
 * Warm app state (Zustand) — human-cadence re-renders only (research/06 tier 3).
 * Drives the 6-state machine from design/README.md:
 *   first-run → baseline → recomputing(HERO) → surge → mitigated → blocked.
 */
import { create } from "zustand";
import {
  type CopilotScript,
  type NetworkState,
  copilotBlocked,
  copilotHero,
  perf,
  recomputeSteps,
} from "../data/demo";

export type Phase = "first-run" | "baseline" | "recomputing" | "surge" | "mitigated" | "blocked";

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
  subNodes: number;
  llm: number;
  fps: number;
}

interface AppState {
  // tweakables
  theme: "light" | "dark";
  density: "comfortable" | "compact";
  intensity: number;
  extrude: number;
  tilt: number;
  // machine
  phase: Phase;
  networkState: NetworkState;
  eventFired: boolean;
  recomputing: boolean;
  recomputeStep: number;
  blocked: boolean;
  // scenario / interaction
  activeTool: string | null;
  selectedEdges: Set<string>;
  previewVisible: boolean;
  appliedActions: string[];
  scrubberMinute: number;
  copilotLog: CopilotMessage[];
  telemetry: Telemetry;
  // actions
  setTheme: (t: "light" | "dark") => void;
  setDensity: (d: "comfortable" | "compact") => void;
  setIntensity: (n: number) => void;
  setExtrude: (n: number) => void;
  setTilt: (n: number) => void;
  loadTwin: () => void;
  setScrubber: (m: number) => void;
  selectEdge: (id: string, additive?: boolean) => void;
  clearSelection: () => void;
  setTool: (id: string | null) => void;
  runRecompute: (to: NetworkState, onDone?: () => void) => void;
  fireSurge: () => void;
  showPreview: () => void;
  applyPlan: () => void;
  discardPreview: () => void;
  copilotSend: (text: string) => void;
  reset: () => void;
}

const liveTelemetry: Telemetry = { ...perf.live };
const idleTelemetry: Telemetry = { ...perf.base };

function scriptToMessages(script: CopilotScript): CopilotMessage[] {
  return [
    { role: "user", text: script.user },
    {
      role: "bot",
      text: script.botLead,
      steps: script.steps,
      citations: script.citations,
      blocked: script.blocked,
    },
    { role: "bot", text: script.botTail },
  ];
}

export const useAppStore = create<AppState>((set, get) => ({
  theme: "light",
  density: "comfortable",
  intensity: 1.0,
  extrude: 1.0,
  tilt: 52,
  phase: "first-run",
  networkState: "base",
  eventFired: false,
  recomputing: false,
  recomputeStep: 0,
  blocked: false,
  activeTool: null,
  selectedEdges: new Set<string>(),
  previewVisible: false,
  appliedActions: [],
  scrubberMinute: 14 * 60,
  copilotLog: [],
  telemetry: { ...idleTelemetry },

  setTheme: (t) => {
    document.documentElement.setAttribute("data-theme", t);
    set({ theme: t });
  },
  setDensity: (d) => {
    document.documentElement.setAttribute("data-density", d);
    set({ density: d });
  },
  setIntensity: (n) => set({ intensity: n }),
  setExtrude: (n) => set({ extrude: n }),
  setTilt: (n) => set({ tilt: n }),

  loadTwin: () => set({ phase: "baseline", networkState: "base", telemetry: { ...idleTelemetry } }),
  setScrubber: (m) => {
    set({ scrubberMinute: m });
    // Crossing full-time auto-triggers the surge recompute (design behavior).
    const st = get();
    if (m >= 17 * 60 + 5 && !st.eventFired && st.phase === "baseline") {
      st.fireSurge();
    }
  },
  selectEdge: (id, additive = false) =>
    set((s) => {
      const next = new Set(additive ? s.selectedEdges : []);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return { selectedEdges: next };
    }),
  clearSelection: () => set({ selectedEdges: new Set<string>() }),
  setTool: (id) => set({ activeTool: id }),

  runRecompute: (to, onDone) => {
    set({ recomputing: true, recomputeStep: 0, telemetry: { ...idleTelemetry } });
    const total = recomputeSteps.length;
    let step = 0;
    const tick = () => {
      step += 1;
      const frac = step / total;
      set({
        recomputeStep: step,
        telemetry: {
          recompute: Math.round(liveTelemetry.recompute * frac),
          subEdges: Math.round(liveTelemetry.subEdges * frac),
          subNodes: Math.round(liveTelemetry.subNodes * frac),
          llm: step >= 4 ? liveTelemetry.llm : 0,
          fps: step === 3 ? 57 : 60,
        },
      });
      if (step >= total) {
        set({ recomputing: false, networkState: to, telemetry: { ...liveTelemetry } });
        onDone?.();
      } else {
        setTimeout(tick, 1750 / total);
      }
    };
    setTimeout(tick, 1750 / total);
  },

  fireSurge: () => {
    set({ eventFired: true, phase: "recomputing" });
    get().runRecompute("surge", () => set({ phase: "surge" }));
  },

  showPreview: () => set({ previewVisible: true }),
  applyPlan: () => {
    set({ phase: "recomputing", previewVisible: false });
    get().runRecompute("mit", () =>
      set({ phase: "mitigated", appliedActions: ["a1", "a2", "a3", "a4", "a5", "a6"] }),
    );
  },
  discardPreview: () => set({ previewVisible: false }),

  copilotSend: (text) => {
    const isBlocked = /close lake shore both ways/i.test(text);
    const script = isBlocked ? copilotBlocked : copilotHero;
    set((s) => ({ copilotLog: [...s.copilotLog, ...scriptToMessages(script)] }));
    if (isBlocked) {
      set({ phase: "blocked", blocked: true });
    } else {
      // Hero: model the event if needed, then reveal the preview card.
      const st = get();
      if (!st.eventFired) st.fireSurge();
      set({ previewVisible: true });
    }
  },

  reset: () =>
    set({
      phase: "baseline",
      networkState: "base",
      eventFired: false,
      recomputing: false,
      recomputeStep: 0,
      blocked: false,
      activeTool: null,
      selectedEdges: new Set<string>(),
      previewVisible: false,
      appliedActions: [],
      scrubberMinute: 14 * 60,
      copilotLog: [],
      telemetry: { ...idleTelemetry },
    }),
}));
