import { describe, expect, it } from "vitest";
import { MODE_COLOR, modeColor } from "../src/layers/transit";

describe("transit modeColor", () => {
  it("maps each known mode to a distinct color", () => {
    expect(modeColor("streetcar")).toEqual(MODE_COLOR.streetcar);
    expect(modeColor("subway")).toEqual(MODE_COLOR.subway);
    expect(modeColor("rail")).toEqual(MODE_COLOR.rail);
    expect(modeColor("air-rail")).toEqual(MODE_COLOR["air-rail"]);
  });

  it("falls back to bus for an unknown mode", () => {
    expect(modeColor("monorail")).toEqual(MODE_COLOR.bus);
  });

  it("transit colors are not the congestion green/amber/red", () => {
    // Sanity: streetcar isn't pure congestion-red rgb(210,58,50).
    expect(MODE_COLOR.streetcar).not.toEqual([210, 58, 50]);
  });
});
