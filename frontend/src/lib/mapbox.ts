/**
 * Mapbox Standard helpers.
 *
 * We render the basemap with Mapbox Standard (`mapbox://styles/mapbox/standard`)
 * so we get dynamic time-of-day lighting + opaque 3D buildings for free, and
 * overlay our deck.gl congestion layer in the Standard "middle" slot (above the
 * road network, below labels & 3D buildings).
 *
 * Standard is configured via the `basemap` style import:
 *   map.setConfigProperty('basemap', 'lightPreset', 'dusk')
 *   map.setConfigProperty('basemap', 'show3dObjects', true)
 * (see https://docs.mapbox.com/map-styles/standard/guides/)
 */

export const STANDARD_STYLE = "mapbox://styles/mapbox/standard";

/** Mapbox access token (set VITE_MAPBOX_TOKEN in frontend/.env). */
export const MAPBOX_TOKEN: string = import.meta.env.VITE_MAPBOX_TOKEN ?? "";
export const HAS_MAPBOX_TOKEN = MAPBOX_TOKEN.length > 0;

/** The Standard slot our congestion streets live in (above roads, below labels). */
export const CONGESTION_SLOT = "middle" as const;

/** The four light presets Mapbox Standard ships. */
export type LightPreset = "dawn" | "day" | "dusk" | "night";

/**
 * Approximate sunrise/sunset (minutes since local midnight) for Toronto
 * (lat ≈ 43.65°N) as a function of day-of-year. Daylight swings sinusoidally
 * around the summer solstice (~day 172): ~15.2 h in midsummer, ~8.8 h midwinter,
 * which matches Toronto within a few minutes — enough to pick a light preset.
 */
export function sunTimes(dayOfYear: number): { sunrise: number; sunset: number } {
  const t = (2 * Math.PI * (dayOfYear - 172)) / 365.25; // 0 at summer solstice
  const daylightMin = (12 + 3.2 * Math.cos(t)) * 60;
  const solarNoon = 12 * 60 + 25; // ~12:25 local clock time in Toronto
  return {
    sunrise: solarNoon - daylightMin / 2,
    sunset: solarNoon + daylightMin / 2,
  };
}

/**
 * Pick the Standard light preset for a clock minute (0–1439), shifted by the
 * season via `dayOfYear` (1–366, default = summer solstice). Dawn brackets
 * sunrise (~1 h before → 30 min after); dusk brackets sunset; night otherwise.
 */
export function lightPresetForMinute(minute: number, dayOfYear = 172): LightPreset {
  const { sunrise, sunset } = sunTimes(dayOfYear);
  const dawnStart = sunrise - 60;
  const dayStart = sunrise + 30;
  const duskStart = sunset - 45;
  const nightStart = sunset + 60;
  if (minute < dawnStart || minute >= nightStart) return "night";
  if (minute < dayStart) return "dawn";
  if (minute < duskStart) return "day";
  return "dusk";
}

/** Mapbox GL map-ish surface we touch (keeps us off a hard mapbox-gl type dep here). */
interface ConfigurableMap {
  setConfigProperty(importId: string, prop: string, value: unknown): void;
}

/**
 * Broader Standard-style map surface for adding our own 3D-building source/layer.
 * Typed loosely (matching the ConfigurableMap pattern) to stay off a hard
 * mapbox-gl type dependency in this helper module.
 */
interface StyleMap extends ConfigurableMap {
  getLayer(id: string): unknown;
  getSource(id: string): unknown;
  addSource(id: string, source: unknown): void;
  addLayer(layer: unknown, beforeId?: string): void;
  setPaintProperty(layerId: string, prop: string, value: unknown): void;
}

/**
 * Most recently applied light preset. mapbox-gl re-runs the (relatively heavy)
 * lightPreset cross-fade on every setConfigProperty call, so the scrubber effect
 * firing each minute would re-trigger the transition. Guard redundant calls.
 */
let _lastPreset: LightPreset | null = null;

/** Apply a light preset to the Standard basemap (safe to call after style load). */
export function applyLightPreset(map: ConfigurableMap | null | undefined, preset: LightPreset): void {
  if (!map) return;
  if (preset === _lastPreset) return;
  try {
    map.setConfigProperty("basemap", "lightPreset", preset);
    _lastPreset = preset; // only mark applied on a successful call
  } catch {
    /* style not ready yet — caller re-applies on 'style.load' */
  }
}

/** Building extrusion fill color per theme (keeps the constants in one place). */
function earlyBuildingColor(dark: boolean): string {
  return dark ? "#3a414b" : "#cfcabb";
}

/**
 * Add 3D building extrusions from Mapbox Streets v8 in the Standard "middle" slot
 * so they appear earlier (lower zoom) than Standard's own buildings. Idempotent.
 */
export function addEarlyBuildings(map: StyleMap | null | undefined, dark: boolean): void {
  try {
    if (!map) return;
    if (map.getLayer("early-buildings")) return;
    if (!map.getSource("mapbox-streets")) {
      map.addSource("mapbox-streets", { type: "vector", url: "mapbox://mapbox.mapbox-streets-v8" });
    }
    map.addLayer({
      id: "early-buildings",
      type: "fill-extrusion",
      source: "mapbox-streets",
      "source-layer": "building",
      slot: "middle",
      minzoom: 12.5,
      maxzoom: 16,
      filter: ["==", ["get", "extrude"], "true"],
      paint: {
        "fill-extrusion-color": earlyBuildingColor(dark),
        "fill-extrusion-height": ["get", "height"],
        "fill-extrusion-base": ["get", "min_height"],
        "fill-extrusion-opacity": ["interpolate", ["linear"], ["zoom"], 12.5, 0, 14, 0.65, 15.5, 1],
      },
    });
  } catch {
    /* style not ready yet — caller re-applies on load */
  }
}

/** Re-tint the early-buildings extrusion for the active theme (no-op if absent). */
export function setEarlyBuildingsColor(map: StyleMap | null | undefined, dark: boolean): void {
  try {
    if (map?.getLayer("early-buildings")) {
      map.setPaintProperty("early-buildings", "fill-extrusion-color", earlyBuildingColor(dark));
    }
  } catch {
    /* no-op until style loads */
  }
}

/** Toggle Standard's 3D objects (buildings, landmarks, trees). */
export function setShow3dObjects(map: ConfigurableMap | null | undefined, show: boolean): void {
  try {
    map?.setConfigProperty("basemap", "show3dObjects", show);
  } catch {
    /* no-op until style loads */
  }
}

/** Set a Standard basemap config property (label groups etc.). Safe after load. */
export function setStandardConfig(map: ConfigurableMap | null | undefined, prop: string, value: boolean): void {
  try {
    map?.setConfigProperty("basemap", prop, value);
  } catch {
    /* no-op until style loads */
  }
}
