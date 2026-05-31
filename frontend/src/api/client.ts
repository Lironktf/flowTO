/**
 * Typed REST client for the live P06/P07/P12 backend. All traffic data is real
 * engine output — the frontend renders the actual Toronto graph (`/edges`)
 * colored by pressures from `/demo/run`, with before/after from the run
 * summaries and copilot answers from `/copilot/plan`. The binary WS tick stream
 * (`connectStream`) feeds the tick store for live-tick scenarios.
 */
import { ingestDayFrame, ingestFrame } from "../state/tickStore";

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

export interface CopilotResponse {
  tool: string;
  rationale: string;
  citations: { ref: string; note: string }[];
  requires_user_confirmation: boolean;
  blocked: boolean;
  retrieved_policy?: { doc_id: string; title: string; source: string }[];
}

/**
 * Graph-mutation ops. The first six mirror the backend
 * (`src/torontosim/graph/mutations.py`). `demand_change` is the demand-side op
 * for the Edit view's surge/relief tool — implemented on the backend in
 * `model/demand_surge.py` and applied to per-node demand before OD generation.
 */
export type InterventionOp =
  | "close_edge"
  | "reopen_edge"
  | "remove_edge"
  | "change_capacity"
  | "close_node"
  | "add_edge"
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
  // demand_change: anchor (edge_id and/or lng/lat) + signed amount radiating
  // along the chosen compass directions (negative amount = relief).
  directions?: ("n" | "e" | "s" | "w")[];
  amount?: number;
  mode?: "absolute" | "relative";
  lat?: number;
  lng?: number;
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

async function jpost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
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
  // Measured 24-hour baseline (raw TMC counts, no ML) as one binary blob of 24
  // concatenated day-frames; the tick store walks it (see `ingestBaselineDay`).
  // Keyed on day-of-week + month (months sample different intersections).
  baselineDay: async (dow: number, month: number): Promise<ArrayBuffer> => {
    const r = await fetch(`${BASE}/baseline/day?dow=${dow}&month=${month}`);
    if (!r.ok) throw new Error(`GET /baseline/day → ${r.status}`);
    return r.arrayBuffer();
  },
  // The full-coverage PREDICTED baseline day (GNN, no interventions): 24 frames,
  // one binary blob the tick store walks via `ingestBaselineDay`. The GNN predicts
  // a pressure for every edge directly, so this is the "usual congestion" view —
  // fast (~0.3s warm) and cached server-side. Keyed on day-of-week + month.
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
  copilotPlan: (prompt: string) => jpost<CopilotResponse>("/copilot/plan", { prompt }),
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
