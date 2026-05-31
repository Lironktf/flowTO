import { describe, expect, it } from "vitest";
import type { EdgeMeta } from "../src/api/client";
import {
  buildGraph,
  coordKey,
  corridorBetween,
  edgesAtNode,
  getSubSegment,
  neighboursOfEdge,
} from "../src/api/graph";
import { congestionSeries, diurnalFactor } from "../src/lib/congestion";
import { lightPresetForMinute, sunTimes } from "../src/lib/mapbox";

// A tiny network:  A —e1— B —e2— C , plus a cross street  B —e3— D
const A: [number, number] = [43.0, -79.0];
const B: [number, number] = [43.0, -79.001];
const C: [number, number] = [43.0, -79.002];
const D: [number, number] = [43.001, -79.001];

const edges: EdgeMeta[] = [
  { idx: 0, edge_id: "e1", road_name: "Main St", road_class: "primary", geometry: [A, B] },
  { idx: 1, edge_id: "e2", road_name: "Main St", road_class: "primary", geometry: [B, C] },
  { idx: 2, edge_id: "e3", road_name: "Cross Ave", road_class: "residential", geometry: [B, D] },
];

describe("graph adjacency index", () => {
  const g = buildGraph(edges);

  it("reconstructs vertices from shared endpoints", () => {
    // A, B, C, D = 4 distinct intersections
    expect(g.nodes.size).toBe(4);
    expect(g.byId.get("e1")?.fromKey).toBe(coordKey(A[0], A[1]));
    expect(g.byId.get("e1")?.toKey).toBe(coordKey(B[0], B[1]));
  });

  it("lists edges incident to a vertex", () => {
    const atB = edgesAtNode(g, coordKey(B[0], B[1])).map((s) => s.edge_id).sort();
    expect(atB).toEqual(["e1", "e2", "e3"]);
  });

  it("finds neighbouring edges of E", () => {
    const nb = neighboursOfEdge(g, "e1").map((s) => s.edge_id).sort();
    expect(nb).toEqual(["e2", "e3"]);
  });

  it("getSubSegment slices the geometry grid points", () => {
    expect(getSubSegment(g.byId.get("e1")!, 0, 1)).toEqual([A]);
  });
});

describe("corridor closure", () => {
  const g = buildGraph(edges);
  it("resolves the edge path between two intersections", () => {
    const corridor = corridorBetween(g, coordKey(A[0], A[1]), coordKey(C[0], C[1]));
    expect(corridor.map((s) => s.edge_id)).toEqual(["e1", "e2"]);
  });
  it("returns nothing for the same vertex", () => {
    expect(corridorBetween(g, coordKey(A[0], A[1]), coordKey(A[0], A[1]))).toEqual([]);
  });
});

describe("mapbox light preset", () => {
  it("maps the clock to dawn/day/dusk/night (summer)", () => {
    expect(lightPresetForMinute(2 * 60, 172)).toBe("night");
    expect(lightPresetForMinute(12 * 60, 172)).toBe("day");
    expect(lightPresetForMinute(23 * 60, 172)).toBe("night");
  });
  it("has longer days in summer than winter", () => {
    const summer = sunTimes(172);
    const winter = sunTimes(355);
    const summerLen = summer.sunset - summer.sunrise;
    const winterLen = winter.sunset - winter.sunrise;
    expect(summerLen).toBeGreaterThan(winterLen);
  });
});

describe("congestion series", () => {
  it("stays within [0,1] and peaks at rush hour", () => {
    const s = congestionSeries(1, 96);
    expect(s).toHaveLength(96);
    for (const p of s) {
      expect(p.v).toBeGreaterThanOrEqual(0);
      expect(p.v).toBeLessThanOrEqual(1);
    }
    // PM rush (~17:30) is busier than 03:00
    expect(diurnalFactor(17 * 60 + 30)).toBeGreaterThan(diurnalFactor(3 * 60));
  });
});
