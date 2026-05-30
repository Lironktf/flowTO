# P01 — Data pipeline: fetch → versioned Parquet feature store

| | |
|---|---|
| **Priority** | Core |
| **Depends on** | P00 |
| **Owner hint** | Data/sim owner |
| **Status** | not started |

## Goal
A **reproducible, runnable ingest pipeline** (`python -m torontosim.datapipeline …`) that pulls every Toronto
open dataset + transit GTFS + weather, normalizes to **Parquet/GeoParquet/DuckDB**, and preserves raw-file
lineage. Replaces ad-hoc downloads with one command + a manifest.

**Why / rubric tie-in:** Completeness ("the demo starts from raw City data, not a static dashboard") + Spark
story (fast local rebuilds). The ingest is **part of the judged system**.

## Current state
- Liron's `scripts/fetch_data.sh` pulls TMC + weather; `src/model/ingest_real_data.py` ETLs TMC+weather → training CSV. No GeoParquet store, no manifest, no Centreline/restrictions/massing/GTFS, some malformed weather filenames.

## Target state
- `datapipeline/` module: per-dataset fetchers (CKAN API + live CART feed + Metrolinx), a normalizer to GeoParquet, a DuckDB catalog, and a **raw-file manifest** (`data/manifest.json`: source URL, resource UUID, fetch timestamp, sha256, license).
- One CLI: `fetch` (download raw), `bake` (normalize → parquet), `verify` (schema + row-count checks).

### In scope
TCL, Intersection, TMC (per-decade), Traffic Signals, Road Restrictions (live), One-Way (cross-check), Bridges, 3D Massing, Neighbourhoods/Wards; TTC/GO/UP GTFS; ECCC weather. Manifest + lineage. Idempotent caching.
### Out of scope
The graph build (P02), OD/demand (P03), trajectory precompute (P08 consumes the GTFS this phase lands).

## Design / implementation plan
1. **CKAN fetchers** (`datapipeline/ckan.py`) — `package_show` → resolve resource UUID by format; download file or `datastore/dump`; **paginate** (no server SQL). Use the **exact resource UUIDs in `research/01`**, but resolve-by-name to survive renames.
2. **Live restrictions** (`datapipeline/restrictions.py`) — poll `secure.toronto.ca/opendata/cart/road_restrictions/v3?format=json` with a **browser `User-Agent`**; epoch-ms times; `geoPolyline` `[lng,lat]` → LineString.
3. **GTFS fetch** (`datapipeline/gtfs.py`) — TTC (CKAN), GO + UP (Metrolinx, separate); tag `agency`/`mode`; cache zips with fetch date (no API key for static).
4. **Weather** (`datapipeline/weather.py`) — ECCC hourly (Toronto Pearson); fix Liron's malformed `weather_2023 6_00.csv` filenames; normalize to `{(y,m,d,h): category}`.
5. **Normalize → GeoParquet** (`datapipeline/bake.py`) — reproject to EPSG:4326; write `data/parquet/{centreline,intersections,tmc,signals,restrictions,bridges,massing,zones}.parquet`; build a DuckDB catalog `data/catalog.duckdb` over them.
6. **Manifest + lineage** — `data/manifest.json` with provenance per dataset; print attribution strings (OGL-Toronto / OGL-Ontario).
7. **Idempotency** — skip re-download if sha256 matches; `--force` to refresh.

## Data / models / sources
All IDs/URLs/gotchas: **`research/01-toronto-datasets.md`** (CKAN API, exact UUIDs, live feed UA, retired-bridges/3D-massing/TMC-filename flags) + **`research/02-transit-gtfs-deckgl.md`** (TTC/GO/UP feeds).

## Files to create / modify
**Create:** `src/torontosim/datapipeline/{__init__,ckan,restrictions,gtfs,weather,bake,manifest,cli}.py`; `data/README.md` (provenance); `data/.gitignore` (parquet/raw gitignored).
**Modify/absorb:** `scripts/fetch_data.sh` → thin wrapper over the CLI; `src/torontosim/model/ingest_real_data.py` → read from the parquet store instead of raw CSVs.

## Test-driven design
- `tests/test_datapipeline.py` (write first, network-mocked): `ckan.resolve_resource("ttc-routes-and-schedules","zip")` returns a URL; `restrictions.parse(sample_json)` → LineStrings with epoch-ms→datetime; `weather.normalize` handles the malformed filename.
- **Schema contract tests:** each baked parquet has the expected columns/dtypes (`tmc` has `centreline_id`,`px`,`start_time`,…). Use a tiny committed sample fixture, not the full download.
- `bake.verify()` asserts row-count floors (e.g. TCL > 60k segments) — marked `@pytest.mark.network` (skipped in CI, run manually/Spark).

## Verification
**Local:** `python -m torontosim.datapipeline fetch --only ttc,tmc,centreline && … bake && … verify` → parquet files + `manifest.json` present; `duckdb data/catalog.duckdb "select count(*) from centreline"`.
**On Spark:** run full `fetch+bake` over SSH (the Spark has the disk + may be the air-gapped runtime) and `pull.sh` the manifest back; confirm reproducible sha256s.

## Tasks
- [ ] T01.1 `ckan.py` fetcher + resolve-by-name + pagination — *1d*
- [ ] T01.2 `restrictions.py` live CART feed (UA, epoch ms, polyline) — *0.5d*
- [ ] T01.3 `gtfs.py` TTC/GO/UP fetch + tagging — *0.5d*
- [ ] T01.4 `weather.py` ECCC + filename fix — *0.5d*
- [ ] T01.5 `bake.py` → GeoParquet + DuckDB catalog — *1d*
- [ ] T01.6 `manifest.py` lineage + attribution; CLI wiring — *0.5d*
- [ ] T01.7 Schema/contract tests + verify; point `ingest_real_data` at parquet — *0.5d*

## Risks / fallbacks
- **Air-gapped runtime** → run `fetch` before the event; the manifest + cached raw make `bake` offline-repeatable.
- **Live restrictions feed flaky/blocked** → snapshot a JSON once; restrictions are a *demo input*, not load-bearing.
- **Big downloads (TCL 118 MB, TMC 346k)** → cache + sha256; pull as files not paged.
