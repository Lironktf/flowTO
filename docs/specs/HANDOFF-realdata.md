# HANDOFF — close the "real data" gap

> A scoped handoff for the next build agent. The MVP (P00–P12) is complete, green,
> and merged to `main`; the frontend is real-data-wired. **This task swaps the
> remaining sample/mock inputs for real City of Toronto data** — behind flags, with
> the baseline kept green. Operating rules follow `docs/specs/GOAL.md` (§2, §4).

## 0. Where things stand (read first)
- Repo `Lironktf/flowTO`; **trunk is `main`** (the MVP was merged via PR #16).
  `git fetch` and branch off `main`.
- CI installs `pip install -e ".[dev,data,api]"` then `pytest -q -m "not spark"` +
  ruff/black, and is green. Local full suite ≈ **104 passed, 2 skipped** (the 2 are
  `@pytest.mark.spark` GPU+LLM, verified live on the Spark).
- The frontend already renders **real engine output** (real 18,190-edge graph from
  `/edges`, pressures from `/demo/run`, copilot `/copilot/plan`). **But** the
  underlying graph is still Liron's **OSMnx** graph, demand uses the committed
  `models/demand_model.pkl`, and transit is a synthesized 509/511 demo set. **No real
  Centreline / TMC / GTFS has ever been fetched or baked.**

## 1. Operating rules (non-negotiable)
- **Baseline stays green.** The demo-safe default path (OSMnx graph, gravity OD, demo
  transit) must keep working. Add real-data paths **behind the existing flags**
  (`graph_source=centreline`, `calibration=ipf_counts`, a transit `source`). Never
  delete the fallback.
- **TDD.** Failing test first, with **small committed fixtures** (network-mocked);
  implement to green. Real downloads are `@pytest.mark.network` (skipped in CI) and run
  on the Spark / pre-event. Large artifacts stay gitignored.
- **CPU-first; Spark for the heavy fetch.** Big files (TCL SHP ~118 MB, TMC 346k rows,
  GTFS zips) + disk-heavy bakes run on the DGX Spark via the SSH harness
  (`scripts/spark/{push,run,pull}.sh`, `SPARK_HOST=asus@gx10-4f5f`). The dev box may
  have limited network — mock locally, fetch for real on the Spark.
- **Determinism + BUILD_STATUS.** Update `docs/specs/BUILD_STATUS.md` per task; commit
  per task with an id-prefixed message; no `Co-Authored-By` trailers.
- **Branching:** ONE feature branch off `main`, ONE PR (`Closes FLO-7`, note FLO-8/9/15
  touched), merged with a **merge commit — NOT squash**. (A squash-merged stacked chain
  broke last time: squash rewrites SHAs and conflicts the rest of the stack.)

## 2. Required reading (in order)
1. `docs/specs/ROADMAP.md`, then `01-data-pipeline.md`, `02-graph.md`,
   `03-demand-and-od.md`, `08-transit-overlay.md`.
2. Research briefs (ground truth — real dataset UUIDs, APIs, gotchas):
   `docs/specs/research/01-toronto-datasets.md`, `02-transit-gtfs-deckgl.md`,
   `03-demand-tts-ipf.md`.
3. `docs/specs/HANDOFF.md` (the deferral list) + root `README.md`.

## 3. The gap → four workstreams (each: a test + acceptance)

### W1 — Implement raw→Parquet bake (the crux; `cmd_bake` is a STUB today)
`src/torontosim/datapipeline/` has `ckan.py` (resolve-by-name + paginate + stream
download), `restrictions.py`, `gtfs.py`, `weather.py`, `bake.py`
(`write_parquet`/`build_catalog`/`verify` — **work**), `manifest.py`, `cli.py`.
**But `cli.cmd_bake` only rebuilds the DuckDB catalog over existing parquet — the
per-dataset normalizers (raw CKAN CSV/GeoJSON → normalized rows) are not written.**
- Implement `bake.bake_{centreline,intersections,tmc,signals,bridges,zones}` per the
  `research/01` schemas + join keys (`centreline_id`/`px`, `INTERSECTION_ID`,
  `ONEWAY_DIR_CODE`). GeoJSON datastore variants parse without geopandas; geometry → WKT
  via shapely (`bake.write_parquet(..., geometry_col=...)` already supports it). For the
  SHP-only TCL 4326 zip either add `pyogrio`/`fiona` to the `data` extra **or** use the
  CSV/GeoJSON datastore resources to avoid geopandas.
- Wire into `cmd_bake` so `fetch → bake → verify` yields
  `data/parquet/{centreline,intersections,tmc,signals,bridges,zones}.parquet`,
  `data/catalog.duckdb`, and `data/manifest.json` (sha256 + license per
  `manifest.ATTRIBUTION`).
- **Test:** tiny committed CKAN-shaped fixtures → bake → assert columns/dtypes (`tmc` has
  `centreline_id`/`px`/`start_time`; centreline has `CENTRELINE_ID`/`ONEWAY_DIR_CODE`) +
  `verify()` floors. Real fetch+bake = `@pytest.mark.network`, run on the Spark.
- **Acceptance:** `python -m torontosim.datapipeline fetch && … bake && … verify`
  produces the store; `duckdb data/catalog.duckdb "select count(*) from centreline"` ≥ 60k.

### W2 — Build the real Centreline graph
`graph/centreline_loader.py` (`build_centreline_graph`, `load_from_parquet`) +
`graph/build.py` (`--source centreline`) + `calibrate_capacity.py` exist and are
fixture-tested. Run them on the **baked** parquet:
- `python -m torontosim.graph.build --source centreline` → canonical-schema graph JSON,
  capacity-calibrated against the real TMC parquet, `schema.validate_graph` clean.
- Make it loadable by the API/demo via `TS_GRAPH_JSON` / a `graph_source` switch in
  `api/_bootstrap.load_default_state`, **defaulting to OSMnx** (baseline-safe), Centreline
  opt-in. Confirm `/edges` + `/demo/run` work on it (downtown extent if citywide is too
  heavy — perf is a P11 concern).
- **Acceptance:** Centreline graph builds, validates, routes a sample path; OSMnx path
  unchanged + green.

### W3 — Real demand + ODME against TMC counts
- `model/ingest_real_data.load_tmc` already prefers `data/parquet/tmc.parquet` (falls back
  to raw CSV). With W1 done, rebuild the training table / retrain the demand model from
  real counts (`scripts/train_on_gx10.sh` on the Spark; pull the `.pkl` back).
- Wire **ODME** (`model/odme.odme_ipf_counts` + `assign_to_links` +
  `observed_peak_by_centreline`) into OD construction:
  `generate_od_matrix(..., calibration="ipf_counts")` should reconcile assigned link flows
  to observed TMC peaks. Keep `calibration="none"` the default.
- **Acceptance:** an OD whose assigned counts track TMC; deterministic; `test_simulation.py`
  green under `calibration=none`.

### W4 — Real GTFS transit (replaces the demo 509/511 set)
- `transit/routes.py` + `trajectories.py` have record-level helpers + a hand-authored demo
  set; **there is no GTFS-zip reader.** Add `gtfs_kit` (new `transit` extra) and implement:
  GTFS zip → per-route LineStrings (`geometrize_shapes`) + per-trip `{path, timestamps}`
  (seconds-since-midnight, float32-safe, no >86400 wrap — honor the existing
  `trajectories.build_trajectory` contract). Cache to `data/transit/{agency}_{date}.json`.
- Point the API (`/transit/routes`, `/transit/trajectories`) to the cached real feeds when
  present, else the demo set. TTC via CKAN; GO/UP via Metrolinx (`gtfs.FEEDS`).
- **Acceptance:** real TTC routes/vehicles animate on the scrubber; `test_transit_*` green;
  on-shape / monotonic / no-wrap invariants hold on real data.

## 4. Environment
- `source .venv/bin/activate`; `pip install -e ".[dev,data,api]"` (+ `sim`, `ai`, `gpu`
  only on the Spark). Add `pyogrio` / `gtfs_kit` to the `data` / new `transit` extra as
  needed (and to the CI install line).
- Spark harness: `scripts/spark/push.sh` then
  `scripts/spark/run.sh "python -m torontosim.datapipeline fetch --only centreline,intersections,tmc,ttc && python -m torontosim.datapipeline bake && python -m torontosim.datapipeline verify"`,
  then `scripts/spark/pull.sh data/parquet ./data/parquet`. Smokes pass: RAPIDS_OK,
  OLLAMA_OK (`infra/README-spark.md`).

## 5. Definition of done
- Real Centreline+TMC parquet store baked + manifest; Centreline graph builds & validates;
  demand/ODME consume real TMC; real GTFS animates — all behind flags, **baseline OSMnx +
  demo path still green**.
- `pytest -q` green (new fixtures + mocked-network tests; real fetch `@pytest.mark.network`
  run on the Spark and recorded); ruff/black clean; CI green (extras updated if new deps).
- `docs/specs/BUILD_STATUS.md` + `HANDOFF.md` updated (what's now real vs still fallback);
  `data/README.md` provenance refreshed. One PR to `main`, merge-commit (not squash).

## 6. Known gotchas
- `datastore_search_sql` is disabled on the Toronto CKAN instance → paginate
  `datastore_search` or download files (exact UUIDs + the browser User-Agent the live
  restrictions feed needs are in `research/01`).
- TCL includes rivers/rail/walkways → filter `FEATURE_CODE_DESC` to road classes (the
  loader maps these). `ONEWAY_DIR_CODE`: `0`=two-way, `±1`=one-way.
- The citywide Centreline graph is far larger than the 18k OSMnx downtown graph → keep the
  demo on the downtown extent; full-city is a perf / P11 concern.
- Don't commit large parquet/graph artifacts (gitignored); keep tiny fixtures only.
- Full-graph k-path scenario runs are ~tens of seconds; the API warms a demo cache at
  startup — keep that working.
