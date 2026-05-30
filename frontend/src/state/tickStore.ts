/**
 * Hot tick store — lives OUTSIDE React (research/06 rule #1).
 * Module-level typed arrays indexed by edge index; the WS handler writes in
 * place and bumps `tickSeq` (used in deck.gl `updateTriggers`). No setState.
 */
import { decodeFrameInto, makeTickArrays, type TickArrays } from "../lib/decodeFrame";

let arrays: TickArrays = makeTickArrays(0);
let tickSeq = 0;
let dirty = false;

export function resizeTickStore(n: number): void {
  arrays = makeTickArrays(n);
  dirty = true;
}

export function getArrays(): TickArrays {
  return arrays;
}

export function getTickSeq(): number {
  return tickSeq;
}

export function isDirty(): boolean {
  return dirty;
}

/** Decode a binary WS frame into the store. Returns records written. */
export function ingestFrame(buffer: ArrayBuffer): number {
  const n = decodeFrameInto(buffer, arrays);
  dirty = true;
  return n;
}

/** Consume the dirty flag + advance the tick sequence (called once per rAF). */
export function consumeDirty(): boolean {
  if (!dirty) return false;
  dirty = false;
  tickSeq++;
  return true;
}

/** Directly set a pressure value (used by the deterministic demo state machine). */
export function setPressure(idx: number, value: number): void {
  if (idx >= 0 && idx < arrays.pressure.length) {
    arrays.pressure[idx] = value;
    dirty = true;
  }
}
