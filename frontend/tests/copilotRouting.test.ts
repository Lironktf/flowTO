import { beforeEach, describe, expect, it, vi } from "vitest";

// Mock the API client so we can assert HOW the single-classifier router dispatches.
// /copilot/route is the one entry: it returns the chosen mode (and, for plan
// intents, the dispatched plan inline). The frontend no longer guesses with a regex.
vi.mock("../src/api/client", () => {
  const plan = {
    tool: "answer",
    rationale: "",
    interventions: [],
    citations: [],
    requires_user_confirmation: false,
    blocked: false,
    retrieved_policy: [],
  };
  const agent = {
    answer: "ok",
    interventions: [],
    citations: [],
    steps: [],
    requires_user_confirmation: false,
    blocked: false,
  };
  return {
    api: {
      // Test double for the backend classifier: a trailing-? or why/what/how →
      // chat; everything else → a plan intent with the dispatched plan inline.
      copilotRoute: vi.fn(async (prompt: string) => {
        const chat = /\?\s*$/.test(prompt) || /^(why|what|how)\b/i.test(prompt.trim());
        return chat
          ? { mode: "chat", intent: "chat" }
          : { mode: "plan", intent: "close_road", result: plan };
      }),
      copilotPlan: vi.fn(async () => plan),
      copilotFollowups: vi.fn(async () => ({ prompts: [] })),
      copilotAgent: vi.fn(async () => agent),
      copilotConfirm: vi.fn(),
      scenarioRecords: vi.fn(),
      compareScenario: vi.fn(),
      demoRun: vi.fn(),
      loadSavedSims: vi.fn(),
    },
    copilotStream: vi.fn(async (_p: string, _t: (s: string) => void, onDone: (d: unknown) => void) =>
      onDone({ first_token_ms: 1, total_ms: 2 }),
    ),
  };
});

import { api, copilotStream } from "../src/api/client";
import { useAppStore } from "../src/state/appStore";

describe("copilot single-classifier routing", () => {
  beforeEach(() => {
    useAppStore.setState({ copilotLog: [], deepMode: false, copilotThinking: false });
    vi.clearAllMocks();
  });

  it("a chat-mode classification → Chat (stream), no plan call", async () => {
    await useAppStore.getState().copilotAsk("why is Lake Shore congested?");
    expect(api.copilotRoute).toHaveBeenCalledOnce();
    expect(copilotStream).toHaveBeenCalledOnce();
    expect(api.copilotAgent).not.toHaveBeenCalled();
  });

  it("a plan-mode classification dispatches inline (no second /plan hop)", async () => {
    await useAppStore.getState().copilotAsk("reduce capacity on King Street");
    expect(api.copilotRoute).toHaveBeenCalledOnce();
    expect(copilotStream).not.toHaveBeenCalled();
    // The plan rode inline on the route response — no separate /copilot/plan call.
    expect(api.copilotPlan).not.toHaveBeenCalled();
    const bot = useAppStore.getState().copilotLog.find((m) => m.role === "bot");
    expect(bot?.mode).toBe("plan");
  });

  it("Deep on → Agent, bypassing the classifier", async () => {
    useAppStore.setState({ deepMode: true });
    await useAppStore.getState().copilotAsk("why is Lake Shore congested?");
    expect(api.copilotAgent).toHaveBeenCalledOnce();
    expect(api.copilotRoute).not.toHaveBeenCalled();
    expect(copilotStream).not.toHaveBeenCalled();
  });

  it("toggleDeep flips the flag", () => {
    expect(useAppStore.getState().deepMode).toBe(false);
    useAppStore.getState().toggleDeep();
    expect(useAppStore.getState().deepMode).toBe(true);
  });

  it("records the resolved mode on the bot reply (badge)", async () => {
    await useAppStore.getState().copilotAsk("close King Street");
    const bot = useAppStore.getState().copilotLog.find((m) => m.role === "bot");
    expect(bot?.mode).toBe("plan");
  });
});
