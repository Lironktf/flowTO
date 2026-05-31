/**
 * Frontend road-graph layer — the team's agreed vocabulary over the live graph.
 *
 *   Vertex (V) = intersection/connection      Edge (E) = street
 *   Segment    = an edge between two vertices  Subsegment = a slice of the edge
 *                                              geometry coordinate list ("grid points")
 *
 * The backend `/edges` payload (see api/client.ts `EdgeMeta`) gives geometry as
 * `[lat, lng]` coordinate lists but NOT from/to node ids. Intersections in the
 * source graph share *exact* endpoint coordinates, so we reconstruct vertices and
 * adjacency by hashing the first/last geometry coordinate of every edge — no
 * backend change required. (If the backend later returns node ids + coords, swap
 * `coordKey(endpoints)` for those ids and the rest of this module is unchanged.)
 */
import { api, type EdgeMeta, type Intervention, type RestrictedRoad } from "./client";

export type NodeKey = string;

/** A reconstructed intersection. */
export interface GraphNode {
  key: NodeKey;
  lng: number;
  lat: number;
  edgeIds: string[];
}

/** A street segment (== one directed graph edge between two intersections). */
export interface Segment {
  edge_id: string;
  idx: number;
  road_name?: string;
  road_class?: string;
  restricted?: RestrictedRoad; // set on MTO highways / municipal expressways
  geometry: [number, number][]; // [lat, lng], as stored upstream
  fromKey: NodeKey;
  toKey: NodeKey;
}

export interface RoadGraph {
  edges: Segment[];
  byId: Map<string, Segment>;
  byIdx: Map<number, Segment>;
  nodes: Map<NodeKey, GraphNode>;
}

/** Quantize a [lat, lng] coordinate into a stable vertex key. */
export function coordKey(lat: number, lng: number): NodeKey {
  return `${lat.toFixed(6)},${lng.toFixed(6)}`;
}

/** Equirectangular distance (metres) — fine for the city-scale comparisons here. */
function metres(aLat: number, aLng: number, bLat: number, bLng: number): number {
  const R = 6371000;
  const x = (((bLng - aLng) * Math.PI) / 180) * Math.cos(((aLat + bLat) * Math.PI) / 360);
  const y = ((bLat - aLat) * Math.PI) / 180;
  return Math.sqrt(x * x + y * y) * R;
}

/** Total length (metres) of a segment's polyline. */
export function segmentLength(seg: Segment): number {
  let total = 0;
  for (let i = 1; i < seg.geometry.length; i++) {
    const [aLat, aLng] = seg.geometry[i - 1];
    const [bLat, bLng] = seg.geometry[i];
    total += metres(aLat, aLng, bLat, bLng);
  }
  return total;
}

/** Build the vertex/adjacency index from the loaded edges. */
export function buildGraph(edges: EdgeMeta[]): RoadGraph {
  const segs: Segment[] = [];
  const byId = new Map<string, Segment>();
  const byIdx = new Map<number, Segment>();
  const nodes = new Map<NodeKey, GraphNode>();

  const touch = (key: NodeKey, lat: number, lng: number, edgeId: string) => {
    let n = nodes.get(key);
    if (!n) {
      n = { key, lat, lng, edgeIds: [] };
      nodes.set(key, n);
    }
    n.edgeIds.push(edgeId);
  };

  for (const e of edges) {
    if (!e.geometry || e.geometry.length < 2) continue;
    const [aLat, aLng] = e.geometry[0];
    const [bLat, bLng] = e.geometry[e.geometry.length - 1];
    const fromKey = coordKey(aLat, aLng);
    const toKey = coordKey(bLat, bLng);
    const seg: Segment = {
      edge_id: e.edge_id,
      idx: e.idx,
      road_name: e.road_name,
      road_class: e.road_class,
      restricted: e.restricted,
      geometry: e.geometry,
      fromKey,
      toKey,
    };
    segs.push(seg);
    byId.set(seg.edge_id, seg);
    byIdx.set(seg.idx, seg);
    touch(fromKey, aLat, aLng, seg.edge_id);
    touch(toKey, bLat, bLng, seg.edge_id);
  }

  return { edges: segs, byId, byIdx, nodes };
}

/** Load the graph from the API and build the index. */
export async function loadGraph(): Promise<{ raw: EdgeMeta[]; graph: RoadGraph }> {
  const { edges } = await api.edges();
  return { raw: edges, graph: buildGraph(edges) };
}

// ── Agreed read API ──────────────────────────────────────────────────────────

/** getE(): all edges/segments. Neighbours are reachable via {@link neighboursOfEdge}. */
export function getE(graph: RoadGraph): Segment[] {
  return graph.edges;
}

/** getEdge(E): one segment by edge id. */
export function getEdge(graph: RoadGraph, edgeId: string): Segment | undefined {
  return graph.byId.get(edgeId);
}

/** getSegment(E): same object as the edge (one segment per edge). */
export const getSegment = getEdge;

/** getSubSegment(segment, i, j): a slice of the geometry "grid points" [lat,lng]. */
export function getSubSegment(seg: Segment, startIdx = 0, endIdx?: number): [number, number][] {
  return seg.geometry.slice(startIdx, endIdx);
}

/** All edges incident to a vertex (i.e. getEdge(V)). */
export function edgesAtNode(graph: RoadGraph, key: NodeKey): Segment[] {
  const n = graph.nodes.get(key);
  if (!n) return [];
  return n.edgeIds.map((id) => graph.byId.get(id)).filter((s): s is Segment => !!s);
}

/** Neighbouring edges of E — edges sharing either endpoint vertex with E. */
export function neighboursOfEdge(graph: RoadGraph, edgeId: string): Segment[] {
  const seg = graph.byId.get(edgeId);
  if (!seg) return [];
  const out = new Map<string, Segment>();
  for (const key of [seg.fromKey, seg.toKey]) {
    for (const nb of edgesAtNode(graph, key)) {
      if (nb.edge_id !== edgeId) out.set(nb.edge_id, nb);
    }
  }
  return [...out.values()];
}

/** Nearest vertex to a click (lng, lat) — used to snap closures/surges. */
export function nearestNode(graph: RoadGraph, lng: number, lat: number): GraphNode | null {
  let best: GraphNode | null = null;
  let bd = Infinity;
  for (const n of graph.nodes.values()) {
    const d = metres(lat, lng, n.lat, n.lng);
    if (d < bd) {
      bd = d;
      best = n;
    }
  }
  return best;
}

/** Nearest edge to a click (lng, lat), by closest geometry vertex. */
export function nearestEdge(graph: RoadGraph, lng: number, lat: number): Segment | null {
  let best: Segment | null = null;
  let bd = Infinity;
  for (const seg of graph.edges) {
    for (const [gLat, gLng] of seg.geometry) {
      const d = (gLng - lng) ** 2 + (gLat - lat) ** 2;
      if (d < bd) {
        bd = d;
        best = seg;
      }
    }
  }
  return best;
}

// ── Compass / direction helpers (which streets a demand point affects) ────────

export type Compass = "n" | "e" | "s" | "w";

/** Initial compass bearing (degrees, 0=N, clockwise) of the ray a→b. */
function bearingDeg(aLat: number, aLng: number, bLat: number, bLng: number): number {
  const toRad = Math.PI / 180;
  const φ1 = aLat * toRad;
  const φ2 = bLat * toRad;
  const Δλ = (bLng - aLng) * toRad;
  const y = Math.sin(Δλ) * Math.cos(φ2);
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);
  return (Math.atan2(y, x) * 180) / Math.PI;
}

/** Bucket a compass bearing into the nearest cardinal direction. */
export function compassOf(bearing: number): Compass {
  const b = ((bearing % 360) + 360) % 360;
  if (b >= 315 || b < 45) return "n";
  if (b < 135) return "e";
  if (b < 225) return "s";
  return "w";
}

/** A street leaving a vertex, oriented outward from it. */
export interface DirectedStreet {
  dir: Compass;
  edge_id: string;
  road_name?: string;
  /** Polyline as [lng, lat], ordered from the anchor vertex outward. */
  path: [number, number][];
}

/**
 * The streets radiating from a vertex, each oriented so its polyline starts at
 * the vertex and heads outward, keyed by the cardinal direction it leaves in.
 * When two streets leave in the same direction the longer one wins, so a demand
 * point resolves to one representative street per N/E/S/W.
 */
export function streetsByDirection(graph: RoadGraph, key: NodeKey): Partial<Record<Compass, DirectedStreet>> {
  const out: Partial<Record<Compass, DirectedStreet>> = {};
  const seen = new Set<string>();
  for (const seg of edgesAtNode(graph, key)) {
    if (seen.has(seg.edge_id) || seg.geometry.length < 2) continue;
    seen.add(seg.edge_id);
    // Orient the geometry so it starts at the anchor vertex.
    const geom = seg.fromKey === key ? seg.geometry : [...seg.geometry].reverse();
    const [aLat, aLng] = geom[0];
    const [bLat, bLng] = geom[1];
    const dir = compassOf(bearingDeg(aLat, aLng, bLat, bLng));
    const path = geom.map(([la, ln]) => [ln, la] as [number, number]);
    const cur = out[dir];
    if (!cur || path.length > cur.path.length) {
      out[dir] = { dir, edge_id: seg.edge_id, road_name: seg.road_name, path };
    }
  }
  return out;
}

/**
 * Resolve the corridor of edges connecting two vertices — the shortest path by
 * road length (Dijkstra over the undirected vertex graph). Closing these seals
 * the segment between the two intersections: cross-streets touching interior
 * vertices stay open but dead-end at the closure, as does the street itself.
 */
export function corridorBetween(graph: RoadGraph, fromKey: NodeKey, toKey: NodeKey): Segment[] {
  if (fromKey === toKey) return [];
  const dist = new Map<NodeKey, number>([[fromKey, 0]]);
  const prevEdge = new Map<NodeKey, Segment>();
  const visited = new Set<NodeKey>();
  // Simple priority frontier (graph is large but corridors are short/local).
  const frontier = new Set<NodeKey>([fromKey]);

  while (frontier.size) {
    let u: NodeKey | null = null;
    let ud = Infinity;
    for (const k of frontier) {
      const d = dist.get(k) ?? Infinity;
      if (d < ud) {
        ud = d;
        u = k;
      }
    }
    if (u == null) break;
    frontier.delete(u);
    if (u === toKey) break;
    visited.add(u);

    for (const seg of edgesAtNode(graph, u)) {
      const v = seg.fromKey === u ? seg.toKey : seg.fromKey;
      if (visited.has(v)) continue;
      const nd = ud + segmentLength(seg);
      if (nd < (dist.get(v) ?? Infinity)) {
        dist.set(v, nd);
        prevEdge.set(v, seg);
        frontier.add(v);
      }
    }
  }

  if (!prevEdge.has(toKey)) return [];
  const path: Segment[] = [];
  let cur = toKey;
  while (cur !== fromKey) {
    const seg = prevEdge.get(cur);
    if (!seg) return [];
    path.push(seg);
    cur = seg.fromKey === cur ? seg.toKey : seg.fromKey;
  }
  return path.reverse();
}

/** Include reverse-direction twins of the given segments (same vertex pair). */
export function withReverseTwins(graph: RoadGraph, segs: Segment[]): Segment[] {
  const out = new Map<string, Segment>();
  for (const seg of segs) {
    out.set(seg.edge_id, seg);
    for (const nb of edgesAtNode(graph, seg.fromKey)) {
      if (nb.toKey === seg.fromKey && nb.fromKey === seg.toKey) out.set(nb.edge_id, nb);
    }
  }
  return [...out.values()];
}

// ── Agreed mutation API (returns interventions; apply via a scenario run) ─────

/** blockSegment(segment): close one street segment to all traffic. */
export function blockSegment(seg: Segment): Intervention {
  return { op: "close_edge", edge_id: seg.edge_id };
}

/** deleteStreet(E): remove a street from the graph entirely. */
export function deleteStreet(edgeId: string): Intervention {
  return { op: "remove_edge", edge_id: edgeId };
}

/** addNewStreet(E, V, segment): add a new street/edge (optionally mid-segment). */
export function addNewStreet(opts: {
  from_node: number;
  to_node: number;
  road_name?: string;
  speed_kmh?: number;
  lanes?: number;
  capacity?: number;
}): Intervention {
  return { op: "add_edge", ...opts };
}

/** Demand surge at a vertex (backend support pending — see api/client.ts). */
export function demandSurge(nodeId: number, amount: number, mode: "absolute" | "relative"): Intervention {
  return { op: "demand_surge", node_id: nodeId, amount, mode };
}

// ── Segment description (human-readable "Road — A → B" labels) ────────────────

/** A human-readable description of a selected segment. */
export interface SegmentDescription {
  road: string;
  fromCross: string | null;
  toCross: string | null;
  label: string;
}

/** Word-boundary suffix/direction abbreviations for compact street labels. */
const SHORT_NAME_RULES: [RegExp, string][] = [
  [/\bBoulevard\b/gi, "Blvd"],
  [/\bCrescent\b/gi, "Cres"],
  [/\bAvenue\b/gi, "Ave"],
  [/\bStreet\b/gi, "St"],
  [/\bRoad\b/gi, "Rd"],
  [/\bDrive\b/gi, "Dr"],
  [/\bCourt\b/gi, "Crt"],
  [/\bWest\b/gi, "W"],
  [/\bEast\b/gi, "E"],
  [/\bNorth\b/gi, "N"],
  [/\bSouth\b/gi, "S"],
];

/** Abbreviate common street suffixes/directions for compact labels. Pure & local. */
export function shortName(name: string): string {
  let out = name;
  for (const [re, rep] of SHORT_NAME_RULES) out = out.replace(re, rep);
  return out;
}

/** Shared label builder so describeSegment & describeSegmentAsync never drift. */
export function buildSegmentLabel(
  road: string,
  fromCross: string | null,
  toCross: string | null,
): string {
  if (fromCross && toCross) return `${road} — ${shortName(fromCross)} → ${shortName(toCross)}`;
  const one = fromCross ?? toCross;
  if (one) return `${road} — at ${shortName(one)}`;
  return road;
}

/** Describe a segment from local graph adjacency (no network). */
export function describeSegment(graph: RoadGraph, edgeId: string): SegmentDescription {
  const seg = graph.byId.get(edgeId);
  if (!seg) {
    return { road: "Selected road", fromCross: null, toCross: null, label: "Selected road" };
  }
  const road = seg.road_name ?? "Selected road";

  /** Most common incident road name at a vertex, excluding `road` (case-insensitive). */
  const crossAt = (key: NodeKey): string | null => {
    const counts = new Map<string, number>();
    let best: string | null = null;
    let bestCount = 0;
    for (const nb of edgesAtNode(graph, key)) {
      const name = nb.road_name;
      if (!name || !name.trim()) continue;
      if (name.toLowerCase() === road.toLowerCase()) continue;
      const next = (counts.get(name) ?? 0) + 1;
      counts.set(name, next);
      if (next > bestCount) {
        bestCount = next;
        best = name;
      }
    }
    return best;
  };

  const fromCross = crossAt(seg.fromKey);
  const toCross = crossAt(seg.toKey);
  return { road, fromCross, toCross, label: buildSegmentLabel(road, fromCross, toCross) };
}
