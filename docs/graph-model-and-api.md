# flowTO / TorontoSim — Graph Model & Backend↔Frontend Interface

> Canonical design doc for the backend↔frontend contract.
> Reconciles the whiteboard session with the *TorontoSim Final Technical Specification*.
> **Source of truth for terminology and API shape.**

---

## 1. Graph model — the "pro" approach

We use the **primal road graph** as the stored, rendered, and reasoned-about model, exactly
like OpenStreetMap, Google Maps, OSRM, Valhalla, and the Toronto Centreline dataset itself:

| Concept | Is a | Carries |
|---|---|---|
| **Node / vertex** | an **intersection** | `node_id`, lat/lon (WGS84), signal timing, intersection class |
| **Edge** | a **directed street segment** | capacity, free-flow time, length, road class, lanes, one-way, bridge flag, live load/pressure/speed |

```
 (intersection A) ───King St segment──▶ (intersection B) ───King St segment──▶ (intersection C)
      NODE                EDGE                 NODE                EDGE                NODE
```

Key consequences:

- **A "street" is not one object.** A long road (King St) is a **chain of edges**, one per block,
  broken at every intersection. ("Segment each long road" from the whiteboard.)
- **Traffic lives on edges.** `load`, `capacity`, `pressure = load/capacity`, `speed`, `travel_time`
  are all per-edge. The congestion heatmap colors **edges**.
- **Node coordinates solve "where is a street?"** — every node has lat/lon, so the frontend never
  has to guess geometry.

### Turn modeling — the pro trick

We do **not** invert to a line graph (node = street, edge = intersection). Instead, turns are
modeled the way production routers do it: a **turn table** layered on the primal graph, and the
router internally compiles an edge-based graph *only when turn penalties matter*.

```
turn table:  (edge_in, node, edge_out) -> { penalty_seconds, banned: bool }

# e.g. no left from King onto Bay:
("King_AB", "node_B", "Bay_BX") -> { banned: true }
```

This matters because our demand data (**TMC = Turning Movement Counts**) is turn-shaped, so the
turn table is also where TMC calibration naturally lands. We get full turn-restriction support
**without** inverting data, rendering, or ingest.

> Rejected alternative: pure line graph. Valid in theory (it's the graph-theory *dual*), but it
> fights Centreline ingest, deck.gl road rendering, and every standard tool. Pros store primal and
> derive the line graph internally — so do we.

---

## 2. Two kinds of "weight" — don't conflate them

The whiteboard had a single "weighting." There are actually two:

| Kind | Fields | Source | Changes when |
|---|---|---|---|
| **Static** | `capacity`, `free_flow_time`, `lanes`, `length` | ingest (Centreline + defaults) | graph is edited |
| **Dynamic** | `load`, `pressure`, `speed`, `travel_time` | a **simulation run** | a sim runs for a time slice |

`getSegmentWeight()` is ambiguous — split into "get edge attributes" (static) and "read dynamic
state from a sim frame" (dynamic, streamed — see §5).

---

## 3. Edits vs. interventions — two different write paths

The whiteboard only had `addNewStreet` (a permanent mutation). The spec needs **two** paths:

| | Graph edit | Intervention (scenario overlay) |
|---|---|---|
| Example | add/remove a street, add intersection | close road, drop a lane, retime signal, temporary one-way |
| Permanence | **permanent** structural change | **temporary** override on top of the graph |
| Preview | n/a | **preview-before-apply is mandatory** |
| Shape | nodes + edges | `{intervention_type, edge_ids[], start_time, end_time, capacity_multiplier, requires_user_confirmation}` |

Interventions never mutate the base graph — they're masks the simulator applies for a scenario.

---

## 4. Simulation is asynchronous — not a getter

The single biggest gap on the whiteboard ("Frontend (Sim)" was empty). Simulation is a **long GPU
job**, so:

- Frontend **starts** a sim (HTTP) → gets a `job_id`.
- Backend emits **progress events**, then streams result frames.
- **Input to a sim is a time slice + scenario**, NOT the graph:
  - `time_bin` (15-min) + `day_of_week` → selects the **OD demand bundles**.
  - active interventions → scenario overlay.
- **Output is partial (blast radius):** only affected edges + boundary region come back, not the
  whole city. Frontend must handle partial updates.

---

## 5. The interface (HTTP for control, WebSocket for frames)

> Rule of thumb (from spec §5): **HTTP/JSON for slow control calls, WebSocket binary for tick frames.**

### HTTP — graph (read)
| Method | Endpoint | Returns |
|---|---|---|
| `GET` | `/graph/nodes` | all intersections (id, lat/lon, class) |
| `GET` | `/graph/edges` | all street segments (id, endpoints, static attrs) |
| `GET` | `/graph/nodes/{id}/edges` | edges incident to a node (the "neighbours" call) |
| `GET` | `/graph/edges/{id}` | one edge's static attributes + confidence |

### HTTP — graph (write, permanent)
| Method | Endpoint | Body |
|---|---|---|
| `POST` | `/graph/streets` | `{ nodes:[...], edges:[...] }` — adds a street as a node+edge chain |
| `DELETE` | `/graph/edges/{id}` | remove a segment |

### HTTP — interventions (scenario, previewed)
| Method | Endpoint | Body / returns |
|---|---|---|
| `POST` | `/scenario/preview` | intervention object → preview (affected edge_ids, no commit) |
| `POST` | `/scenario/apply` | confirmed intervention → scenario_id |
| `POST` | `/scenario/{id}/simulate` | `{ time_bin, day_of_week }` → `{ job_id }` |
| `GET` | `/scenario/compare?a=&b=` | before/after metrics (see below) |

### WebSocket — live sim frames
```
ws://.../sim/{job_id}
  → { type: "progress", pct }
  → { type: "frame", edges: [ {edge_id, load, speed, pressure, closure_state}, ... ] }   # binary in prod
  → { type: "done", affected: {nodes, edges}, recompute_ms }
```

### Before/after metrics (compare response)
`total_delay`, `mean_travel_time`, `p95_travel_time`, `congested_edge_count`,
`local_road_infiltration`, plus any `budget/constraint warnings`.

---

## 6. Cross-cutting requirements (don't forget)

- **Confidence labels** (`observed | inferred | default | manual`) round-trip to the UI on edge reads.
- **Preview-before-apply** on every mutation and intervention.
- **IDs are opaque** — use real Centreline IDs (e.g. `13467077`); don't reindex.
- **Congestion color** is derived from `pressure = load/capacity`; agree green/amber/red cutoffs.
- **Legality checks** (road vs. bridge — `bridges-elevated-roadways-and-culverts`) gate adds/edits.

---

## 7. Whiteboard → this doc (what changed)

| Whiteboard | Status | Resolution |
|---|---|---|
| "Vertices/Node: Street, Edge: intersection" (left board) | ❌ inverted | node = intersection, edge = street |
| "neighbouring edges (aka all streets)" (right board) | ✅ correct | `GET /graph/nodes/{id}/edges` |
| `getEdge(V)`, `getV()` | ✅ | graph read endpoints |
| `addNewStreet(V,E)` | ⚠️ partial | street = node+edge **chain**; edges have no `name` |
| `getSegment`, `getSegmentWeight` | ⚠️ split | static attrs (HTTP) vs dynamic state (WS frame) |
| "Frontend (Sim)" | ❌ empty | async job + WebSocket frames + OD/time-slice input |
| "legality of adding V+edge (road vs bridge)" | ✅ | bridge constraint gate |
| "how to know where street is" | ✅ solved | nodes carry lat/lon |
| line-graph idea | ➡️ replaced | primal graph + turn table (the pro way) |
