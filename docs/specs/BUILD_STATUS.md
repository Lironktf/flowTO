# BUILD STATUS — TorontoSim MVP

> Overnight dashboard. The build agent updates this after every task and phase.
> Status legend: `todo` · `doing` · `done ✅` · `blocked 🚫` · `deferred ⏭️` (with reason).
> Started: _(agent fills in)_ · Branch: `build/mvp` · Last update: _(agent fills in)_

## Phase status
| Phase | Title | Status | Notes |
|---|---|---|---|
| P00 | Repo restructure, env, Spark harness | todo | |
| P01 | Data pipeline → Parquet feature store | todo | |
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
- RAPIDS smoke (`smoke_rapids.py` on Spark): _pending_ → `RAPIDS_OK` | `RAPIDS_FALLBACK_CPU`
- Ollama smoke (`smoke_ollama.py` on Spark): _pending_
- cuOpt smoke (`smoke_cuopt.py` on Spark): _pending_
- Spark reachable over Tailscale: _pending_

## Task log (append-only)
| Time | Phase/Task | Status | Note |
|---|---|---|---|
| _(seed)_ | — | — | Build not started. |

## Blocked / deferred (surface for the human)
_(none yet)_
