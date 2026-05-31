import { describe, expect, it } from "vitest";
import { placeScore } from "../src/lib/search";

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
