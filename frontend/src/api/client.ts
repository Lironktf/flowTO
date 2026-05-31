/**
 * Typed REST client for the live P06/P07/P12 backend. All traffic data is real
 * engine output — the frontend renders the actual Toronto graph (`/edges`)
 * colored by pressures from `/demo/run`, with before/after from the run
 * summaries and copilot answers from `/copilot/plan`. The binary WS tick stream
 * (`connectStream`) feeds the tick store for live-tick scenarios.
 */
import { ingestFrame } from "../state/tickStore";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

export interface EdgeMeta {
  idx: number;
  edge_id: string;
  geometry: [number, number][] | null; // [[lat, lng], ...] (Liron's stored form)
  road_name?: string;
  road_class?: string;
}

// A tick record: [edge_idx, load, speed, pressure, closure].
export type Record5 = [number, number, number, number, number];

export interface DemoRun {
  scenario: string;
  summary: Record<string, number>;
  headline_metric: number;
  exhibition_pressure: number;
  records: Record5[];
}

/**
 * Graph-mutation ops. The first six mirror the backend
 * (`src/torontosim/graph/mutations.py`). `demand_surge` is defined here for the
 * Edit view's surge tool; backend support is still pending (see HANDOFF), so
 * runs may currently ignore it.
 */
export type InterventionOp =
  | "close_edge"
  | "reopen_edge"
  | "remove_edge"
  | "change_capacity"
  | "close_node"
  | "add_edge"
  | "demand_surge";

export interface Intervention {
  op: InterventionOp;
  edge_id?: string;
  node_id?: number;
  multiplier?: number;
  // add_edge
  from_node?: number;
  to_node?: number;
  road_name?: string;
  speed_kmh?: number;
  lanes?: number;
  capacity?: number;
  // demand_surge (frontend-defined; backend support pending)
  amount?: number;
  mode?: "absolute" | "relative";
  lat?: number;
  lng?: number;
}

export interface CopilotResponse {
  tool: string;
  rationale: string;
  interventions: Intervention[];
  citations: { ref: string; note: string }[];
  requires_user_confirmation: boolean;
  blocked: boolean;
  retrieved_policy?: { doc_id: string; title: string; source: string }[];
}

export interface CopilotConfirmResult {
  scenario_id: string;
  summary: Record<string, number>;
  summary_delta: Record<string, number>;
  most_impacted_edges: { edge_id: string; road_name?: string | null; [k: string]: unknown }[];
  explanation: string;
}

export interface AgentStepLog {
  tool: string;
  thought?: string;
  observation: unknown;
}

export interface CopilotAgentResult {
  answer: string;
  interventions: Intervention[];
  citations: { ref: string; note: string }[];
  steps: AgentStepLog[];
  requires_user_confirmation: boolean;
  blocked: boolean;
}

export interface StreamDone {
  first_token_ms: number | null;
  total_ms: number | null;
  backend?: string;
  error?: string;
}

export interface ScenarioSummary {
  id: string;
  name?: string;
  interventions?: Intervention[];
  [k: string]: unknown;
}

export interface CompareResult {
  summary_delta?: Record<string, number>;
  most_impacted_edges?: { edge_id: string; delta: number }[];
  warnings?: { ref?: string; note: string; severity?: string }[];
  [k: string]: unknown;
}

async function jget<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`GET ${path} → ${r.status}`);
  return r.json() as Promise<T>;
}

async function jpost<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok) throw new Error(`POST ${path} → ${r.status}`);
  return r.json() as Promise<T>;
}

async function jpatch<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`PATCH ${path} → ${r.status}`);
  return r.json() as Promise<T>;
}

async function jdelete<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`DELETE ${path} → ${r.status}`);
  return (r.status === 204 ? (undefined as T) : ((await r.json()) as T));
}

export const api = {
  health: () => jget<{ status: string; edges: number }>("/healthz"),
  edges: () => jget<{ edges: EdgeMeta[] }>("/edges"),
  demoRun: (scenario: string) => jget<DemoRun>(`/demo/run?scenario=${scenario}`),
  copilotPlan: (prompt: string, signal?: AbortSignal) =>
    jpost<CopilotResponse>("/copilot/plan", { prompt }, signal),
  copilotAgent: (prompt: string, signal?: AbortSignal) =>
    jpost<CopilotAgentResult>("/copilot/agent", { prompt }, signal),
  copilotConfirm: (interventions: Intervention[], name = "Copilot scenario") =>
    jpost<CopilotConfirmResult>("/copilot/confirm", { interventions, name }),
  // Edit-mode scenario flow (real engine, blast-radius recompute).
  createScenario: (payload: unknown) => jpost<{ id: string }>("/scenarios", payload),
  patchScenario: (id: string, payload: unknown) => jpatch<unknown>(`/scenarios/${id}`, payload),
  run: (id: string, req: unknown) => jpost<unknown>(`/scenarios/${id}/run`, req),
  scenarioRecords: (id: string) =>
    jget<{ records: Record5[]; summary: Record<string, number> }>(`/scenarios/${id}/records`),
  transitRoutes: (agencies = "ttc") =>
    jget<{ routes: { route_id: string; mode: string; path: [number, number][] }[] }>(
      `/transit/routes?agencies=${agencies}`,
    ),
  transitTrajectories: (agencies = "ttc") =>
    jget<{ trajectories: { trip_id: string; route_type: number; path: [number, number][]; timestamps: number[] }[] }>(
      `/transit/trajectories?agencies=${agencies}`,
    ),
  // Saved-simulation (scenario) CRUD — backs the Simulation view's left rail.
  listScenarios: () => jget<{ scenarios: ScenarioSummary[] }>("/scenarios"),
  getScenario: (id: string) => jget<ScenarioSummary>(`/scenarios/${id}`),
  deleteScenario: (id: string) => jdelete<void>(`/scenarios/${id}`),
  previewScenario: (id: string, req: unknown) => jpost<unknown>(`/scenarios/${id}/preview`, req),
  compareScenario: (id: string, against = "baseline") =>
    jget<CompareResult>(`/scenarios/${id}/compare?against=${against}`),
};

/**
 * Stream a free-text copilot answer via SSE (`/copilot/stream`). Calls `onToken`
 * as tokens arrive and `onDone` with the latency payload on the final event.
 */
export async function copilotStream(
  prompt: string,
  onToken: (t: string) => void,
  onDone: (d: StreamDone) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch(`${BASE}/copilot/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
    signal,
  });
  if (!r.ok || !r.body) throw new Error(`POST /copilot/stream → ${r.status}`);
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    // SSE events are separated by a blank line.
    let nl: number;
    while ((nl = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, nl);
      buf = buf.slice(nl + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      const evt = JSON.parse(line.slice(6)) as { token?: string; done?: boolean } & StreamDone;
      if (evt.token) onToken(evt.token);
      if (evt.done) onDone(evt);
    }
  }
}

/** Connect the binary tick WebSocket (live-tick scenarios → tick store). */
export function connectStream(scenarioId: string): WebSocket {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${location.host}${BASE}/scenarios/${scenarioId}/stream`;
  const ws = new WebSocket(url);
  ws.binaryType = "arraybuffer";
  ws.onmessage = (ev) => {
    if (ev.data instanceof ArrayBuffer) ingestFrame(ev.data);
  };
  return ws;
}
