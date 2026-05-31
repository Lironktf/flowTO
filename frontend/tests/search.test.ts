import { describe, expect, it } from "vitest";
import { placeScore, resolveQuery, type RoadIndexEntry } from "../src/lib/search";

const ROAD_INDEX: RoadIndexEntry[] = [
  {
    name: "King Street West",
    lower: "king street west",
    edgeId: "k1",
    coord: [-79.4, 43.64],
    bbox: [
      [-79.42, 43.63],
      [-79.38, 43.65],
    ],
  },
];

describe("placeScore", () => {
  it("ranks the exact-name landmark above a business that merely contains it", () => {
    // The bug it fixes: "360 The Restaurant at the CN Tower" outranking "CN Tower".
    const tower = placeScore("CN Tower", "poi", "CN Tower", 0);
    const restaurant = placeScore("360 The Restaurant at the CN Tower", "poi", "CN Tower", 0);
    expect(tower).toBeLessThan(restaurant);
  });

  it("prefers a poi over an address for the same name match", () => {
    const poi = placeScore("Union Station", "poi", "Union Station", 0);
    const addr = placeScore("Union Station", "address", "Union Station", 0);
    expect(poi).toBeLessThan(addr);
  });

  it("exact match beats starts-with beats contains", () => {
    const exact = placeScore("Liberty Village", "neighborhood", "Liberty Village", 0);
    const starts = placeScore("Liberty Village Park", "poi", "Liberty Village", 0);
    const contains = placeScore("North Liberty Village Lofts", "poi", "Liberty Village", 0);
    expect(exact).toBeLessThan(starts);
    expect(starts).toBeLessThan(contains);
  });

  it("is deterministic", () => {
    expect(placeScore("BMO Field", "poi", "bmo field", 2)).toBe(placeScore("BMO Field", "poi", "bmo field", 2));
  });
});

describe("resolveQuery (shared omnibox/copilot resolver)", () => {
  const noSignal = new AbortController().signal;

  it("resolves a road name to its street hit (local index, no network)", async () => {
    const hit = await resolveQuery(ROAD_INDEX, "King", noSignal);
    expect(hit?.kind).toBe("street");
    expect(hit?.label).toBe("King Street West");
    expect(hit?.bbox).toBeDefined();
    expect(hit?.edgeId).toBe("k1");
  });

  it("returns null for an empty query", async () => {
    expect(await resolveQuery(ROAD_INDEX, "  ", noSignal)).toBeNull();
  });

  it("returns null when nothing matches and geocoding is unavailable (no token)", async () => {
    // geocodePlaces no-ops without a Mapbox token, so a non-road query resolves to null.
    expect(await resolveQuery(ROAD_INDEX, "Narnia", noSignal)).toBeNull();
  });
});
