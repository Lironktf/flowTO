/**
 * FAKE demo data engine (frontend-only, NO backend).
 *
 * Synthesises everything the real backend would serve — per-edge pressures over
 * a 24-hour matchday, the FIFA post-match egress surge, the mitigated "fix", the
 * binary tick frames, and the canned Nemotron copilot answers — entirely in the
 * browser from the REAL Toronto graph geometry (`/mock/edges.json`).
 *
 * This is the fallback demo path: if the live Spark stack hiccups, the app still
 * plays the whole RUNBOOK story off these fakes. Toggle with `VITE_MOCK=1`.
 */
import { RECORD_SIZE } from "../lib/decodeFrame";

export interface MockEdge {
  idx: number;
  edge_id: string;
  geometry: [number, number][]; // [lat, lng]
  road_name: string | null;
  road_class: string | null;
}

export interface MockIntervention {
  op: string;
  edge_id?: string;
  amount?: number;
  lat?: number;
  lng?: number;
  multiplier?: number;
}

// BMO Field / Exhibition Place — the egress generator (lat, lng).
const STADIUM_LAT = 43.6332;
const STADIUM_LNG = -79.4185;
// Financial-district core — biases the citywide baseline gradient.
const CORE_LAT = 43.6532;
const CORE_LNG = -79.3832;

// Hours the post-match surge is live (full-time ~17:05), peak at 17:00.
const EVENT_STRENGTH: Record<number, number> = { 17: 1.0, 18: 0.68, 19: 0.34 };

// Network-wide demand multiplier by hour (twin rush peaks, quiet overnight).
const HOUR_MULT = [
  0.22, 0.16, 0.14, 0.15, 0.2, 0.32, 0.58, 0.92, 1.12, 0.96, 0.82, 0.8, 0.82,
  0.8, 0.82, 0.9, 1.02, 1.16, 1.08, 0.86, 0.66, 0.5, 0.38, 0.28,
];

function classWeight(rc: string | null): number {
  switch (rc) {
    case "motorway":
    case "motorway_link":
    case "trunk":
    case "trunk_link":
      return 0.52;
    case "primary":
    case "primary_link":
      return 0.44;
    case "secondary":
    case "secondary_link":
      return 0.37;
    case "tertiary":
    case "tertiary_link":
      return 0.3;
    case "residential":
    case "living_street":
      return 0.16;
    case "service":
      return 0.12;
    default:
      return 0.24;
  }
}

/** Falloff factor of the egress surge onto local streets (cut-through). */
function classSurgeFactor(rc: string | null): number {
  switch (rc) {
    case "motorway":
    case "motorway_link":
    case "trunk":
    case "trunk_link":
    case "primary":
    case "primary_link":
      return 1.0;
    case "secondary":
    case "secondary_link":
      return 0.85;
    case "tertiary":
    case "tertiary_link":
      return 0.7;
    case "residential":
    case "living_street":
      return 0.55;
    default:
      return 0.6;
  }
}

/** Deterministic [-0.1, 0.1] jitter from an edge id (stable across reloads). */
function hashNoise(id: string): number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (((h >>> 0) % 1000) / 1000 - 0.5) * 0.2;
}

/** Equirectangular distance in km — fine at city scale. */
function distKm(aLat: number, aLng: number, bLat: number, bLng: number): number {
  const x = (((bLng - aLng) * Math.PI) / 180) * Math.cos(((aLat + bLat) * Math.PI) / 360);
  const y = ((bLat - aLat) * Math.PI) / 180;
  return Math.sqrt(x * x + y * y) * 6371;
}

// ── Precomputed per-edge static features ─────────────────────────────────────

export interface EdgeModel {
  edges: MockEdge[];
  byId: Map<string, number>;
  midLat: Float32Array;
  midLng: Float32Array;
  base: Float32Array; // calm baseline pressure p0
  surge: Float32Array; // surge spatial×class coefficient (× EVENT_STRENGTH[h])
  cap: Float32Array; // nominal capacity (for the load field)
}

let MODEL: EdgeModel | null = null;

export function buildModel(edges: MockEdge[]): EdgeModel {
  const n = edges.length;
  const byId = new Map<string, number>();
  const midLat = new Float32Array(n);
  const midLng = new Float32Array(n);
  const base = new Float32Array(n);
  const surge = new Float32Array(n);
  const cap = new Float32Array(n);

  for (let i = 0; i < n; i++) {
    const e = edges[i];
    byId.set(e.edge_id, i);
    const g = e.geometry;
    const m = g[Math.floor(g.length / 2)] ?? g[0];
    const la = m[0];
    const ln = m[1];
    midLat[i] = la;
    midLng[i] = ln;

    const w = classWeight(e.road_class);
    const dCore = distKm(la, ln, CORE_LAT, CORE_LNG);
    const coreBoost = Math.max(0, 0.22 * (1 - dCore / 11));
    base[i] = Math.min(0.8, Math.max(0.05, w + coreBoost + hashNoise(e.edge_id)));

    const dStad = distKm(la, ln, STADIUM_LAT, STADIUM_LNG);
    const spatial = Math.max(0, 1 - dStad / 3.0); // within ~3 km of the stadium
    surge[i] = spatial * classSurgeFactor(e.road_class) * 0.95;

    cap[i] = 600 + w * 1800;
  }
  return { edges, byId, midLat, midLng, base, surge, cap };
}

export function setModel(m: EdgeModel): void {
  MODEL = m;
}
export function getModel(): EdgeModel {
  if (!MODEL) throw new Error("mock model not initialised");
  return MODEL;
}

// ── Per-hour pressure field (matchday + interventions) ───────────────────────

export interface Field {
  pressure: Float32Array;
  closure: Uint8Array;
}

/**
 * The per-edge pressure for a given hour, with the matchday egress surge baked
 * in, then each intervention applied as a local delta. With no interventions
 * this IS the predicted matchday (calm pre-FT, deep red on the egress spine at
 * 17:00) — so scrubbing to full-time melts the southwest red.
 */
export function pressureForHour(hour: number, interventions: MockIntervention[] = []): Field {
  const M = getModel();
  const n = M.edges.length;
  const mult = HOUR_MULT[((hour % 24) + 24) % 24];
  const ev = EVENT_STRENGTH[hour] ?? 0;
  const pressure = new Float32Array(n);
  const closure = new Uint8Array(n);

  for (let i = 0; i < n; i++) {
    const p = M.base[i] * mult + M.surge[i] * ev;
    pressure[i] = p > 1.4 ? 1.4 : p;
  }

  for (const iv of interventions) {
    if (iv.op === "close_edge" && iv.edge_id) {
      const idx = M.byId.get(iv.edge_id);
      if (idx !== undefined) {
        closure[idx] = 1;
        pressure[idx] = 0;
        applyRadial(pressure, M, M.midLat[idx], M.midLng[idx], 0.4, -0.12);
      }
    } else if ((iv.op === "demand_surge" || iv.op === "demand_change") && iv.lat != null && iv.lng != null) {
      const amt = iv.amount ?? 0;
      const strength = Math.sign(amt) * Math.min(Math.abs(amt) / 45000, 1) * 0.78;
      applyRadial(pressure, M, iv.lat, iv.lng, 2.6, strength);
    } else if (iv.op === "change_capacity" && iv.edge_id) {
      const idx = M.byId.get(iv.edge_id);
      if (idx !== undefined && iv.multiplier) {
        pressure[idx] = Math.min(1.4, pressure[idx] / Math.max(0.2, iv.multiplier));
      }
    }
  }
  return { pressure, closure };
}

function applyRadial(
  pressure: Float32Array,
  M: EdgeModel,
  lat: number,
  lng: number,
  radiusKm: number,
  delta: number,
): void {
  const n = pressure.length;
  for (let i = 0; i < n; i++) {
    const d = distKm(M.midLat[i], M.midLng[i], lat, lng);
    if (d >= radiusKm) continue;
    const falloff = 1 - d / radiusKm;
    const p = pressure[i] + delta * falloff;
    pressure[i] = p < 0 ? 0 : p > 1.4 ? 1.4 : p;
  }
}

// ── Binary frame encoding (mirrors backend api/encoding.py) ───────────────────

const DAY_TAG = 5;

/** Encode one day-frame: [hour:u8][epoch:u32][count:u32][records...]. */
export function encodeDayFrame(hour: number, epoch: number, field: Field): ArrayBuffer {
  const M = getModel();
  const n = M.edges.length;
  const buf = new ArrayBuffer(DAY_TAG + 4 + n * RECORD_SIZE);
  const dv = new DataView(buf);
  dv.setUint8(0, hour);
  dv.setUint32(1, epoch, true);
  dv.setUint32(DAY_TAG, n, true);
  let off = DAY_TAG + 4;
  for (let i = 0; i < n; i++) {
    const p = field.pressure[i];
    const speed = Math.max(4, 55 * (1 - (0.6 * Math.min(p, 1.3)) / 1.3));
    const load = p * M.cap[i];
    dv.setUint32(off, i, true);
    dv.setFloat32(off + 4, load, true);
    dv.setFloat32(off + 8, speed, true);
    dv.setFloat32(off + 12, p, true);
    dv.setUint8(off + 16, field.closure[i]);
    off += RECORD_SIZE;
  }
  return buf;
}

/** The 24-hour predicted matchday as one blob of concatenated day-frames. */
export function encodeBaselineDay(interventions: MockIntervention[] = []): ArrayBuffer {
  const frames: ArrayBuffer[] = [];
  let total = 0;
  for (let h = 0; h < 24; h++) {
    const f = encodeDayFrame(h, 0, pressureForHour(h, interventions));
    frames.push(f);
    total += f.byteLength;
  }
  const out = new Uint8Array(total);
  let off = 0;
  for (const f of frames) {
    out.set(new Uint8Array(f), off);
    off += f.byteLength;
  }
  return out.buffer;
}

/** JSON records ([idx, load, speed, pressure, closure]) for the REST paint paths. */
export function recordsForHour(hour: number, interventions: MockIntervention[] = []): number[][] {
  const M = getModel();
  const f = pressureForHour(hour, interventions);
  const out: number[][] = [];
  for (let i = 0; i < M.edges.length; i++) {
    const p = f.pressure[i];
    const speed = Math.max(4, 55 * (1 - (0.6 * Math.min(p, 1.3)) / 1.3));
    out.push([i, p * M.cap[i], speed, p, f.closure[i]]);
  }
  return out;
}

/** Summary metrics over a pressure field (matches METRIC_LABELS keys). */
export function summarize(hour: number, interventions: MockIntervention[] = []): Record<string, number> {
  const f = pressureForHour(hour, interventions);
  let active = 0;
  let high = 0;
  let severe = 0;
  let sum = 0;
  for (let i = 0; i < f.pressure.length; i++) {
    const p = f.pressure[i];
    if (p > 0.02) {
      active++;
      sum += p;
    }
    if (p >= 1.0) severe++;
    else if (p >= 0.75) high++;
  }
  return {
    average_pressure: active ? sum / active : 0,
    active_edges: active,
    high_risk_edges: high,
    severe_edges: severe,
    total_assigned_trips: Math.round(active * 1.7),
  };
}

export function summaryDelta(hour: number, interventions: MockIntervention[]): Record<string, number> {
  const before = summarize(hour, []);
  const after = summarize(hour, interventions);
  const out: Record<string, number> = {};
  for (const k of Object.keys(before)) out[k] = after[k] - before[k];
  return out;
}

// ── Nearest-edge helper (resolve copilot plan targets to real edge ids) ──────

export function nearestEdgeId(lat: number, lng: number): string {
  const M = getModel();
  let best = 0;
  let bd = Infinity;
  for (let i = 0; i < M.edges.length; i++) {
    const d = (M.midLat[i] - lat) ** 2 + (M.midLng[i] - lng) ** 2;
    if (d < bd) {
      bd = d;
      best = i;
    }
  }
  return M.edges[best].edge_id;
}
