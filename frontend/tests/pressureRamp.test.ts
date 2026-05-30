import { describe, expect, it } from "vitest";
import { pressureRamp, remapIntensity } from "../src/lib/pressureRamp";

describe("pressureRamp", () => {
  it("is green at free flow and red at gridlock", () => {
    const free = pressureRamp(0);
    const grid = pressureRamp(1);
    expect(free).toEqual([31, 157, 87]);
    expect(grid).toEqual([210, 58, 50]);
  });

  it("hits amber at the moderate stop (0.55)", () => {
    expect(pressureRamp(0.55)).toEqual([224, 162, 26]);
  });

  it("red channel increases monotonically with pressure", () => {
    let prevRedMinusGreen = -Infinity;
    for (let p = 0; p <= 1.0001; p += 0.1) {
      const [r, g] = pressureRamp(Math.min(p, 1));
      expect(r - g).toBeGreaterThanOrEqual(prevRedMinusGreen - 1);
      prevRedMinusGreen = r - g;
    }
  });

  it("clamps and remaps intensity around the midpoint", () => {
    expect(remapIntensity(0.5, 1.4)).toBeCloseTo(0.5);
    expect(remapIntensity(1.0, 1.4)).toBe(1);
    expect(remapIntensity(0.0, 1.4)).toBe(0);
  });

  it("brightens channels in dark mode", () => {
    const light = pressureRamp(0.5);
    const dark = pressureRamp(0.5, { dark: true });
    expect(dark[0]).toBeGreaterThan(light[0]);
  });
});
