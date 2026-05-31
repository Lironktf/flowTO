import { beforeEach, describe, expect, it, vi } from "vitest";

// Mock the API client so we can assert WHICH copilot endpoint Auto mode dispatches to.
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
      copilotPlan: vi.fn(async () => plan),
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

describe("copilot Auto-mode routing", () => {
  beforeEach(() => {
    useAppStore.setState({ copilotLog: [], deepMode: false, copilotThinking: false });
    vi.clearAllMocks();
  });

  it("routes a question → Chat (stream)", async () => {
    await useAppStore.getState().copilotAsk("why is Lake Shore congested?");
    expect(copilotStream).toHaveBeenCalledOnce();
    expect(api.copilotPlan).not.toHaveBeenCalled();
    expect(api.copilotAgent).not.toHaveBeenCalled();
  });

  it("routes an action → Plan", async () => {
    await useAppStore.getState().copilotAsk("reduce capacity on King Street");
    expect(api.copilotPlan).toHaveBeenCalledOnce();
    expect(copilotStream).not.toHaveBeenCalled();
  });

  it("Deep on → Agent regardless of phrasing", async () => {
    useAppStore.setState({ deepMode: true });
    await useAppStore.getState().copilotAsk("why is Lake Shore congested?");
    expect(api.copilotAgent).toHaveBeenCalledOnce();
    expect(copilotStream).not.toHaveBeenCalled();
  });

  it("toggleDeep flips the flag", () => {
    expect(useAppStore.getState().deepMode).toBe(false);
    useAppStore.getState().toggleDeep();
    expect(useAppStore.getState().deepMode).toBe(true);
  });

  it("records the resolved mode on the bot reply (badge)", async () => {
    await useAppStore.getState().copilotAsk("close King Street");
    const log = useAppStore.getState().copilotLog;
    const bot = log.find((m) => m.role === "bot");
    expect(bot?.mode).toBe("plan");
  });
});
