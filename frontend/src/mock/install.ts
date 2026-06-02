/**
 * Installs the FAKE backend: shims `fetch` and `WebSocket` so the app's real
 * API client (`src/api/client.ts`) talks to an in-browser engine instead of a
 * live server. No torontosim backend, no Spark, no Nemotron — the whole RUNBOOK
 * story is synthesised from the committed graph. Activated by `VITE_MOCK=1`
 * (see `main.tsx`). Everything is deterministic, so a recording matches every run.
 */
import {
  buildModel,
  encodeBaselineDay,
  encodeDayFrame,
  getModel,
  nearestEdgeId,
  pressureForHour,
  recordsForHour,
  setModel,
  summarize,
  summaryDelta,
  type MockEdge,
  type MockIntervention,
} from "./data";

const BASE = "/api";
const SURGE_HOUR = 17; // the dramatic full-time hour the demo reveals

const nativeFetch = window.fetch.bind(window);
const NativeWebSocket = window.WebSocket;

// ── Edge model (loaded once from the static fixture) ─────────────────────────

let edgesPayload: { count: number; edges: MockEdge[] } | null = null;
let modelReady: Promise<void> | null = null;

function ensureModel(): Promise<void> {
  if (!modelReady) {
    modelReady = nativeFetch("/mock/edges.json")
      .then((r) => r.json())
      .then((payload: { count: number; edges: MockEdge[] }) => {
        edgesPayload = payload;
        setModel(buildModel(payload.edges));
        console.info(`[mock] loaded ${payload.edges.length} edges — FAKE backend active`);
      });
  }
  return modelReady;
}

// ── Tiny scenario store (in-memory) ──────────────────────────────────────────

const scenarios = new Map<string, MockIntervention[]>();
let scenarioSeq = 0;
function newScenario(interventions: MockIntervention[]): string {
  const id = `mock-sc-${++scenarioSeq}`;
  scenarios.set(id, interventions);
  return id;
}

// ── Canned Nemotron copilot ──────────────────────────────────────────────────

const HERO_RATIONALE = [
  "Full-time at Toronto Stadium releases ~45,000 people over 25 minutes. I assigned the egress demand to the Lake Shore / Strachan / Dufferin spine and found severe spill-over into Parkdale and Liberty Village local streets. A bylaw-valid mitigation:",
  "",
  "1. Eastbound contraflow on Lake Shore Blvd W (Strachan → Bathurst), 17:00–18:30",
  "2. Retime Dufferin and Strachan signals — 110 s cycle, egress-biased splits",
  "3. Close Princes' Blvd to general traffic (pedestrian egress); hold 509 / 511 transit priority",
  "",
  "Projected vs. unmitigated: total delay −38%, local infiltration −71%, zero hard-constraint conflicts. Preview on the map?",
].join("\n");

const HERO_CITATIONS = [
  { ref: "Toronto Municipal Code Ch. 950", note: "temporary traffic regulation under an approved event TMP" },
  { ref: "King St Transit Priority Corridor", note: "through-traffic restriction preserved" },
  { ref: "Toronto Municipal Code Ch. 880", note: "fire-route / emergency access lanes maintained" },
  { ref: "AODA 2005", note: "accessible pedestrian route on Princes' Blvd retained" },
];

const BLOCKED_RATIONALE = [
  "I can't apply that — closing Lake Shore Blvd in both directions breaches two hard constraints:",
  "",
  "• It removes the only emergency corridor to Stadium South — Toronto Fire access is lost.",
  "• The 509 / 511 streetcar-replacement buses require a westbound Lake Shore lane.",
  "",
  "Action blocked. The eastbound-contraflow alternative clears 84% of the same demand without these conflicts — apply that instead?",
].join("\n");

const BLOCKED_CITATIONS = [
  { ref: "Toronto Municipal Code Ch. 880", note: "designated fire route may not be fully closed" },
  { ref: "TTC service bylaw", note: "streetcar-replacement bus lane must be retained" },
];

/** The hero "ease the gridlock" plan — mixed closures + an egress-relief demand op
 *  (the contraflow + transit/pedestrian shift), so the surge actually melts. */
function heroPlan() {
  const interventions: MockIntervention[] = [
    { op: "close_edge", edge_id: nearestEdgeId(43.6348, -79.415) }, // Princes' Blvd
    { op: "close_edge", edge_id: nearestEdgeId(43.635, -79.4088) }, // Strachan @ Lake Shore
    { op: "demand_surge", lat: 43.6332, lng: -79.4185, amount: -45000 }, // contraflow + transit/pedestrian shift
  ];
  return {
    tool: "plan_intervention",
    rationale: HERO_RATIONALE,
    interventions,
    citations: HERO_CITATIONS,
    warnings: [],
    view: { action: "fly", lng: -79.4185, lat: 43.6332, zoom: 13.4 },
    requires_user_confirmation: true,
    blocked: false,
    intent: "mitigate_congestion",
    retrieved_policy: HERO_CITATIONS.map((c, i) => ({ doc_id: `doc-${i}`, title: c.ref, source: "Toronto Municipal Code" })),
  };
}

function blockedPlan() {
  return {
    tool: "reject_intervention",
    rationale: BLOCKED_RATIONALE,
    interventions: [],
    citations: BLOCKED_CITATIONS,
    warnings: [
      { severity: "danger", title: "Fire route may not be fully closed", detail: BLOCKED_CITATIONS[0].note, ref: BLOCKED_CITATIONS[0].ref },
    ],
    view: { action: "fly", lng: -79.42, lat: 43.636, zoom: 13.2 },
    requires_user_confirmation: false,
    blocked: true,
    intent: "blocked_bylaw",
    retrieved_policy: BLOCKED_CITATIONS.map((c, i) => ({ doc_id: `b-${i}`, title: c.ref, source: "Toronto Municipal Code" })),
  };
}

const CHAT_ANSWER =
  "Right now the worst congestion is the post-match egress spine: Lake Shore Blvd W and the Gardiner near Exhibition Place are at ~1.2 pressure (gridlock), with Dufferin and Strachan close behind. Cut-through is bleeding into Liberty Village and Parkdale local streets. Ask me to ease it without breaking bylaws and I'll propose a cited plan.";

type Mode = "plan" | "chat" | "agent";
function classify(prompt: string): { mode: Mode; kind: "hero" | "blocked" | "chat" } {
  const p = prompt.toLowerCase();
  if (/both ways|both directions/.test(p) || (/close/.test(p) && /lake ?shore/.test(p) && /both/.test(p)))
    return { mode: "plan", kind: "blocked" };
  if (/ease|mitigat|fix|reduce|relieve|relief|unblock|gridlock|surge|egress|without breaking|bylaw/.test(p))
    return { mode: "plan", kind: "hero" };
  if (/where|worst|congest|status|how bad/.test(p)) return { mode: "chat", kind: "chat" };
  return { mode: "chat", kind: "chat" };
}

const FOLLOWUPS = [
  "Apply the contraflow plan.",
  "What if we close Lake Shore both ways?",
  "Protect Parkdale local streets from cut-through.",
];

// ── JSON / binary Response helpers ───────────────────────────────────────────

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
}
function binary(buf: ArrayBuffer): Response {
  return new Response(buf, { status: 200, headers: { "content-type": "application/octet-stream" } });
}

function topImpacted(interventions: MockIntervention[]): { edge_id: string; delta: number; road_name?: string | null }[] {
  const M = getModel();
  const before = pressureForHour(SURGE_HOUR, []).pressure;
  const after = pressureForHour(SURGE_HOUR, interventions).pressure;
  const rows: { edge_id: string; delta: number; road_name?: string | null }[] = [];
  for (let i = 0; i < before.length; i++) {
    const d = after[i] - before[i];
    if (d < -0.05) rows.push({ edge_id: M.edges[i].edge_id, delta: d, road_name: M.edges[i].road_name });
  }
  rows.sort((a, b) => a.delta - b.delta);
  return rows.slice(0, 8);
}

// ── The REST router ──────────────────────────────────────────────────────────

async function route(path: string, init?: RequestInit): Promise<Response | null> {
  await ensureModel();
  const method = (init?.method ?? "GET").toUpperCase();
  const [rawPath, query = ""] = path.split("?");
  const qs = new URLSearchParams(query);
  const body = init?.body ? JSON.parse(init.body as string) : {};

  if (rawPath === "/healthz") return json({ status: "ok", edges: edgesPayload!.count, baseline_ready: true });
  if (rawPath === "/edges") return json(edgesPayload);

  if (rawPath === "/demo/run") {
    return json({
      scenario: qs.get("scenario") ?? "baseline",
      summary: summarize(8, []),
      headline_metric: 0,
      exhibition_pressure: pressureForHour(SURGE_HOUR, []).pressure[0] ?? 0,
      records: recordsForHour(8, []),
    });
  }

  if (rawPath === "/baseline/predicted" || rawPath === "/baseline/day") return binary(encodeBaselineDay([]));

  if (rawPath === "/baseline/retime") {
    const minute = body.minute ?? 8 * 60;
    const hour = Math.min(23, Math.floor(minute / 60));
    return json({ time_context: { hour }, summary: summarize(hour, []), records: recordsForHour(hour, []) });
  }

  if (rawPath === "/copilot/route") {
    const { mode, kind } = classify(body.prompt ?? "");
    if (mode === "plan") return json({ mode: "plan", intent: kind, result: kind === "blocked" ? blockedPlan() : heroPlan() });
    return json({ mode: "chat", intent: "status" });
  }
  if (rawPath === "/copilot/plan") {
    const { kind } = classify(body.prompt ?? "");
    return json(kind === "blocked" ? blockedPlan() : heroPlan());
  }
  if (rawPath === "/copilot/agent") {
    const { kind } = classify(body.prompt ?? "");
    const plan = kind === "blocked" ? blockedPlan() : heroPlan();
    return json({
      answer: plan.rationale,
      interventions: plan.interventions,
      citations: plan.citations,
      warnings: plan.warnings,
      steps: [
        { tool: "retrieve", thought: "Checking Toronto bylaws for the egress corridor.", observation: plan.citations.map((c) => c.ref) },
        { tool: "simulate", thought: "Scoring the candidate plan on the live sim.", observation: { delay_change: "-38%" } },
      ],
      requires_user_confirmation: plan.requires_user_confirmation,
      blocked: plan.blocked,
    });
  }
  if (rawPath === "/copilot/suggestions")
    return json({ prompts: ["Where is congestion worst right now?", "Ease gridlock near BMO Field without breaking bylaws.", "What happens if I close Lake Shore both ways?"] });
  if (rawPath === "/copilot/followups") return json({ prompts: FOLLOWUPS });
  if (rawPath === "/assess") return json({ warnings: [] });

  if (rawPath === "/copilot/confirm") {
    const interventions = (body.interventions ?? []) as MockIntervention[];
    const id = newScenario(interventions);
    return json({
      scenario_id: id,
      summary: summarize(SURGE_HOUR, interventions),
      summary_delta: summaryDelta(SURGE_HOUR, interventions),
      most_impacted_edges: topImpacted(interventions),
      explanation: "Plan applied — contraflow + signal retiming + pedestrian corridor recomputed via blast-radius. Egress corridors eased red → green; zero hard-constraint conflicts.",
    });
  }

  if (rawPath === "/scenarios" && method === "GET") return json({ scenarios: [] });
  if (rawPath === "/scenarios" && method === "POST") return json({ id: newScenario(body.interventions ?? []) });
  const sc = rawPath.match(/^\/scenarios\/([^/]+)(\/(run|records|preview|compare))?$/);
  if (sc) {
    const id = sc[1];
    const sub = sc[3];
    if (method === "PATCH") {
      scenarios.set(id, body.interventions ?? scenarios.get(id) ?? []);
      return json({ id });
    }
    if (method === "DELETE") {
      scenarios.delete(id);
      return new Response(null, { status: 204 });
    }
    const ivs = scenarios.get(id) ?? [];
    if (sub === "run" || sub === "preview") return json({ ok: true, scenario_id: id });
    if (sub === "records") return json({ records: recordsForHour(SURGE_HOUR, ivs), summary: summarize(SURGE_HOUR, ivs) });
    if (sub === "compare") return json({ summary_delta: summaryDelta(SURGE_HOUR, ivs), most_impacted_edges: topImpacted(ivs) });
    return json({ id, interventions: ivs });
  }

  if (rawPath === "/simulate")
    return json({ records: recordsForHour(SURGE_HOUR, body.interventions ?? []), summary: summarize(SURGE_HOUR, body.interventions ?? []), model_actual: "xgboost(mock)", cached: false });
  if (rawPath === "/simulate/prewarm") return json({ queued: 1 });
  if (rawPath === "/transit/routes") return json({ routes: [] });
  if (rawPath === "/transit/trajectories") return json({ trajectories: [] });

  return null; // not ours → native fetch
}

// ── fetch shim ───────────────────────────────────────────────────────────────

function reqUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return (input as Request).url;
}

window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const url = reqUrl(input);
  const apiAt = url.indexOf(BASE);
  const isApi = url.startsWith(BASE) || apiAt >= 0;
  if (isApi) {
    const path = url.startsWith(BASE) ? url.slice(BASE.length) : url.slice(apiAt + BASE.length);
    if (path.split("?")[0] === "/copilot/stream") {
      await ensureModel();
      return sseResponse();
    }
    try {
      const r = await route(path, init);
      if (r) return r;
    } catch (e) {
      console.error("[mock] route error", path, e);
      return new Response(JSON.stringify({ error: String(e) }), { status: 500 });
    }
  }
  return nativeFetch(input as RequestInfo, init);
};

/** Server-Sent-Events stream for the free-text copilot answer (chat mode). */
function sseResponse(): Response {
  const tokens = CHAT_ANSWER.match(/\S+\s*/g) ?? [CHAT_ANSWER];
  const enc = new TextEncoder();
  const t0 = performance.now();
  let i = 0;
  const stream = new ReadableStream({
    pull(controller) {
      if (i < tokens.length) {
        controller.enqueue(enc.encode(`data: ${JSON.stringify({ token: tokens[i++] })}\n\n`));
        return new Promise<void>((res) => setTimeout(res, 22));
      }
      const done = { done: true, first_token_ms: 40, total_ms: Math.round(performance.now() - t0), backend: "nemotron3:33b (mock)" };
      controller.enqueue(enc.encode(`data: ${JSON.stringify(done)}\n\n`));
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });
}

// ── WebSocket shim (the 24-hour day-stream) ──────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type WSListener = (ev: any) => void;

class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSING = 2;
  readonly CLOSED = 3;

  url: string;
  readyState = 0;
  binaryType: BinaryType = "blob";
  onopen: WSListener | null = null;
  onmessage: WSListener | null = null;
  onerror: WSListener | null = null;
  onclose: WSListener | null = null;
  private native: WebSocket | null = null;
  private closed = false;

  constructor(url: string | URL, protocols?: string | string[]) {
    this.url = url.toString();
    if (!this.url.includes("/api/day/stream") && !this.url.includes("/api/scenarios/")) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      this.native = new NativeWebSocket(url, protocols as any);
      return;
    }
    setTimeout(() => {
      if (this.closed) return;
      this.readyState = 1;
      this.onopen?.({ type: "open" });
    }, 0);
  }

  send(data: string): void {
    if (this.native) return this.native.send(data);
    let spec: Record<string, unknown> = {};
    try {
      spec = JSON.parse(data);
    } catch {
      /* ignore */
    }
    void this.emitDay(spec);
  }

  private async emitDay(spec: Record<string, unknown>): Promise<void> {
    await ensureModel();
    if (this.closed) return;
    const epoch = (spec.epoch as number) ?? 0;
    const interventions = (spec.interventions as MockIntervention[]) ?? [];
    const current = Math.max(0, Math.min(23, (spec.current_hour as number) ?? 8));
    this.onmessage?.({ data: JSON.stringify({ type: "meta", total: 24, epoch, model_actual: "xgboost(mock)" }) });
    const order = [current, ...Array.from({ length: 24 }, (_, h) => h).filter((h) => h !== current)];
    for (let k = 0; k < order.length; k++) {
      if (this.closed) return;
      const h = order[k];
      await new Promise<void>((res) => setTimeout(res, k === 0 ? 60 : 25));
      if (this.closed) return;
      this.onmessage?.({ data: encodeDayFrame(h, epoch, pressureForHour(h, interventions)) });
    }
    if (this.closed) return;
    this.onmessage?.({ data: JSON.stringify({ type: "done" }) });
  }

  close(): void {
    this.closed = true;
    this.readyState = 3;
    if (this.native) return this.native.close();
    setTimeout(() => this.onclose?.({ type: "close", wasClean: true }), 0);
  }

  addEventListener(type: string, fn: WSListener): void {
    if (type === "open") this.onopen = fn;
    else if (type === "message") this.onmessage = fn;
    else if (type === "error") this.onerror = fn;
    else if (type === "close") this.onclose = fn;
  }
  removeEventListener(): void {
    /* no-op for the demo */
  }
}

export function installMockBackend(): void {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (window as any).WebSocket = MockWebSocket;
  void ensureModel();
  console.info("[mock] FAKE backend installed (VITE_MOCK). No server required.");
}
