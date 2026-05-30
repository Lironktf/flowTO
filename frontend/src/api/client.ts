/**
 * Typed REST + WS client for the P06 backend. In demo mode the app runs off the
 * embedded corridor data; in live mode it talks to this client. The WS handler
 * decodes binary frames straight into the tick store (no React).
 */
import { ingestFrame } from "../state/tickStore";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

export interface EdgeMeta {
  idx: number;
  edge_id: string;
  geometry: [number, number][] | null;
  road_name?: string;
  road_class?: string;
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

export const api = {
  health: () => jget<{ status: string; edges: number }>("/healthz"),
  edges: () => jget<{ edges: EdgeMeta[] }>("/edges"),
  createScenario: (payload: unknown) => jpost<{ id: string }>("/scenarios", payload),
  run: (id: string, req: unknown) => jpost<unknown>(`/scenarios/${id}/run`, req),
  preview: (id: string, req: unknown) => jpost<unknown>(`/scenarios/${id}/preview`, req),
  compare: (id: string) => jget<unknown>(`/scenarios/${id}/compare?against=baseline`),
};

/** Connect the tick WebSocket; decodes binary frames into the tick store. */
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
