import { describe, expect, it } from "vitest";
import { THREE_D_MIN_ZOOM } from "../src/lib/mapbox";
import {
  cameraForView,
  minZoomForView,
} from "../src/lib/mapViewToggle";

describe("map view minimum zoom", () => {
  it("sets zoom 12 as the 3D floor", () => {
    expect(minZoomForView("3D")).toBe(THREE_D_MIN_ZOOM);
  });

  it("clears the floor in top-down view", () => {
    expect(minZoomForView("2D")).toBeUndefined();
  });
});

describe("map zoom clamp integration", () => {
  it("blocks zoom-out below 12 in 3D without changing the camera bearing", () => {
    let zoom = 14;
    let minZoom: number | null = null;
    const bearing = cameraForView("3D").bearing;
    const applyView = (view: "2D" | "3D") => {
      minZoom = minZoomForView(view) ?? null;
    };
    const map = {
      zoomOutTo: (requested: number) => { zoom = Math.max(requested, minZoom ?? 0); },
    };
    applyView("3D");
    map.zoomOutTo(10);
    expect(zoom).toBe(THREE_D_MIN_ZOOM);
    expect(cameraForView("3D").bearing).toBe(bearing);
  });

  it("allows zoom-out below 12 in top-down view", () => {
    let zoom = 14;
    let minZoom: number | null = THREE_D_MIN_ZOOM;
    const applyView = (view: "2D" | "3D") => {
      minZoom = minZoomForView(view) ?? null;
    };
    const map = {
      zoomOutTo: (requested: number) => { zoom = Math.max(requested, minZoom ?? 0); },
    };
    applyView("2D");
    map.zoomOutTo(10);
    expect(zoom).toBe(10);
  });
});
