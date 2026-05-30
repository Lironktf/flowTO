/**
 * Transit overlay layers (P08): route PathLayers colored by mode + a TripsLayer
 * animated by the scrubber's currentTime (seconds since midnight — small floats,
 * no TripsLayer float32 jitter). Visual only — decoupled from the traffic math.
 */
import { PathLayer } from "@deck.gl/layers";
import { TripsLayer } from "@deck.gl/geo-layers";

export type RGB = [number, number, number];

// route_type / mode → display color (NOT the congestion ramp — those hues are
// reserved for edge pressure).
export const MODE_COLOR: Record<string, RGB> = {
  streetcar: [196, 86, 47], // TTC red-brown
  subway: [50, 70, 110],
  bus: [90, 100, 120],
  rail: [40, 120, 90], // GO green
  "air-rail": [120, 80, 160], // UP Express
};

export interface RouteGeom {
  route_id: string;
  mode: string;
  path: [number, number][];
}
export interface Trajectory {
  trip_id: string;
  route_type: number;
  path: [number, number][];
  timestamps: number[];
}

export function modeColor(mode: string): RGB {
  return MODE_COLOR[mode] ?? MODE_COLOR.bus;
}

export function buildTransitLayers(
  routes: RouteGeom[],
  trajectories: Trajectory[],
  currentTime: number,
  opts?: { trailLength?: number },
): unknown[] {
  const layers: unknown[] = [];

  layers.push(
    new PathLayer({
      id: "transit-routes",
      data: routes,
      getPath: (r: RouteGeom) => r.path,
      getColor: (r: RouteGeom) => modeColor(r.mode),
      getWidth: 2.5,
      widthUnits: "pixels",
      getDashArray: [6, 4],
      dashJustified: true,
    }),
  );

  layers.push(
    new TripsLayer({
      id: "transit-vehicles",
      data: trajectories,
      getPath: (t: Trajectory) => t.path,
      getTimestamps: (t: Trajectory) => t.timestamps,
      getColor: [196, 86, 47],
      currentTime,
      trailLength: opts?.trailLength ?? 180,
      widthMinPixels: 4,
      capRounded: true,
    }),
  );

  return layers;
}
