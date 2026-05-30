# 03 — Data Sources (Toronto)

All open / free. **Download + bake BEFORE the event** if internet is restricted at runtime.

## Road network + directionality
- **OpenStreetMap via OSMnx** — full Toronto drive graph with `oneway` tags, lane counts,
  speed limits, turn restrictions. `ox.graph_from_place("Toronto, Ontario, Canada", network_type="drive")`.
  Also `network_type="walk"` (pedestrians) and `"bike"`.
- **City of Toronto Open Data** (`open.toronto.ca`):
  - Centreline (official street network), traffic signal locations + timing
  - **Traffic volumes / turning-movement counts** (calibrate demand)
  - Cycling network, pedestrian volumes

## Buildings (the 3D look)
- **City of Toronto 3D Massing** dataset — building footprints + heights → extruded outlines. Best fit for "outline, not full render."
- Fallback: OSM `building` footprints + `building:levels` / `height`.

## Transit (schedule-driven layers)
- **TTC GTFS** — subway, streetcar, bus routes + schedules (City Open Data / TTC).
- **GO Transit + UP Express GTFS** — Metrolinx open data (`metrolinx` / Open Data on transitfeeds mirrors).
- GTFS gives: stops, routes, trips, stop_times, calendar → real "time of day / day of year" behavior.
- Parse with `gtfs_kit` or `partridge`. Build per-route polylines for the map + vehicle trajectories for the sim.

## Demand (who travels where, when)
- **TTS (Transportation Tomorrow Survey)** — GTA travel survey → origin-destination by time of day (gold standard; check access/aggregation).
- **StatsCan / Census** journey-to-work + population by census tract → synthetic OD as a fallback.
- **Event demand:** BMO Field capacity (~28k base, expanded for WC), match schedule → injected surge.

## Bylaws / rules (for optimizer + copilot citations)
- Toronto Municipal Code (traffic/parking), road classifications, transit priority rules.
- Curate a SMALL set of machine-readable constraints (e.g. "no through-truck on residential",
  "min sidewalk width", "transit signal priority on streetcar corridors"). Don't boil the ocean.

## FIFA World Cup 2026 (the hero scenario)
- Toronto = host city, matches at **BMO Field** (Exhibition Place), June–July 2026.
- Build a match-day demand profile: pre-match inbound surge, post-match egress spike on
  Gardiner/Lakeshore + 509/504 streetcars + Exhibition GO/UP.

## Baking pipeline (target)
`raw downloads → normalized graph (nodes/edges + capacities) + GTFS trajectories + OD matrices →
parquet/feather on disk → loaded once at sim startup.` Keep a `data/README` with provenance + dates.

## Pre-event checklist
- [ ] Confirm whether runtime is air-gapped (if so, mirror ALL data locally first)
- [ ] Download OSM extract for Toronto (Geofabrik Ontario) as offline fallback
- [ ] Pull TTC + GO + UP GTFS, snapshot the date
- [ ] Pull 3D Massing + Centreline + traffic counts
- [ ] Verify license/attribution for each (most are Open Government Licence — Toronto)
