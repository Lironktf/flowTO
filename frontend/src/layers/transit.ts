/**
 * Transit overlay (visual only — decoupled from the traffic math).
 *
 * Route lines are rendered with a plain deck.gl PathLayer (from @deck.gl/layers).
 * We deliberately avoid @deck.gl/geo-layers (TripsLayer) and @deck.gl/extensions
 * here: those packages pull a large peer-dependency tree (mesh-layers, loaders.gl,
 * h3-js, …) that isn't needed for the redesign and breaks the production bundle.
 */
import { PathLayer } from "@deck.gl/layers";

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

/** Transit route lines, colored by mode. */
export function buildTransitLayers(routes: RouteGeom[]): unknown[] {
  return [
    new PathLayer({
      id: "transit-routes",
      parameters: { depthCompare: "always" },
      data: routes,
      getPath: (r: RouteGeom) => r.path,
      getColor: (r: RouteGeom) => modeColor(r.mode),
      getWidth: 2.5,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
    }),
  ];
}
