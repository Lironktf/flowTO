import { beforeEach, describe, expect, it, vi } from "vitest";

// A plan-mode route response carrying a 2-segment closure (Dubarry Avenue).
const PLAN = {
  tool: "preview_intervention",
  rationale: "Close Dubarry Avenue (2 road segment(s)). Confirm to apply.",
  interventions: [
    { op: "close_edge" as const, edge_id: "a" },
    { op: "close_edge" as const, edge_id: "b" },
  ],
  citations: [],
  warnings: [],
  view: null,
  requires_user_confirmation: true,
  blocked: false,
};

vi.mock("../src/api/client", () => ({
  api: {
    copilotRoute: vi.fn(async () => ({ mode: "plan", intent: "close_road", result: PLAN })),
    copilotFollowups: vi.fn(async () => ({ prompts: [] })),
    copilotAgent: vi.fn(),
  },
  copilotStream: vi.fn(),
}));

import { useAppStore } from "../src/state/appStore";
import { confirmLabel } from "../src/components/CopilotPanel";

describe("Tier 0 — single staged plan + apply path", () => {
  beforeEach(() => {
    useAppStore.setState({ copilotLog: [], deepMode: false, stagedPlan: null, copilotThinking: false });
    vi.clearAllMocks();
  });

  it("0a: a plan-mode ask stages the plan with edgeIds + the bot msgIndex", async () => {
    await useAppStore.getState().copilotAsk("block dubarry ave");
    const sp = useAppStore.getState().stagedPlan;
    expect(sp).toBeTruthy();
    expect(sp!.edgeIds).toEqual(["a", "b"]);
    expect(useAppStore.getState().copilotLog[sp!.msgIndex].role).toBe("bot");
  });

  it("0a: discardPlan clears the staged plan", () => {
    useAppStore.setState({ stagedPlan: { msgIndex: 0, interventions: [], edgeIds: ["a"] } });
    useAppStore.getState().discardPlan();
    expect(useAppStore.getState().stagedPlan).toBeNull();
  });

  it("0a: applyPlan routes through copilotConfirm with the staged msgIndex (one apply path)", async () => {
    const confirmSpy = vi.fn(async () => {});
    useAppStore.setState({
      stagedPlan: { msgIndex: 3, interventions: PLAN.interventions, edgeIds: ["a", "b"] },
      // override the store action to assert wiring without the heavy apply path
      copilotConfirm: confirmSpy as unknown as (i: number) => Promise<void>,
    });
    await useAppStore.getState().applyPlan();
    expect(confirmSpy).toHaveBeenCalledWith(3);
  });
});

describe("Tier 0c — road-centric confirm wording", () => {
  const graph = {
    byId: new Map([
      ["a", { road_name: "Dubarry Avenue" }],
      ["b", { road_name: "Dubarry Avenue" }],
      ["c", { road_name: "King Street West" }],
    ]),
  };

  it("one road's two directional segments → segments, never 'changes'", () => {
    const label = confirmLabel(
      [
        { op: "close_edge", edge_id: "a" },
        { op: "close_edge", edge_id: "b" },
      ],
      graph,
    );
    expect(label).toBe("Confirm & run · 2 segments");
    expect(label).not.toContain("change");
  });

  it("multiple roads → roads + segments", () => {
    const label = confirmLabel(
      [
        { op: "close_edge", edge_id: "a" },
        { op: "close_edge", edge_id: "c" },
      ],
      graph,
    );
    expect(label).toBe("Confirm & run · 2 roads · 2 segments");
  });

  it("singular for one segment", () => {
    expect(confirmLabel([{ op: "close_edge", edge_id: "a" }], graph)).toBe(
      "Confirm & run · 1 segment",
    );
  });
});
