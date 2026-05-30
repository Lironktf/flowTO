# Research Brief 02 — Transit GTFS + deck.gl rendering

> Feeds **P08 (transit overlay)** and **P07 (frontend)**. MVP = visual + schedule overlay, no rider coupling.

## 1. TTC GTFS static
- **Source:** City Open Data `ttc-routes-and-schedules`. Direct zip: `https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/7795b45e-e65a-4465-81fc-c36b9dfff169/resource/cfb6b2b8-6191-41e3-bda1-b175c51148cb/download/opendata_ttc_schedules.zip`
- **Don't hardcode the filename** (it has changed) — resolve via CKAN API: `…/api/3/action/package_show?id=ttc-routes-and-schedules` → `result.resources[].url`.
- **Format:** standard GTFS static. **Cadence:** ~6-weekly (board periods). **License:** OGL-Toronto.

## 2. GO Transit + UP Express GTFS (Metrolinx)
- **Source:** https://www.metrolinx.com/en/about-us/open-data — **GO and UP are TWO SEPARATE feeds.**
- Static GTFS zips need **no API key** (click-through Access agreement). The separate **GO real-time API** (GTFS-RT) needs a free account — **not needed** for schedule animation.
- **Fallback mirrors:** Transitland `f-dpz-gotransit` (https://www.transit.land/feeds/f-dpz-gotransit) + UP; Mobility Database (successor to transitfeeds). **License:** OGL-Ontario.
- **Recommendation:** ingest 3 feeds (TTC/GO/UP) separately, tag each with `mode`/`agency` for coloring. Cache zips with fetch date; weekly re-fetch is plenty (local-only).

## 3. GTFS parsing in Python — `gtfs_kit` vs `partridge`
| | `partridge` | `gtfs_kit` |
|---|---|---|
| Model | Lazy reader; filter by `service_id`/date cheaply | Eager pandas/GeoPandas; geometry helpers |
| Best for | **(b)** time-filtered trip set for vehicle interpolation | **(a)** per-route shape polylines + stops GeoJSON |

Neither ships "vehicle position at time T" — build interpolation yourself. **Use both** (or `gtfs_kit` alone covers everything).

**(a) Route polylines (`gtfs_kit`):**
```python
import gtfs_kit as gk
feed = gk.read_feed("ttc.zip", dist_units="km")
shapes_gdf = feed.geometrize_shapes()       # shape_id -> LineString (4326)
trips = feed.trips[["route_id","shape_id"]].drop_duplicates()
routes = feed.routes[["route_id","route_short_name","route_type","route_color"]]
route_shapes = shapes_gdf.merge(trips,on="shape_id").merge(routes,on="route_id")
route_shapes.to_file("ttc_routes.geojson", driver="GeoJSON")
```

**(b) Vehicle position at time T (interpolate along shape):**
1. pick service date → active `service_id`s (calendar/calendar_dates).
2. trips for those services; their `stop_times` (secs since midnight).
3. project each stop onto its trip's shape → `shape_dist_traveled` (use `feed.append_dist_to_stop_times()` if missing).
4. for query `t`: per trip find bracketing stops, lerp distance, `line.interpolate(d)`.
Watch-outs: times exceed 24:00:00 (next-day; keep seconds, don't wrap); not every trip has `shape_dist_traveled`.

## 4. deck.gl rendering (deck.gl 9.x; v9.1 latest at brief time, v9.3 confirmed in brief 06)
**Version-specific:**
- **`TripsLayer` + `TileLayer`/`MVTLayer` moved to `@deck.gl/geo-layers`** in v9. `PathLayer`/`GeoJsonLayer` in `@deck.gl/layers`.
- **MapLibre:** use **`MapboxOverlay`** from `@deck.gl/mapbox`; interleaved needs `maplibre-gl@>=3`.
- **float32 gotcha:** `currentTime`/`getTimestamps` are stored float32 → use **seconds-since-midnight (small floats)**, NOT raw Unix ms, or animation jitters.

**PathLayer (routes, color per mode):**
```js
new PathLayer({ id:'routes', data: routeShapes, getPath:d=>d.path,
  getColor:d=>MODE_COLOR[d.route_type] ?? hexToRgb(d.route_color),
  getWidth:2, widthUnits:'pixels', widthMinPixels:1.5, capRounded:true, jointRounded:true, pickable:true });
```
**TripsLayer (animated vehicles):** each trip = `{path:[[lng,lat]...], timestamps:[secs...], route_type}` (parallel arrays).
```js
import { TripsLayer } from '@deck.gl/geo-layers';
new TripsLayer({ id:'vehicles', data:trips, getPath:d=>d.path, getTimestamps:d=>d.timestamps,
  getColor:d=>MODE_COLOR[d.route_type], currentTime, trailLength:90, fadeTrail:true,
  widthMinPixels:3, capRounded:true });
```
Animate by re-setting `currentTime` each frame (driven by the time scrubber, not a free rAF). GeoJsonLayer for stops.

## 5. Precompute server-side vs client-side
**Verdict for MVP: precompute server-side** into TripsLayer-ready `{path, timestamps:[secs], route_type}`, cache per `(service_date, agency)`. Hundreds–thousands of trips animate smoothly because **TripsLayer interpolates on the GPU** (`currentTime` is one uniform; per-frame CPU ≈ 0). Cleanly satisfies "vehicles are pure visual overlay, decoupled from traffic math." Reserve GTFS-RT for a later phase.

### Links
TTC: https://open.toronto.ca/dataset/ttc-routes-and-schedules/ · Metrolinx: https://www.metrolinx.com/en/about-us/open-data · partridge: https://github.com/remix/partridge · gtfs_kit: https://github.com/mrcagney/gtfs_kit · TripsLayer: https://deck.gl/docs/api-reference/geo-layers/trips-layer · MapboxOverlay: https://deck.gl/docs/api-reference/mapbox/mapbox-overlay

**Flags:** (1) v9 moved TripsLayer to geo-layers; (2) MapboxOverlay + maplibre-gl≥3 for interleaved; (3) keep timestamps small (seconds-since-midnight); (4) re-resolve download URLs via APIs; (5) GO & UP are separate feeds, static zips need no key.
