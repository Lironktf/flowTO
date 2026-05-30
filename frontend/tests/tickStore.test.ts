import { beforeEach, describe, expect, it } from "vitest";
import { RECORD_SIZE } from "../src/lib/decodeFrame";
import {
  consumeDirty,
  getArrays,
  getTickSeq,
  ingestFrame,
  isDirty,
  resizeTickStore,
  setPressure,
} from "../src/state/tickStore";

function packOne(idx: number, pressure: number): ArrayBuffer {
  const buf = new ArrayBuffer(4 + RECORD_SIZE);
  const dv = new DataView(buf);
  dv.setUint32(0, 1, true);
  dv.setUint32(4, idx, true);
  dv.setFloat32(8, 0, true);
  dv.setFloat32(12, 0, true);
  dv.setFloat32(16, pressure, true);
  dv.setUint8(20, 0);
  return buf;
}

describe("tickStore", () => {
  beforeEach(() => resizeTickStore(8));

  it("ingests frames into the typed arrays and flags dirty", () => {
    ingestFrame(packOne(3, 0.65));
    expect(getArrays().pressure[3]).toBeCloseTo(0.65, 5);
    expect(isDirty()).toBe(true);
  });

  it("consumeDirty advances the tick sequence exactly once per dirty batch", () => {
    const before = getTickSeq();
    setPressure(0, 0.5);
    expect(consumeDirty()).toBe(true);
    expect(getTickSeq()).toBe(before + 1);
    // No new writes -> not dirty, seq unchanged.
    expect(consumeDirty()).toBe(false);
    expect(getTickSeq()).toBe(before + 1);
  });
});
