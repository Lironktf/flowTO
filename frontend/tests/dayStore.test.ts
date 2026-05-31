import { beforeEach, describe, expect, it } from "vitest";
import { DAY_TAG_SIZE, RECORD_SIZE } from "../src/lib/decodeFrame";
import {
  getArrays,
  hourlyNetworkPressure,
  ingestBaselineDay,
  ingestDayFrame,
  isHourReady,
  readyCount,
  resizeDayStore,
  setEpoch,
  setSelectedHour,
} from "../src/state/tickStore";

/** Pack a one-record day frame: (hour, epoch) tag + [idx, 0, 0, pressure, 0]. */
function packDayFrame(hour: number, epoch: number, idx: number, pressure: number): ArrayBuffer {
  const buf = new ArrayBuffer(DAY_TAG_SIZE + 4 + RECORD_SIZE);
  const dv = new DataView(buf);
  dv.setUint8(0, hour);
  dv.setUint32(1, epoch, true);
  const o = DAY_TAG_SIZE;
  dv.setUint32(o, 1, true); // count
  dv.setUint32(o + 4, idx, true);
  dv.setFloat32(o + 8, 0, true);
  dv.setFloat32(o + 12, 0, true);
  dv.setFloat32(o + 16, pressure, true);
  dv.setUint8(o + 20, 0);
  return buf;
}

describe("day tick store", () => {
  beforeEach(() => {
    resizeDayStore(8);
    setEpoch(1);
    setSelectedHour(8);
  });

  it("routes each hour's frame into its own slot", () => {
    ingestDayFrame(packDayFrame(8, 1, 3, 0.7));
    ingestDayFrame(packDayFrame(14, 1, 3, 0.2));
    expect(isHourReady(8)).toBe(true);
    expect(isHourReady(14)).toBe(true);
    expect(isHourReady(9)).toBe(false);
    expect(readyCount()).toBe(2);
    // getArrays() returns the selected hour (8).
    expect(getArrays().pressure[3]).toBeCloseTo(0.7, 5);
    // Scrub to 14 → that slot.
    setSelectedHour(14);
    expect(getArrays().pressure[3]).toBeCloseTo(0.2, 5);
  });

  it("drops frames from a stale epoch", () => {
    const r = ingestDayFrame(packDayFrame(8, 99, 3, 0.9));
    expect(r.affectsView).toBe(false);
    expect(isHourReady(8)).toBe(false);
  });

  it("reports a frame for the visible hour as affecting the view", () => {
    const r = ingestDayFrame(packDayFrame(8, 1, 3, 0.7));
    expect(r.affectsView).toBe(true); // hour 8 is selected
    const other = ingestDayFrame(packDayFrame(2, 1, 3, 0.5));
    expect(other.affectsView).toBe(false); // hour 2 not on screen, 8 already ready
  });

  it("shows the nearest ready hour until the exact one lands", () => {
    setSelectedHour(10); // nothing ready yet
    ingestDayFrame(packDayFrame(12, 1, 3, 0.4)); // nearest ready becomes 12
    expect(getArrays().pressure[3]).toBeCloseTo(0.4, 5);
    ingestDayFrame(packDayFrame(10, 1, 3, 0.9)); // exact hour now ready → preferred
    expect(getArrays().pressure[3]).toBeCloseTo(0.9, 5);
  });

  it("builds an hourly network-pressure series (NaN for unready hours)", () => {
    ingestDayFrame(packDayFrame(8, 1, 0, 0.6));
    const series = hourlyNetworkPressure();
    expect(series[8]).toBeCloseTo(0.6, 5);
    expect(Number.isNaN(series[9])).toBe(true);
  });

  it("ingests a 24-frame measured-baseline blob in one pass", () => {
    // hour 8 carries one record (idx 3, pressure 0.55); all other hours are empty.
    const frames: ArrayBuffer[] = [];
    for (let h = 0; h < 24; h++) {
      if (h === 8) {
        frames.push(packDayFrame(8, 0, 3, 0.55)); // epoch 0 = baseline
      } else {
        const empty = new ArrayBuffer(DAY_TAG_SIZE + 4);
        const dv = new DataView(empty);
        dv.setUint8(0, h);
        dv.setUint32(1, 0, true); // epoch 0
        dv.setUint32(DAY_TAG_SIZE, 0, true); // count 0
        frames.push(empty);
      }
    }
    const total = frames.reduce((n, b) => n + b.byteLength, 0);
    const blob = new Uint8Array(total);
    let o = 0;
    for (const b of frames) {
      blob.set(new Uint8Array(b), o);
      o += b.byteLength;
    }

    const n = ingestBaselineDay(blob.buffer);
    expect(n).toBe(24); // all 24 hours walked
    expect(readyCount()).toBe(24); // every hour marked ready (even empty ones)
    setSelectedHour(8);
    expect(getArrays().pressure[3]).toBeCloseTo(0.55, 5);
    setSelectedHour(2); // empty hour → free-flow
    expect(getArrays().pressure[3]).toBeCloseTo(0, 5);
  });

  it("setEpoch resets readiness for a new view", () => {
    ingestDayFrame(packDayFrame(8, 1, 3, 0.7));
    expect(readyCount()).toBe(1);
    setEpoch(2);
    expect(readyCount()).toBe(0);
    expect(isHourReady(8)).toBe(false);
  });
});
