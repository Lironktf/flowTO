/**
 * Map search — powers the topbar omnibox (fly-to navigation).
 *
 * Two sources, merged in the UI:
 *   1. A local road index built from the loaded RoadGraph (instant, offline) —
 *      every named street, with a representative [lng, lat] and an edge_id so a
 *      hit can also be highlighted via selectRoad().
 *   2. Mapbox Geocoding (neighborhoods, landmarks, addresses) — bbox-biased to
 *      Toronto. Only called when a token is present.
 */
import { MAPBOX_TOKEN } from "./mapbox";
import { TORONTO_BBOX } from "../config";
import type { RoadGraph } from "../api/graph";

/** [[west, south], [east, north]] in lng/lat — a Mapbox fitBounds-ready box. */
export type BBox = [[number, number], [number, number]];

export interface SearchHit {
  id: string;
  /** Display name. */
  label: string;
  /** "street" (local graph) or a Mapbox place kind ("place", "poi", "address", …). */
  kind: string;
  /** [lng, lat] for the camera (point fly-to / fallback). [0,0] for place hits until retrieved. */
  coord: [number, number];
  /** Streets: the whole road's extent, so the camera frames the entire street. */
  bbox?: BBox;
  /** Present for local streets so the result can highlight the road. */
  edgeId?: string;
  /** Place hits: the Search Box id; coords are fetched via retrievePlace() on selection. */
  mapboxId?: string;
  /** Closer ≈ better when ranking; lower is better. */
  score: number;
}

export interface RoadIndexEntry {
  name: string;
  lower: string;
  edgeId: string;
  coord: [number, number]; // bbox center
  bbox: BBox; // full extent of every segment sharing this name
}

/**
 * One entry per unique road name, with the bounding box spanning ALL segments
 * of that name — so a hit can frame the entire street, not one block.
 * (geometry is stored as [lat, lng]; bbox/coord are emitted as [lng, lat].)
 */
export function buildRoadIndex(graph: RoadGraph): RoadIndexEntry[] {
  interface Acc {
    name: string;
    edgeId: string;
    minLng: number;
    minLat: number;
    maxLng: number;
    maxLat: number;
  }
  const acc = new Map<string, Acc>();
  for (const seg of graph.edges) {
    const name = seg.road_name?.trim();
    if (!name) continue;
    const key = name.toLowerCase();
    let a = acc.get(key);
    if (!a) {
      a = { name, edgeId: seg.edge_id, minLng: Infinity, minLat: Infinity, maxLng: -Infinity, maxLat: -Infinity };
      acc.set(key, a);
    }
    for (const [lat, lng] of seg.geometry) {
      if (lng < a.minLng) a.minLng = lng;
      if (lat < a.minLat) a.minLat = lat;
      if (lng > a.maxLng) a.maxLng = lng;
      if (lat > a.maxLat) a.maxLat = lat;
    }
  }
  const out: RoadIndexEntry[] = [];
  for (const [lower, a] of acc) {
    if (!Number.isFinite(a.minLng)) continue;
    out.push({
      name: a.name,
      lower,
      edgeId: a.edgeId,
      coord: [(a.minLng + a.maxLng) / 2, (a.minLat + a.maxLat) / 2],
      bbox: [
        [a.minLng, a.minLat],
        [a.maxLng, a.maxLat],
      ],
    });
  }
  out.sort((a, b) => a.name.localeCompare(b.name));
  return out;
}

/** Rank local streets: prefix matches beat substring matches; shorter names win ties. */
export function searchRoads(index: RoadIndexEntry[], query: string, limit = 6): SearchHit[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const hits: SearchHit[] = [];
  for (const e of index) {
    const at = e.lower.indexOf(q);
    if (at === -1) continue;
    // prefix (0) ranks above interior; tie-break by name length.
    const score = (at === 0 ? 0 : 100) + at + e.name.length / 100;
    hits.push({
      id: `road:${e.edgeId}`,
      label: e.name,
      kind: "street",
      coord: e.coord,
      bbox: e.bbox,
      edgeId: e.edgeId,
      score,
    });
    if (hits.length > 200) break; // cap scan cost on very short queries
  }
  hits.sort((a, b) => a.score - b.score);
  return hits.slice(0, limit);
}

interface Suggestion {
  name?: string;
  mapbox_id?: string;
  feature_type?: string;
}
interface RetrieveFeature {
  geometry?: { coordinates?: [number, number] }; // [lng, lat]
  properties?: { name?: string };
}

// One Search Box session groups a /suggest + /retrieve pair for billing. Stable per page load.
const SESSION_TOKEN =
  typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `s-${Date.now()}`;

/** Feature-type preference — landmarks/areas beat addresses/categories. Lower = better. */
const TYPE_BIAS: Record<string, number> = {
  poi: 0,
  neighborhood: 1,
  place: 2,
  locality: 2,
  district: 2,
  postcode: 5,
  street: 6,
  address: 8,
  category: 12,
};

/**
 * Relevance score for a place result (lower = better). Favors a hit whose name
 * actually matches the query — so "CN Tower" beats "360 The Restaurant at the CN
 * Tower" — then biases by feature type, original API order, and shorter names.
 * Pure + deterministic (unit-tested).
 */
export function placeScore(name: string, kind: string, query: string, apiOrder: number): number {
  const n = name.toLowerCase();
  const q = query.trim().toLowerCase();
  let s: number;
  if (n === q) s = 0; // exact name match — the thing you searched for
  else if (n.startsWith(q)) s = 10;
  else if (n.includes(q)) s = 26; // query buried inside a longer name (a business "at the X")
  else s = 60; // query not in the name at all — tangential
  s += TYPE_BIAS[kind] ?? 5;
  s += apiOrder * 0.5; // keep some of Mapbox's own ranking as a tiebreak
  s += name.length / 200; // nudge toward shorter, cleaner names
  return s;
}

/**
 * Mapbox Search Box (suggest) for landmarks / POIs / neighborhoods / addresses,
 * biased to Toronto. /suggest ranks named places correctly (e.g. "CN Tower" leads,
 * not "360 The Restaurant at the CN Tower" — which /forward gets wrong). Suggestions
 * carry no coordinates; retrievePlace() fetches them on selection. Re-ranked by
 * placeScore for an extra nudge toward the searched-for name.
 */
export async function geocodePlaces(query: string, signal: AbortSignal, limit = 5): Promise<SearchHit[]> {
  const q = query.trim();
  if (!q || !MAPBOX_TOKEN) return [];
  const [minLng, minLat, maxLng, maxLat] = TORONTO_BBOX;
  const url =
    `https://api.mapbox.com/search/searchbox/v1/suggest?q=${encodeURIComponent(q)}` +
    `&access_token=${MAPBOX_TOKEN}&session_token=${SESSION_TOKEN}&country=ca&limit=${limit}` +
    `&bbox=${minLng},${minLat},${maxLng},${maxLat}` +
    `&proximity=${(minLng + maxLng) / 2},${(minLat + maxLat) / 2}`;
  const r = await fetch(url, { signal });
  if (!r.ok) throw new Error(`searchbox → ${r.status}`);
  const data = (await r.json()) as { suggestions?: Suggestion[] };
  const hits: SearchHit[] = [];
  const list = data.suggestions ?? [];
  for (let i = 0; i < list.length; i++) {
    const s = list[i];
    if (!s.name || !s.mapbox_id) continue;
    const kind = s.feature_type ?? "place";
    hits.push({
      id: `place:${s.mapbox_id}`,
      label: s.name,
      kind,
      coord: [0, 0], // resolved on selection
      mapboxId: s.mapbox_id,
      score: placeScore(s.name, kind, q, i),
    });
  }
  hits.sort((a, b) => a.score - b.score);
  return hits;
}

/** Resolve a suggestion's coordinates ([lng, lat]) for the camera, on selection. */
export async function retrievePlace(mapboxId: string, signal: AbortSignal): Promise<[number, number] | null> {
  if (!MAPBOX_TOKEN) return null;
  const url =
    `https://api.mapbox.com/search/searchbox/v1/retrieve/${encodeURIComponent(mapboxId)}` +
    `?access_token=${MAPBOX_TOKEN}&session_token=${SESSION_TOKEN}`;
  const r = await fetch(url, { signal });
  if (!r.ok) return null;
  const data = (await r.json()) as { features?: RetrieveFeature[] };
  const c = data.features?.[0]?.geometry?.coordinates;
  return c ? [c[0], c[1]] : null;
}

/** Merge local + place hits, dropping case-insensitive label duplicates (keeps the first). */
export function dedupeHits(hits: SearchHit[], limit = 8): SearchHit[] {
  const seen = new Set<string>();
  const out: SearchHit[] = [];
  for (const h of hits) {
    const key = h.label.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(h);
    if (out.length >= limit) break;
  }
  return out;
}
