/**
 * Cross-street resolution via the Mapbox Tilequery API.
 *
 * `describeSegment` (api/graph.ts) names cross-streets from local graph
 * adjacency alone. When an endpoint has no usable incident road name (e.g. the
 * cross-street isn't in the loaded graph), we fall back to a Tilequery lookup
 * against `mapbox.mapbox-streets-v8` to find the nearest road by name.
 *
 * Tilequery API: https://docs.mapbox.com/api/maps/tilequery/
 */
import {
  type SegmentDescription,
  type RoadGraph,
  describeSegment,
  getEdge,
  buildSegmentLabel,
} from "../api/graph";
import { MAPBOX_TOKEN } from "./mapbox";

/** Cache by rounded coords + exclude set: in-flight promise then resolved value. */
const cache = new Map<string, Promise<string | null> | (string | null)>();

/**
 * Nearest distinct road name (not in `excludeNames`) within ~30 m of (lng, lat),
 * via Tilequery. Returns null when there's no token, on any error, or no match.
 */
export async function mapboxCrossStreet(
  lng: number,
  lat: number,
  excludeNames: string[] = [],
): Promise<string | null> {
  if (!MAPBOX_TOKEN) return null;
  const excludeKey = excludeNames.map((s) => s.toLowerCase()).sort().join("|");
  const key = `${lng.toFixed(5)},${lat.toFixed(5)}|${excludeKey}`;
  const cached = cache.get(key);
  if (cached !== undefined) return await cached;

  const exclude = new Set(excludeNames.map((s) => s.toLowerCase()));
  const p = (async () => {
    try {
      const url = `https://api.mapbox.com/v4/mapbox.mapbox-streets-v8/tilequery/${lng},${lat}.json?radius=30&limit=8&layers=road&geometry=linestring&access_token=${MAPBOX_TOKEN}`;
      const res = await fetch(url);
      if (!res.ok) return null;
      const data = await res.json();
      // Features come back sorted nearest-first.
      for (const f of data?.features ?? []) {
        const name: string | undefined = f?.properties?.name;
        if (name && !exclude.has(name.toLowerCase())) return name;
      }
      return null;
    } catch {
      return null;
    }
  })();

  cache.set(key, p);
  const val = await p;
  cache.set(key, val); // collapse to resolved value
  return val;
}

/**
 * Like {@link describeSegment} but fills any missing cross-street ends via
 * Tilequery, then recomputes the label. Falls back to the local result on error.
 */
export async function describeSegmentAsync(
  graph: RoadGraph,
  edgeId: string,
): Promise<SegmentDescription> {
  const base = describeSegment(graph, edgeId);
  if (base.fromCross && base.toCross) return base;

  const seg = getEdge(graph, edgeId);
  if (!seg) return base;

  let { fromCross, toCross } = base;
  const fromN = graph.nodes.get(seg.fromKey);
  const toN = graph.nodes.get(seg.toKey);

  if (!fromCross && fromN) {
    const ex = [base.road, toCross].filter(Boolean) as string[];
    fromCross = await mapboxCrossStreet(fromN.lng, fromN.lat, ex);
  }
  if (!toCross && toN) {
    const ex = [base.road, fromCross].filter(Boolean) as string[];
    toCross = await mapboxCrossStreet(toN.lng, toN.lat, ex);
  }

  return {
    road: base.road,
    fromCross,
    toCross,
    label: buildSegmentLabel(base.road, fromCross, toCross),
  };
}
