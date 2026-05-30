# BUILD STATUS — TorontoSim MVP

> Overnight dashboard. The build agent updates this after every task and phase.
> Status legend: `todo` · `doing` · `done ✅` · `blocked 🚫` · `deferred ⏭️` (with reason).
> Started: 2026-05-30 · Branch: per-phase `build/flo-*` off `bentobranch` (+`liron/model` merged) · Last update: 2026-05-30
> Baseline: `pytest -q` = **5 passed** (2 Liron + 3 packaging); ruff+black clean.

## Phase status
| Phase | Title | Status | Notes |
|---|---|---|---|
| P00 | Repo restructure, env, Spark harness | done ✅ | `torontosim` pkg + shims; pyproject/Makefile/CI; Spark harness verified end-to-end. PR: FLO-6. |
| P01 | Data pipeline → Parquet feature store | done ✅ | `datapipeline` module (ckan/restrictions/gtfs/weather/bake/manifest/cli); mocked tests + offline bake/verify. Real full fetch deferred to pre-event/Spark (network). PR: FLO-7. |
| P02 | Road graph (OSMnx + Centreline) | done ✅ | Canonical `schema.validate_graph` + confidence labels; `centreline_loader` (TCL→edges, oneway, dedupe, filter), `calibrate_capacity` (TMC nudge), `build` CLI. 7 tests + parity; Liron regression green. PR: FLO-8. |
| P03 | Demand & OD (ML + IPF + TTS seed) | done ✅ | `ipf` (numpy Furness), `odme` (IPF-on-counts), `timeofday`, `tts_seed` (Census×Employment fallback), `validate_past`; `generate_od_matrix` gains `calibration={none(default),ipf,ipf_counts}`. 10 tests. Demand retrain on full data + live ODME wiring deferred to Spark/P04. PR: FLO-9. |
| P04 | Simulation engine (BPR + Frank-Wolfe + oracle) | done ✅ | BPR + CFW user equilibrium; **validated vs published SiouxFalls UE** (~0.1% link err); CPU+cuGraph backends (**GPU-vs-CPU verified on Spark**); determinism; wired into `simulate_traffic` behind `engine`/`congestion_model`/`backend` flags (defaults baseline-safe). PR: FLO-10. |
| P05 | Blast-radius recompute | done ✅ | `pathcache` (edge→OD reverse index), `cones` (bounded up/down Dijkstra + highway core), `recompute` (affected subgraph + blast AON). **Parity: blast == full recompute exactly at AON layer**; subgraph strict subset; deterministic. `simulate_scenario(recompute=blast)`. PR: FLO-14. |
| P06 | Backend API (FastAPI + WS) | todo | |
| P07 | Frontend (deck.gl + MapLibre) | todo | design drop slots in |
| P08 | Transit overlay (GTFS) | todo | |
| P09 | Copilot (Nemotron) | todo | Spark-gated |
| P10 | Optimizer (heuristic + cuOpt) | todo | Spark-gated |
| P11 | Profiling & perf | todo | land early |
| P12 | FIFA WC demo | todo | |
| S1–S6 | Stretch | todo | only after core stable |

## Gating verdicts (record once)
- Spark reachable over Tailscale: ✅ **REACHABLE** (2026-05-30, key auth via `gx10-4f5f` and `100.124.76.16`).
- RAPIDS smoke (`smoke_rapids.py` on Spark): ✅ **RAPIDS_OK** (2026-05-30, cuDF/cuGraph 26.04 + SSSP on GB10) → `backend=gpu` available.
- Ollama smoke (`smoke_ollama.py` on Spark): ✅ **OLLAMA_OK** (2026-05-30, `nemotron3:33b`, ~1.07s JSON).
- cuOpt smoke (`smoke_cuopt.py` on Spark): _pending_ (P10).

## Task log (append-only)
| Time | Phase/Task | Status | Note |
|---|---|---|---|
| 2026-05-30 | P00 T00.1 | done ✅ | Merged `liron/model` into build branch; kept both doc sets; resolved `.gitignore`. |
| 2026-05-30 | P00 T00.2 | done ✅ | `src/*` → `src/torontosim/*`; shims at `src/{graph,model,simulation}`; tests on `torontosim.*`; +`test_packaging.py`. |
| 2026-05-30 | P00 T00.3 | done ✅ | `pyproject.toml` (extras dev/sim/gpu/ai/api), `Makefile`, ruff/black/pre-commit; lint clean. |
| 2026-05-30 | P00 T00.4 | done ✅ | De-committed graphml/raw/model/sim artifacts + `.DS_Store`; kept test-critical json+pkl; `data/README.md`. |
| 2026-05-30 | P00 T00.5 | done ✅ | Spark harness (`scripts/spark/*`) + smokes; verified RAPIDS_OK + OLLAMA_OK on gx10-4f5f. |
| 2026-05-30 | P00 T00.6 | done ✅ | GitHub Actions CI (py3.12, ruff+black+pytest, spark tests skipped). |
| 2026-05-30 | P00 T00.7 | done ✅ | Local verify green (5 passed, lint clean); Spark round-trip + both smokes green. |
| 2026-05-30 | P01 T01.1–T01.7 | done ✅ | `datapipeline`: CKAN resolve-by-name+paginate, live CART restrictions parse, GTFS TTC/GO/UP feeds, ECCC weather + filename fix, parquet+DuckDB bake/verify, manifest+attribution, CLI. 12 mocked/fixture tests green; `ingest_real_data` now prefers parquet w/ raw fallback. Full network fetch (TCL 118MB etc.) deferred to pre-event/Spark. |
| 2026-05-30 | P02 T02.1–T02.6 | done ✅ | `schema.py` (canonical fields + confidence + `validate_graph`); `centreline_loader` (TCL→directed edges, ONEWAY_DIR_CODE, intersection dedupe, road-class filter, CENTRELINE_ID kept); `calibrate_capacity` (observed-peak nudge); `build.py` CLI (`--source osmnx|centreline`); OSMnx enrich now emits per-field confidence. 7 P02 tests + parity green; full suite 24 passed. |
| 2026-05-30 | P03 T03.1–T03.7 | done ✅ | `ipf.py` (numpy Furness, struct-zero safe), `odme.py` (pragmatic IPF-on-counts, error-decreasing), `timeofday.py` (AM/PM peak shares), `tts_seed.py` (node↔zone, Census×Employment gravity prior, explode-to-nodes), `validate_past.py` (deterministic predicted/observed metrics); `generate_od_matrix` `calibration` flag (default `none` = baseline-safe) + sparse `_calibrate_ipf`. Full suite 35 passed. |
| 2026-05-30 | P04 T04.1–T04.8 | done ✅ | `bpr.py` + per-class α/β + congestion dispatch; `network.py` (CSR), `backends/{cpu,gpu}` (Dijkstra / cuGraph SSSP AON); `equilibrium.py` FW+CFW+line-search+rgap (CFW 206 vs FW 967 iters on SiouxFalls); `oracle.py` TNTP loader; **oracle: link flows match published SiouxFalls UE to ~0.1%**; determinism (byte-identical + tie-break); `simulate_traffic` `engine`/`congestion_model`/`backend` flags (baseline-safe defaults). **Spark: `test_gpu_matches_cpu` PASSED** (cuGraph backend within tol). Full CPU suite 49 passed. |
| 2026-05-30 | P05 T05.1–T05.5 | done ✅ | `blastradius/{pathcache,cones,recompute}`: O(1) affected-OD lookup, bounded up/down cones + highway core, adaptive subgraph. **Parity test: blast AON == full AON exactly** on a 100-node grid; subgraph strict subset; deterministic. Wired `simulate_scenario(recompute=blast)` reporting subgraph fraction. Full suite 56 passed, 1 skipped (spark GPU). |

## Blocked / deferred (surface for the human)
_(none yet)_
