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
| P02 | Road graph (OSMnx + Centreline) | todo | |
| P03 | Demand & OD (ML + IPF + TTS seed) | todo | |
| P04 | Simulation engine (BPR + Frank-Wolfe + oracle) | todo | |
| P05 | Blast-radius recompute | todo | |
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

## Blocked / deferred (surface for the human)
_(none yet)_
