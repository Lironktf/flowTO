# P02 — Road graph: OSMnx baseline + Centreline loader + capacity/confidence

| | |
|---|---|
| **Priority** | Core |
| **Depends on** | P00, P01 |
| **Owner hint** | Data/sim owner |
| **Status** | not started |

## Goal
Harden Liron's OSMnx graph as the **baseline**, and add a **Centreline-based loader** as a higher-fidelity,
spec-aligned alternative behind a `graph_source` flag — both producing the **same enriched edge schema** so the
rest of the pipeline (routing, mutations, simulation) is source-agnostic. Add per-edge **confidence labels** and
calibrated capacity.

**Why / rubric tie-in:** Technical depth + Insight quality. Centreline gives official Toronto geometry whose IDs
link directly to TMC counts + road restrictions; confidence labels are a credibility feature for planners.

## Current state (Liron's prototype)
- `graph/build_graph.py` (OSMnx download → enrich → save graphml+json), `graph/config.py` (capacity/speed/lane defaults by road class, haversine, base-time), `graph/routing.py` (edge index, nearest-node/edge, Dijkstra, JSON I/O), `graph/mutations.py` (close/reopen/remove/capacity/close_node/add_edge). Downtown 7 km, 6834 nodes / 18190 edges, directed `MultiDiGraph`. Capacity = lanes × veh/hr/lane (HCM-ish defaults). No Centreline, no confidence labels.

## Target state
- `graph_source` flag: `osmnx` (baseline) | `centreline` (new). Both emit the **canonical edge schema** Liron already uses: `edge_id, from_node, to_node, road_name, road_class, length_m, one_way, speed_kmh, lanes, capacity, base_time_min, current_time_min, status, load, pressure, geometry`.
- **Confidence label** per inferred field: `observed | inferred | default | manual` (esp. lanes/speed/capacity).
- Capacity **calibrated** against TMC peak counts where a `centreline_id`/`px` match exists.
- Centreline edges keep `CENTRELINE_ID` (links TMC + restrictions); intersections → nodes.

### In scope
Centreline→graph loader; canonical-schema parity; confidence labels; capacity calibration hook; oneway from TCL `ONEWAY_DIR_CODE`; bridges `VERT_CLEAR` as height attr.
### Out of scope
Routing/mutation logic (unchanged — already generic). GPU graph (P04). Citywide scale tuning (start at the spec's coverage; expand if perf allows).

## Design / implementation plan
1. **Canonical schema module** (`graph/schema.py`) — one place defining the edge/node fields + `confidence`; both loaders conform; add a `validate_graph(g)` used by tests.
2. **Centreline loader** (`graph/centreline_loader.py`) — read baked GeoParquet (P01): TCL segments → directed edges (split bidirectional into two; honor `ONEWAY_DIR_CODE`); Intersection file → nodes (dedupe multi-level on `INTERSECTION_ID`); filter `FEATURE_CODE_DESC` to road classes; map TCL class → `config` speed/lane/capacity defaults (label `inferred`/`default`); attach bridges `VERT_CLEAR`.
3. **Confidence labels** — when a value comes from source data → `observed`; from class default → `default`; from a heuristic → `inferred`; manual override → `manual`. Stored per edge; surfaced to the frontend later.
4. **Capacity calibration hook** (`graph/calibrate_capacity.py`) — for edges with a TMC match, nudge `capacity`/`speed` toward observed peak throughput; flag adjusted edges `observed`. (Light; full ODME is P03/P04.)
5. **Keep OSMnx loader** as-is but route it through `schema.validate_graph`; add confidence labels (mostly `inferred`/`default`).
6. **Builder CLI** — `python -m torontosim.graph.build --source {osmnx,centreline} --place "Toronto" --out data/graph/…`.

## Data / models / sources
`research/01` (TCL `CENTRELINE_ID`/`ONEWAY_DIR_CODE`, Intersection `INTERSECTION_ID`, TMC join keys `centreline_id`/`px`, bridges `VERT_CLEAR`, road-class filtering). Liron's `config.py` defaults (saturation flow, free-flow speed, lanes by class) are the calibration priors.

## Files to create / modify
**Create:** `src/torontosim/graph/schema.py`, `centreline_loader.py`, `calibrate_capacity.py`, `build.py` (CLI); `tests/test_graph_schema.py`, `tests/test_centreline_loader.py`.
**Modify:** `graph/build_graph.py` (route through schema + confidence), `graph/config.py` (expose calibration priors + α/β hook for P04), `graph/routing.py` (no logic change; ensure works with both sources).

## Test-driven design
- `test_graph_schema.py` (first): `validate_graph` rejects an edge missing `capacity`/`confidence`; both loaders' output passes.
- `test_centreline_loader.py`: on a small committed TCL+Intersection fixture (a few blocks), build graph → assert oneway directionality matches `ONEWAY_DIR_CODE`; node count = deduped intersections; every edge has a `confidence`.
- **Parity test:** an OSMnx graph and a Centreline graph of the same area both pass `validate_graph` and expose identical field names (routing/mutations work on both).
- **Regression:** Liron's `test_graph_mutation.py` passes on the OSMnx graph unchanged.

## Verification
**Local:** `python -m torontosim.graph.build --source centreline --area downtown` → graph json with confidence labels; `summarize_graph` prints class histogram; mutation test green on both sources.
**On Spark:** build the citywide Centreline graph (more memory) over SSH; confirm it loads + a sample route solves.

## Tasks
- [ ] T02.1 `schema.py` canonical fields + `validate_graph` + confidence enum — *0.5d*
- [ ] T02.2 `centreline_loader.py` (TCL→edges, Intersection→nodes, oneway, filter) — *1.5d*
- [ ] T02.3 Confidence labels across both loaders — *0.5d*
- [ ] T02.4 `calibrate_capacity.py` TMC-match nudge — *0.5d*
- [ ] T02.5 `build.py` CLI + bridges height attach — *0.5d*
- [ ] T02.6 Tests (schema, centreline fixture, parity) + Liron regression — *0.5d*

## Risks / fallbacks
- **Centreline topology messy** (segments not noded cleanly at intersections) → snap endpoints to nearest Intersection node within tolerance; fall back to OSMnx (baseline) for the demo if Centreline graph is unstable.
- **Centreline → many more edges than OSMnx** (perf) → keep the demo on the downtown extent; citywide is a perf/P11 concern.
- **TMC match coverage low** → calibration is best-effort; uncalibrated edges keep `default` confidence (honest).
