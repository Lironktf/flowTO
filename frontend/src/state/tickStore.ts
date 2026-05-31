/**
 * Hot tick store — lives OUTSIDE React (research/06 rule #1).
 *
 * Holds a whole DAY as 24 hourly snapshots of per-edge [load, speed, pressure,
 * closure] (~950 KB/hour × 24 ≈ 23 MB for the Toronto graph). The day-stream WS
 * (`connectDayStream`) decodes each hour's frame into its slot as it arrives;
 * scrubbing/▶play just *select* which hour `getArrays()` returns — no network,
 * no recompute. Repaint is driven by the app store bumping `pressureSeq`
 * (deck.gl `updateTriggers`), so the WS handler bumps it whenever the *visible*
 * hour's data changes.
 */
import { DAY_TAG_SIZE, RECORD_SIZE, decodeFrameInto, makeTickArrays, type TickArrays } from "../lib/decodeFrame";

const DAY_HOURS = 24;

let dayArrays: TickArrays[] = Array.from({ length: DAY_HOURS }, () => makeTickArrays(0));
let readyHours = new Uint8Array(DAY_HOURS); // 1 = that hour's frame has landed
let selectedHour = 8; // which hour getArrays() returns (the playhead)
let currentEpoch = 0; // view generation; frames from other epochs are dropped
let nEdges = 0;
let tickSeq = 0;
let dirty = false;

/** Allocate the 24 hourly buffers for an n-edge graph and reset readiness. */
export function resizeDayStore(n: number): void {
  nEdges = n;
  dayArrays = Array.from({ length: DAY_HOURS }, () => makeTickArrays(n));
  readyHours = new Uint8Array(DAY_HOURS);
  dirty = true;
}

/** Back-compat alias (loadTwin calls resizeTickStore(edges.length)). */
export function resizeTickStore(n: number): void {
  resizeDayStore(n);
}

/** Nearest ready hour to `h` (search outward), or -1 if none ready yet. */
function nearestReadyHour(h: number): number {
  if (readyHours[h]) return h;
  for (let d = 1; d < DAY_HOURS; d++) {
    const a = (h + d) % DAY_HOURS;
    const b = (h - d + DAY_HOURS) % DAY_HOURS;
    if (readyHours[a]) return a;
    if (readyHours[b]) return b;
  }
  return -1;
}

/** The hour actually shown: the selected hour if ready, else nearest ready. */
function displayHour(): number {
  const nr = nearestReadyHour(selectedHour);
  return nr === -1 ? selectedHour : nr;
}

export function getArrays(): TickArrays {
  return dayArrays[displayHour()];
}

export function getHourArrays(h: number): TickArrays {
  return dayArrays[((h % DAY_HOURS) + DAY_HOURS) % DAY_HOURS];
}

export function isHourReady(h: number): boolean {
  return !!readyHours[((h % DAY_HOURS) + DAY_HOURS) % DAY_HOURS];
}

export function readyCount(): number {
  let c = 0;
  for (let i = 0; i < DAY_HOURS; i++) c += readyHours[i];
  return c;
}

export function getSelectedHour(): number {
  return selectedHour;
}

export function getCurrentEpoch(): number {
  return currentEpoch;
}

/** Begin a new view: drop readiness (keep old buffers painting until new frames
 * land, so there's no flash to empty) and tag incoming frames with this epoch. */
export function setEpoch(epoch: number): void {
  currentEpoch = epoch;
  readyHours = new Uint8Array(DAY_HOURS);
}

/** Select which hour is painted (the playhead). Returns true if the *displayed*
 * arrays changed (so the caller can bump pressureSeq to repaint). */
export function setSelectedHour(h: number): boolean {
  const prev = displayHour();
  selectedHour = ((h % DAY_HOURS) + DAY_HOURS) % DAY_HOURS;
  const now = displayHour();
  if (now !== prev) {
    dirty = true;
    return true;
  }
  return false;
}

/** Decode a day frame (tag + body) into its hour slot. Returns whether the
 * frame belongs to the current epoch and whether it changed the visible hour. */
export function ingestDayFrame(buffer: ArrayBuffer): { hour: number; epoch: number; affectsView: boolean } {
  const dv = new DataView(buffer);
  const hour = dv.getUint8(0);
  const epoch = dv.getUint32(1, true);
  if (epoch !== currentEpoch || hour < 0 || hour >= DAY_HOURS) {
    return { hour, epoch, affectsView: false }; // stale view or bad tag
  }
  if (dayArrays[hour].pressure.length !== nEdges) {
    dayArrays[hour] = makeTickArrays(nEdges); // safety if resized between
  }
  decodeFrameInto(buffer, dayArrays[hour], DAY_TAG_SIZE);
  readyHours[hour] = 1;
  const affectsView = hour === displayHour();
  if (affectsView) dirty = true;
  return { hour, epoch, affectsView };
}

/** Ingest the measured-baseline day: one blob of 24 concatenated day-frames
 * (`GET /baseline/day`). Walks each frame into its hour slot in one pass — no
 * WebSocket, no epoch (baseline is the epoch-0 view). Returns #frames ingested. */
export function ingestBaselineDay(buffer: ArrayBuffer): number {
  const dv = new DataView(buffer);
  currentEpoch = 0;
  readyHours = new Uint8Array(DAY_HOURS);
  let off = 0;
  let frames = 0;
  while (off + DAY_TAG_SIZE + 4 <= buffer.byteLength && frames < DAY_HOURS) {
    const hour = dv.getUint8(off);
    const bodyOffset = off + DAY_TAG_SIZE; // skip (hour:u8, epoch:u32) tag → frame body
    const count = dv.getUint32(bodyOffset, true);
    if (hour >= 0 && hour < DAY_HOURS) {
      if (dayArrays[hour].pressure.length !== nEdges) dayArrays[hour] = makeTickArrays(nEdges);
      decodeFrameInto(buffer, dayArrays[hour], bodyOffset);
      readyHours[hour] = 1;
    }
    off = bodyOffset + 4 + count * RECORD_SIZE;
    frames++;
  }
  dirty = true;
  return frames;
}

// ── back-compat: single-snapshot REST path (saved-sim / copilot / reset) ──────
// These write into the *selected* hour slot so the existing paintBaseline /
// simulateAndPaint / setPressure flows keep working unchanged.

export function getTickSeq(): number {
  return tickSeq;
}

export function isDirty(): boolean {
  return dirty;
}

/** Live-tick scenario stream (dormant): decode a plain frame into selected hour. */
export function ingestFrame(buffer: ArrayBuffer): number {
  const n = decodeFrameInto(buffer, dayArrays[selectedHour]);
  readyHours[selectedHour] = 1;
  dirty = true;
  return n;
}

export function consumeDirty(): boolean {
  if (!dirty) return false;
  dirty = false;
  tickSeq++;
  return true;
}

export function setPressure(idx: number, value: number): void {
  const arr = dayArrays[selectedHour].pressure;
  if (idx >= 0 && idx < arr.length) {
    arr[idx] = value;
    dirty = true;
  }
}

/** Write a batch of [edge_idx, load, speed, pressure, closure] into selected hour. */
export function writeRecords(records: [number, number, number, number, number][]): void {
  const a = dayArrays[selectedHour];
  for (const [idx, load, speed, pressure, closure] of records) {
    if (idx >= 0 && idx < a.pressure.length) {
      a.load[idx] = load;
      a.speed[idx] = speed;
      a.pressure[idx] = pressure;
      a.closure[idx] = closure;
    }
  }
  readyHours[selectedHour] = 1;
  dirty = true;
}

// ── derived per-hour series for the congestion chart (Phase 6) ────────────────

/** Network-average pressure over loaded edges, per hour (NaN for unready hours). */
export function hourlyNetworkPressure(): Float32Array {
  const out = new Float32Array(DAY_HOURS);
  for (let h = 0; h < DAY_HOURS; h++) {
    if (!readyHours[h]) {
      out[h] = NaN;
      continue;
    }
    const p = dayArrays[h].pressure;
    let sum = 0;
    let c = 0;
    for (let i = 0; i < p.length; i++) {
      if (p[i] > 0) {
        sum += p[i];
        c++;
      }
    }
    out[h] = c ? sum / c : 0;
  }
  return out;
}

/** One edge's pressure per hour (NaN for unready hours). */
export function hourlyEdgePressure(idx: number): Float32Array {
  const out = new Float32Array(DAY_HOURS);
  for (let h = 0; h < DAY_HOURS; h++) {
    out[h] = readyHours[h] ? dayArrays[h].pressure[idx] ?? 0 : NaN;
  }
  return out;
}
