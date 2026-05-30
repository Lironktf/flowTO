# Research Brief 01 — Toronto Open Data (ingestion)

> Verified live against the City of Toronto CKAN API on **2026-05-30**. Feeds **P01, P02**.
> **API base:** `https://ckan0.cf.opendata.inter.prod-toronto.ca` · portal `https://open.toronto.ca`.

**License:** Treat all as **Open Government Licence – Toronto v1.0** (attribution string:
`Contains information licensed under the Open Government Licence – Toronto`). Per-package `license_id`
metadata is unreliable (often `notspecified`); only `toronto-centreline-tcl` and `one-way-streets` carry the
explicit license id. License text: https://www.toronto.ca/city-government/data-research-maps/open-data/open-data-licence/

## 0. CKAN API pattern
- **Package metadata:** `GET /api/3/action/package_show?id=<package-name>` → `result.resources[]` (`id`, `format`, `name`, `url`, `datastore_active`).
- **Tabular data (paginated):** `GET /api/3/action/datastore_search?id=<resource-uuid>&limit=N&offset=M` → `result.fields[]` + `result.records[]`; `limit=1` reads schema cheaply; `result.total` = row count.
- **Bulk download:** use resource `url` directly; for datastore resources `…/datastore/dump/<uuid>` streams full CSV.
- **Gotcha:** `datastore_search_sql` is **disabled** on this instance — paginate `datastore_search` instead.

```python
import requests
BASE="https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action"
def resources(pkg): return requests.get(f"{BASE}/package_show", params={"id":pkg}).json()["result"]["resources"]
def page(rid, limit=10000):
    off=0
    while True:
        r=requests.get(f"{BASE}/datastore_search", params={"id":rid,"limit":limit,"offset":off}).json()["result"]
        yield from r["records"]; off+=limit
        if off>=r["total"]: break
```

## 1. Toronto Centreline (TCL) v2 — road geometry
- **Package:** `toronto-centreline-tcl` (`1d079757-377b-4564-82df-eb5638583bfb`) — https://open.toronto.ca/dataset/toronto-centreline-tcl/
- **GeoJSON datastore:** `ad296ebf-fca6-4e67-b3ce-48040a20e6cd`. SHP zip 4326: `…/resource/d86bdca4-ab2c-470d-80fb-34647ea0e87f/download/centreline-version-2-4326.zip` (~118 MB). CSV 4326: `4dec5884-a5cf-49e7-b562-f835150dc0b1`.
- **Formats:** GeoJSON/SHP/CSV/GPKG, in **EPSG:4326** and **EPSG:2952**. **Rows:** 64,441 segments.
- **Key fields:** `CENTRELINE_ID`, `LINEAR_NAME_FULL`, `FROM_INTERSECTION_ID`, `TO_INTERSECTION_ID`, `ONEWAY_DIR_CODE`/`_DESC`, `FEATURE_CODE`/`_DESC`, `JURISDICTION`, `CENTRELINE_STATUS`, address ranges, `geometry`.
- **Refresh:** Daily. **Gotcha:** includes rivers/walkways/rail/admin — **filter `FEATURE_CODE_DESC` to road classes**. `FROM_/TO_INTERSECTION_ID` join to #2.

## 2. Centreline Intersection — nodes
- **Package:** `intersection-file-city-of-toronto` — https://open.toronto.ca/dataset/intersection-file-city-of-toronto/
- **GeoJSON datastore:** `17eb3392-518c-490e-b968-81912b07af81`. **Rows:** 46,397.
- **Key fields:** `INTERSECTION_ID` (→ TCL `FROM_/TO_INTERSECTION_ID`), `INTERSECTION_DESC`, `CLASSIFICATION`, `ELEVATION`, `NUMBER_OF_ELEVATIONS`, `geometry` (Point).
- **Gotcha:** multi-level intersections = multiple rows; dedupe on `INTERSECTION_ID` for a planar graph.

## 3. Traffic Volumes / Turning Movement Counts (TMC)
- **Package:** `traffic-volumes-at-intersections-for-all-modes` (`811c4c10-7e5d-4c76-8d42-dab4e31c8265`) — https://open.toronto.ca/dataset/traffic-volumes-at-intersections-for-all-modes/
- **⚠️ No `tmc_raw_data_2000-2029.csv`.** Split per-decade. Current = **`tmc_raw_data_2020_2029`** (datastore `262469c2-abfe-4756-9068-4ea5c7ba1af7`, 346,154 rows; CSV `88ea1329-1da3-4992-bae6-a821d609d45d`). Others: `2010_2019`, `2000_2009`, `1990_1999`, `1980_1989`.
- **Raw schema (15-min):** `count_id`, `count_date`, `location_name`, `longitude`, `latitude`, `centreline_id`, `px`, `start_time`, `end_time`, per-leg/per-mode movements `{n,s,e,w}_appr_{cars,truck,bus}_{r,t,l}`, `_peds`, `_bike`.
- **Summary:** `tmc_most_recent_summary_data` (`6afa3b1f-…`, 6,410 rows; one latest per location) with `am_peak_*`, `pm_peak_*`.
- **Gotcha:** counts are **sparse/ad-hoc**, not continuous. Pre-Sept-2023 = 8 non-continuous hours; after = 14h continuous. Join via `centreline_id`/`px`.

## 4. Traffic Signals
- **Package:** `traffic-signals-tabular` (`1a106e88-f734-4179-b3fe-d690a6187a71`) — https://open.toronto.ca/dataset/traffic-signals-tabular/
- **⚠️ No `traffic-signals-timing.csv`** — open data does **not** publish phase/cycle timing. Closest = `Traffic Signal` layer (`139e5357-0caf-4c9a-a6be-ce94d38bcfeb`, 2,545 rows).
- **Key fields:** `PX` (→ TMC `px`), `MAIN_STREET`, `SIDE1/2_STREET`, `CONTROL_MODE`, `PEDWALKSPEED`, `TRANSIT_PREEMPT`, `geometry`. Must **synthesize** actual phase timings.

## 5. Road Restrictions / closures — **LIVE feed**
- **Package:** `road-restrictions` (`2265bfca-e845-4613-b341-70ee2ac73fbe`) — https://open.toronto.ca/dataset/road-restrictions/
- **Live CART endpoint (not static):** JSON `https://secure.toronto.ca/opendata/cart/road_restrictions/v3?format=json` (also `csv`, `xml`).
- **Schema:** `id`, `road`, `name`, `latitude`, `longitude`, `roadClass`, `planned`, `startTime`/`endTime` (epoch ms), `description`, `fromRoad`/`toRoad`/`atRoad`, `directionsAffected`, `type` (e.g. `CONSTRUCTION`), `geoPolyline` (`[lng,lat]` list), `maxImpact`.
- **Gotchas:** **needs a browser `User-Agent`** (else 403/404); times are epoch ms; `geoPolyline` is not GeoJSON; poll directly (no datastore copy).

## 6. One-Way Streets
- **Package:** `one-way-streets` (`4de009e0-ea29-4469-8b1c-22c9cdefe32c`). SHP only; **stale** (2019). **Prefer TCL `ONEWAY_DIR_CODE`** (daily) as authoritative; use this as cross-check.

## 7. Bridges & elevated roadways
- **⚠️ Old package retired** → use **`bridge-structure`** → "Bridge Structures" (`405d75e3-3fb8-4957-8937-3dc9936b17b9`, 1,829 rows; GeoJSON `9a087353-e2f7-4e44-92a4-56f2208aec5f`). Fields incl. `VERT_CLEAR` (height-restricted routing), `STR_TYPE`, `WARD_NO`, `geometry` (Point). Join to TCL by location/ward.

## 8. 3D Massing
- **Package:** `3d-massing` — https://open.toronto.ca/dataset/3d-massing/
- **⚠️ Newer than spec's 2016-2019** — yearly **2016 → 2025**. Latest SHP: `3DMassingShapefile_2025_WGS84.zip` (`667237d6-4d3c-4cf3-8cb7-e91c48d59375`). Each year: **Shapefile** (footprint+height) + **Multipatch** (true 3D). WGS84, file-only (no datastore). Use latest year unless 2016-2019 specifically needed.

## 9. Boundaries / TAZ
- **Wards:** `city-wards` (25, datastore `7672dac5-…`). **Neighbourhoods:** `neighbourhoods` (158 current `5e6095fc-…`; historical 140 `7d3ae06b-…`).
- **⚠️ No Toronto-published TAZ.** Real TAZ = TTS **GTA06** zones (UofT DMG, external — see research/03). For TorontoSim use **neighbourhoods (158)** or **wards (25)** as zone proxies, or TTS zones if obtained.

## Ingestion notes
- Prefer **EPSG:4326** variants. Graph = TCL (#1) + Intersection (#2), filter TCL to road classes. Join keys: `centreline_id`↔`CENTRELINE_ID`, `px`↔`PX`, intersection endpoints ↔ `INTERSECTION_ID`.
- Only #5 is live (browser UA); snapshot the rest once. No server-side SQL — paginate or download files; big files (TCL SHP 118 MB, TMC 346k rows) pull as files.

### Could-not-verify / flags
`tmc_raw_data_2000-2029.csv` (doesn't exist → per-decade), `traffic-signals-timing.csv` (no phase timings in open data), `cart_road_restrictions.xml` (live feed not static), bridges package retired, 3D massing → 2025, no Toronto TAZ layer.
