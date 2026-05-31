/**
 * Typed REST client for the live P06/P07/P12 backend. All traffic data is real
 * engine output — the frontend renders the actual Toronto graph (`/edges`)
 * colored by pressures from `/demo/run`, with before/after from the run
 * summaries and copilot answers from `/copilot/plan`. The binary WS tick stream
 * (`connectStream`) feeds the tick store for live-tick scenarios.
 */
import { ingestDayFrame, ingestFrame } from "../state/tickStore";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

/** Closure guardrail: a restricted road may not carry a full closure. */
export interface RestrictedRoad {
  category: "mto_prohibited" | "municipal_expressway";
  label?: string | null;
  reason: string;
}

export interface EdgeMeta {
  idx: number;
  edge_id: string;
  geometry: [number, number][] | null; // [[lat, lng], ...] (Liron's stored form)
  road_name?: string;
  road_class?: string;
  restricted?: RestrictedRoad; // present only on MTO/municipal expressway edges
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
 * (`src/torontosim/graph/mutations.py`). The demand-side op for the Edit view's
 * surge/relief tool is `demand_surge` (backend: `model/demand_surge.py`,
 * applied to per-node demand before OD generation). `demand_change` is kept as
 * an accepted alias from the day-stream frontend.
 */
export type InterventionOp =
  | "close_edge"
  | "reopen_edge"
  | "remove_edge"
  | "change_capacity"
  | "close_node"
  | "add_edge"
  | "demand_surge"
  | "demand_change";

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
  // demand_surge / demand_change: anchor (node_id and/or lng/lat) + signed amount
  // radiating along the chosen compass directions (negative amount = relief).
  directions?: ("n" | "e" | "s" | "w")[];
  amount?: number;
  mode?: "absolute" | "relative";
  lat?: number;
  lng?: number;
}

export interface ViewDirective {
  action: "fit" | "fly" | "select" | "recenter" | "tilt" | "time";
  road_name?: string | null;
  edge_ids?: string[];
  lng?: number | null;
  lat?: number | null;
  zoom?: number | null;
  minute?: number | null; // action="time": minute-of-day to scrub to
}

export interface CopilotResponse {
  tool: string;
  rationale: string;
  interventions: Intervention[];
  citations: { ref: string; note: string }[];
  warnings?: { severity?: string; title?: string; detail?: string; ref?: string | null }[];
  view?: ViewDirective | null;
  requires_user_confirmation: boolean;
  blocked: boolean;
  intent?: string;
  retrieved_policy?: { doc_id: string; title: string; source: string }[];
}

/** /copilot/route — the single classifier's decision. For plan-mode intents the
 *  dispatched plan rides inline in `result` (no second hop). */
export interface CopilotRouteResult {
  mode: "plan" | "chat" | "agent";
  intent: string;
  result?: CopilotResponse;
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

export interface CopilotWarning {
  severity?: "info" | "warn" | "danger";
  title?: string;
  detail?: string;
  ref?: string | null;
}

export interface CopilotAgentResult {
  answer: string;
  interventions: Intervention[];
  citations: { ref: string; note: string }[];
  warnings?: CopilotWarning[];
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

/** Param-driven simulation request (POST /simulate, /simulate/prewarm). */
export interface SimulateReq {
  demand_model: "xgboost" | "gnn";
  time_context: { hour: number; day_of_week: number; month: number; weather: string };
  interventions: Intervention[];
  iterations?: number;
}

export interface SimulateResult {
  records: Record5[];
  summary: Record<string, number>;
  rgap?: number | null;
  /** Model that actually ran — surfaces the silent HeuristicDemandModel fallback. */
  model_actual: string;
  cached: boolean;
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
  health: () => jget<{ status: string; edges: number; baseline_ready?: boolean }>("/healthz"),
  edges: () => jget<{ edges: EdgeMeta[] }>("/edges"),
  // Measured 24-hour baseline (raw TMC counts, no ML) as one binary blob of 24
  // concatenated day-frames; the tick store walks it (see `ingestBaselineDay`).
  // Keyed on day-of-week + month (months sample different intersections).
  baselineDay: async (dow: number, month: number): Promise<ArrayBuffer> => {
    const r = await fetch(`${BASE}/baseline/day?dow=${dow}&month=${month}`);
    if (!r.ok) throw new Error(`GET /baseline/day → ${r.status}`);
    return r.arrayBuffer();
  },
  // The full-coverage PREDICTED baseline day (GNN, no interventions): 24 frames,
  // one binary blob the tick store walks via `ingestBaselineDay`. Keyed on
  // day-of-week + month.
  baselinePredicted: async (dow: number, month: number): Promise<ArrayBuffer> => {
    const r = await fetch(`${BASE}/baseline/predicted?dow=${dow}&month=${month}`);
    if (!r.ok) throw new Error(`GET /baseline/predicted → ${r.status}`);
    return r.arrayBuffer();
  },
  demoRun: (scenario: string) => jget<DemoRun>(`/demo/run?scenario=${scenario}`),
  // Param-driven run (real model → OD → equilibrium, cached). `prewarm` is the
  // speculative, non-blocking variant that warms the cache so Run is instant.
  simulate: (req: SimulateReq) => jpost<SimulateResult>("/simulate", req),
  simulatePrewarm: (req: SimulateReq) => jpost<{ queued: number }>("/simulate/prewarm", req),
  copilotPlan: (prompt: string, signal?: AbortSignal) =>
    jpost<CopilotResponse>("/copilot/plan", { prompt }, signal),
  copilotRoute: (prompt: string, history = "", signal?: AbortSignal) =>
    jpost<CopilotRouteResult>("/copilot/route", { prompt, history }, signal),
  copilotSuggestions: () => jget<{ prompts: string[] }>("/copilot/suggestions"),
  // Rebuild the baseline demand at a time-of-day / date (canonical units:
  // minute-of-day, day-of-year). Heavy — re-derives demand + re-sims.
  retimeBaseline: (minute: number, dayOfYear: number, weather?: string) =>
    jpost<{ time_context: Record<string, unknown>; summary: Record<string, number>; records: Record5[] }>(
      "/baseline/retime",
      { minute, day_of_year: dayOfYear, weather },
    ),
  // Dynamic follow-up chips reflecting the last exchange (prompt + bot reply + intent).
  copilotFollowups: (prompt: string, reply: string, intent: string, signal?: AbortSignal) =>
    jpost<{ prompts: string[] }>("/copilot/followups", { prompt, reply, intent }, signal),
  assess: (interventions: Intervention[], prompt = "", signal?: AbortSignal) =>
    jpost<{ warnings: CopilotWarning[] }>("/assess", { interventions, prompt }, signal),
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

/** A view to stream as a 24-hour time series (everything except the hour). */
export interface DayStreamSpec {
  demand_model: "xgboost" | "gnn";
  time_context: { day_of_week: number; month: number; weather?: string };
  interventions: Intervention[];
  current_hour: number; // prioritised so the visible map paints first
  epoch: number; // view generation; tags every frame so stale ones are dropped
  iterations?: number;
}

export interface DayStreamHandlers {
  onFrame?: (info: { hour: number; affectsView: boolean }) => void;
  onMeta?: (meta: { total: number; epoch: number; model_actual: string }) => void;
  onDone?: () => void;
  /** Socket error (network/handshake). */
  onError?: () => void;
  /** Socket closed BEFORE the server's "done" — a drop/crash mid-stream, distinct
   * from the normal post-"done" close. Lets the caller surface a stuck compute. */
  onPrematureClose?: () => void;
}

/**
 * Open the day-stream WS for a view: sends the spec, then routes each hour's
 * binary frame into the tick store as it completes (current hour first) and
 * surfaces meta/done to the caller. Superseding a view = close this socket and
 * open a new one (the backend cancels the old view's not-yet-started hours).
 */
export function connectDayStream(spec: DayStreamSpec, handlers: DayStreamHandlers = {}): WebSocket {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${location.host}${BASE}/day/stream`;
  const ws = new WebSocket(url);
  ws.binaryType = "arraybuffer";
  let done = false;
  ws.onopen = () => ws.send(JSON.stringify(spec));
  ws.onmessage = (ev) => {
    if (ev.data instanceof ArrayBuffer) {
      const info = ingestDayFrame(ev.data);
      if (info.epoch === spec.epoch) handlers.onFrame?.({ hour: info.hour, affectsView: info.affectsView });
    } else if (typeof ev.data === "string") {
      try {
        const msg = JSON.parse(ev.data) as { type?: string; total?: number; epoch?: number; model_actual?: string };
        if (msg.type === "meta") handlers.onMeta?.(msg as { total: number; epoch: number; model_actual: string });
        else if (msg.type === "done") {
          done = true;
          handlers.onDone?.();
        }
      } catch {
        /* ignore malformed control frame */
      }
    }
  };
  ws.onerror = () => handlers.onError?.();
  ws.onclose = () => {
    // A close after "done" is the normal end of a stream; a close before it means
    // the stream dropped/crashed mid-compute — surface that so the UI can recover.
    if (!done) handlers.onPrematureClose?.();
  };
  return ws;
}
