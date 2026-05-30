import { describe, expect, it } from "vitest";
import { RECORD_SIZE, decodeFrameInto, makeTickArrays } from "../src/lib/decodeFrame";

/** Pack a frame the same way the backend (api.encoding) does. */
function packFrame(records: [number, number, number, number, number][]): ArrayBuffer {
  const buf = new ArrayBuffer(4 + records.length * RECORD_SIZE);
  const dv = new DataView(buf);
  dv.setUint32(0, records.length, true);
  let off = 4;
  for (const [idx, load, speed, pressure, closure] of records) {
    dv.setUint32(off, idx, true);
    dv.setFloat32(off + 4, load, true);
    dv.setFloat32(off + 8, speed, true);
    dv.setFloat32(off + 12, pressure, true);
    dv.setUint8(off + 16, closure);
    off += RECORD_SIZE;
  }
  return buf;
}

describe("decodeFrameInto", () => {
  it("round-trips a packed buffer into typed arrays", () => {
    const arrays = makeTickArrays(4);
    const n = decodeFrameInto(
      packFrame([
        [0, 100.0, 42.0, 0.8, 0],
        [2, 0.0, 0.0, 1.0, 1],
      ]),
      arrays,
    );
    expect(n).toBe(2);
    expect(arrays.pressure[0]).toBeCloseTo(0.8, 5);
    expect(arrays.load[0]).toBeCloseTo(100.0, 3);
    expect(arrays.closure[2]).toBe(1);
    expect(arrays.pressure[2]).toBeCloseTo(1.0, 5);
    // Untouched indices stay zero.
    expect(arrays.pressure[1]).toBe(0);
  });

  it("ignores out-of-range edge indices", () => {
    const arrays = makeTickArrays(2);
    expect(() => decodeFrameInto(packFrame([[99, 1, 1, 1, 0]]), arrays)).not.toThrow();
  });
});
