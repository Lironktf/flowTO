import { THREE_D_MIN_ZOOM } from "./mapbox";

export const TILTED_PITCH = 52;
export const TILTED_BEARING = -18;

export type MapView = "2D" | "3D";

export function cameraForView(view: MapView): { pitch: number; bearing: number } {
  return view === "3D" ? { pitch: TILTED_PITCH, bearing: TILTED_BEARING } : { pitch: 0, bearing: 0 };
}

export function minZoomForView(view: MapView): number | undefined {
  return view === "3D" ? THREE_D_MIN_ZOOM : undefined;
}
