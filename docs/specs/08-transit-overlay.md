# P08 — Transit overlay: GTFS ingest, server-side trajectories, TripsLayer

| | |
|---|---|
| **Priority** | Core |
| **Depends on** | P01 (GTFS fetch), P07 (map) |
| **Owner hint** | Frontend + data owner |
| **Status** | not started |

## Goal
Restore the multimodal *look* and the streetcar demo moment: render **TTC / GO / UP Express** routes as lines and
animate vehicles along **schedule** — as a **visual overlay decoupled from the traffic math** (no rider mode
choice yet). This is the "basic transit now" decision; full coupling is stretch S1.

**Why / rubric tie-in:** Insight quality + the demo narrative (the WC fix can involve "+50% on the 509"). Cheap,
high-impact, and it makes the city read as a real multimodal system.

## Current state
- None. P01 lands the GTFS feeds; nothing consumes them yet.

## Target state
- Server precomputes, per service day, each active trip's `{path:[[lng,lat]…], timestamps:[secs_since_midnight], route_type, agency}` and serves it; the frontend animates with a single `TripsLayer` synced to the time scrubber's `currentTime`. Routes drawn as colored `PathLayer` by mode; stops optional.

### In scope
GTFS → route polylines + stops GeoJSON; server-side trajectory precompute + cache; REST endpoint; frontend TripsLayer + route layer + mode coloring + scrubber sync; toggle.
### Out of scope
Rider loading / mode choice / crowding (stretch S1). GTFS-RT live positions (later). Transit affecting road congestion.

## Design / implementation plan
(Specifics in **`research/02-transit-gtfs-deckgl.md`**.)
1. **Route geometry** (`transit/routes.py`) — `gtfs_kit` `geometrize_shapes()` → per-route LineStrings; join `trips`/`routes` for `route_short_name`/`route_type`/`route_color`; export GeoJSON per agency. Stops via `geometrize_stops()`.
2. **Trajectory precompute** (`transit/trajectories.py`) — for a service date: active `service_id`s → trips → `stop_times` (secs since midnight) → project stops onto shape (`append_dist_to_stop_times` if `shape_dist_traveled` missing) → resample to `{path, timestamps}`. **Use seconds-since-midnight (small floats)** to avoid TripsLayer float32 jitter. Cache per `(service_date, agency)` to `data/transit/{agency}_{date}.json`.
3. **API** (extends P06) — `GET /transit/routes?agencies=ttc,go,up`, `GET /transit/trajectories?date=…&agencies=…` (cached).
4. **Frontend** (extends P07) — `layers/transit.ts`: `PathLayer` routes (color by `route_type`: subway/streetcar/bus/GO-rail/UP), `TripsLayer` vehicles driven by `currentTime` from the scrubber (NOT free rAF), `trailLength` ~ minutes, toggle (default off in compare mode). Optional stops `GeoJsonLayer`.

## Data / models / sources
`research/02` (TTC CKAN zip, GO+UP separate Metrolinx feeds, `gtfs_kit`/`partridge`, interpolation algorithm, TripsLayer data shape + float32 timestamp gotcha, server-precompute verdict). GTFS feeds land via P01.

## Files to create / modify
**Create:** `src/torontosim/transit/{__init__,routes,trajectories}.py`; `api/routes/transit.py`; `frontend/src/layers/transit.ts`; `tests/test_transit_trajectories.py`.
**Modify:** P06 app (register transit routes), P07 `MapCanvas`/`appStore` (transit toggle + scrubber → currentTime wiring).

## Test-driven design
- `test_transit_trajectories.py` (first, tiny GTFS fixture): a trip → `{path, timestamps}` with monotonic timestamps in seconds-since-midnight; vehicle position at a mid-trip time lies on the shape between the bracketing stops; next-day (>86400) times don't wrap.
- Route geometry: each route → ≥1 LineString with a `route_type`.
- Frontend unit: `MODE_COLOR[route_type]` mapping; TripsLayer receives small float timestamps.

## Verification
**Local:** precompute TTC trajectories for a date → `GET /transit/trajectories` returns them → frontend animates streetcars/buses along routes as the scrubber moves; toggle hides/shows.
**On Spark:** precompute all 3 agencies on the Spark (more trips) and serve; confirm hundreds of vehicles animate smoothly (GPU interpolation in TripsLayer).

## Tasks
- [x] T08.1 `routes.py` GTFS → route polylines + stops GeoJSON (3 agencies) — *0.5d*
- [x] T08.2 `trajectories.py` schedule → `{path,timestamps}` + cache (float32-safe) — *1d*
- [x] T08.3 Transit API endpoints (routes, trajectories) — *0.5d*
- [x] T08.4 Frontend route PathLayer + TripsLayer + scrubber sync + toggle — *1d*
- [x] T08.5 Tests + verify smooth animation — *0.5d*

## Risks / fallbacks
- **GO/UP feed access friction** → TTC alone restores the streetcar/subway demo; add GO/UP if time.
- **Too many vehicles → jank** → cap by viewport/zoom; TripsLayer GPU-interpolates so this is mostly fine.
- **Scope creep toward coupling** → hold the line: visual overlay only for MVP; coupling is stretch S1.
