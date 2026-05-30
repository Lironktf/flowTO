# HANDOFF — TorontoSim MVP

> Build completed 2026-05-30 by the autonomous `/goal` agent. **All 13 phases
> (P00–P12) are ✅.** `pytest -q` = **100 passed, 2 skipped** (the 2 skips are
> Spark-gated GPU/LLM tests, both verified live on `gx10-4f5f`). Frontend builds
> + 12 vitest green. The FIFA WC demo runs deterministically.

## 1. What's done (per phase)
| Phase | What shipped | PR |
|---|---|---|
| **P00** Repo/env/Spark | `torontosim` package + shims, pyproject/Makefile/CI, Spark SSH harness | FLO-6 (#1) |
| **P01** Data pipeline | `datapipeline` (ckan/restrictions/gtfs/weather/bake/manifest/cli), parquet+DuckDB | FLO-7 (#2) |
| **P02** Road graph | canonical `schema` + confidence, Centreline loader, capacity calibration, build CLI | FLO-8 (#3) |
| **P03** Demand & OD | IPF/Furness, pragmatic ODME, time-of-day, TTS/Census seed, validate-past; `calibration` flag | FLO-9 (#4) |
| **P04** Sim engine | **BPR + Frank-Wolfe/CFW equilibrium, oracle-validated vs published SiouxFalls UE (~0.1%)**; CPU+cuGraph backends (GPU verified on Spark); determinism | FLO-10 (#5) |
| **P05** Blast-radius | pathcache + cones + recompute; **blast == full recompute exactly at the AON layer**; `recompute=blast` | FLO-14 (#6) |
| **P06** Backend API | FastAPI scenario CRUD/run/preview/compare, **binary WS tick frames**, async jobs; boots on 18k-edge graph | FLO-11 (#7) |
| **P07** Frontend | React+Vite+TS deck.gl+MapLibre, 6-state machine, tickStore typed-arrays, design tokens; browser-verified hero flow | FLO-12 (#8) |
| **P12** FIFA WC demo | `wc_surge` egress injection + 3 deterministic scenarios + RUNBOOK; headline metric melts baseline→surge→fix | FLO-13 (#9) |
| **P09** Copilot | Nemotron NL→validated tool calls (mockable + re-ask), constraint checker, offline RAG, cited; **live `nemotron3:33b` verified on Spark** | FLO-16 (#10) |
| **P10** Optimizer | heuristic + **sim-as-verifier**, action masks + budget, `/optimize`; cuOpt client (deferred) | FLO-17 (#11) |
| **P11** Profiling | timing harness + bench CLI; **measured 15.19× blast-radius speedup (11.6s→766ms)** | FLO-18 (#12) |
| **P08** Transit overlay | GTFS routes/trajectories + API + frontend TripsLayer, scrubber-synced (visual-only) | FLO-15 (#13) |

## 2. Spark verdicts (recorded in `infra/README-spark.md`)
- **Spark reachable** ✅ (Tailscale/key auth, `asus@gx10-4f5f`).
- **RAPIDS_OK** ✅ — cuDF/cuGraph 26.04 + SSSP on GB10; GPU sim backend verified (`test_gpu_matches_cpu` passed).
- **OLLAMA_OK** ✅ — `nemotron3:33b`; live copilot NL→tool-call verified (8.8s).
- **CUOPT_UNAVAILABLE** ⏭️ — not installed; heuristic optimizer is the path (deferred-with-fallback).

## 3. What's deferred (and why it doesn't block the demo)
All deferrals are **network- or install-bound**, each with a working fallback:
- **Real full data fetch** (Centreline 118 MB, TMC 346k, live restrictions, real GTFS): network-bound → run `datapipeline fetch` pre-event/on Spark. Committed `toronto_drive_graph.json` + `demand_model.pkl` carry the demo; mocked tests cover the pipeline logic.
- **cuOpt**: not installed on the Spark → the heuristic optimizer always returns an improving, sim-verified plan.
- **Live ODME against TMC counts in the assignment loop**: the `odme` module is tested standalone; wiring into the live loop is a follow-up.
- **Nsight `.nsys-rep` capture**: scripts present; the in-app counters + the 15.19× bench already give the perf evidence.
- **Demand-model retrain on full data (XGBoost CUDA)**: the committed `.pkl` is used; retrain script targets the Spark.

## 4. Run the demo (exact commands)
```bash
cd ~/flowTO-build && source .venv/bin/activate     # built worktree

# A) Verify everything green (CPU)
pytest -q                                          # 100 passed, 2 skipped

# B) The deterministic demo metric (baseline → surge → fix)
python -m torontosim.demo.wc_surge --scenario all
#   baseline  exhib_p≈0.00   →  wc_surge ≈0.90 (gridlock)  →  wc_fix ≈0.51 (eased)

# C) Perf evidence (full vs blast-radius recompute)
python -m torontosim.perf.bench                    # ~15× speedup, writes data/bench/results.md

# D) The interactive app (two terminals)
scripts/run_api.sh                                 # API on :8000  (docs at /docs)
scripts/run_frontend.sh                            # Vite on :5173

# E) Spark validation (optional, over Tailscale)
scripts/spark/run.sh "python scripts/spark/smoke_rapids.py"    # RAPIDS_OK
scripts/spark/run.sh "python scripts/spark/smoke_ollama.py"    # OLLAMA_OK
```
**Stage run-of-show:** `demo/RUNBOOK.md` (90-second click sequence, fallbacks, rubric close).

## 5. Known issues / notes
- Frontend bundle is large (deck.gl + maplibre, ~1.9 MB) — fine for a local demo; code-split later if needed.
- The full-city `recompute=full` on a congested closure is ~11.6 s (kpath rerouting); **blast-radius (766 ms) is the interactive path** — use `recompute=blast` for live interaction.
- Engine defaults are **baseline-safe** (`engine=kpath`, `congestion_model=legacy`/`bpr`, `backend=cpu`) per GOAL; equilibrium/GPU are opt-in flags, both verified.
- 2 skipped tests are `@pytest.mark.spark` (GPU + live Nemotron) — run them on the Spark via the harness.

## 6. Branches / PRs
Each phase is one branch `build/flo-*` + one PR (stacked, base = previous phase) titled `… (Closes FLO-NN)` for Linear auto-transition. PRs #1–#13 on `github.com/Lironktf/flowTO`. Nothing is merged — the human reviews/merges the stack.
