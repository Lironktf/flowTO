# TESTING — how to verify the TorontoSim MVP

A practical guide to checking the build, phase by phase. Everything runs on the
CPU dev box; GPU/LLM checks run on the Spark (optional). Total CPU suite ≈ 3 min.

## 0. One-time setup
```bash
cd ~/flowTO-build
source .venv/bin/activate          # the built venv (already has all deps)
# if the venv is missing: make install   (or: python3 -m venv .venv && pip install -e ".[dev,data,api,sim]")
```

## 1. The two commands that matter most
```bash
# Fast confidence check — everything except the slow oracle + Spark tests (~30s)
pytest -q -m "not slow and not spark"

# Full green bar — the real definition of done (~3 min): 100 passed, 2 skipped
pytest -q
```
The **2 skipped** are `@pytest.mark.spark` (GPU + live Nemotron) — they only run on
the Spark (see §4). Everything else must pass.

## 2. Test one phase at a time
Run just that phase's files. (Add `-s` to see prints, `-v` for per-test names.)

| Phase | Command |
|---|---|
| **Baseline** (Liron, regression) | `pytest tests/test_graph_mutation.py tests/test_simulation.py -q` |
| **P00** repo/packaging | `pytest tests/test_packaging.py -q` |
| **P01** data pipeline | `pytest tests/test_datapipeline.py -q` |
| **P02** road graph | `pytest tests/test_graph_schema.py tests/test_centreline_loader.py -q` |
| **P03** demand & OD | `pytest tests/test_ipf.py tests/test_odme.py tests/test_validate_past.py -q` |
| **P04** sim engine | `pytest tests/test_bpr.py tests/test_determinism.py tests/test_sim_engine_integration.py -q` |
| **P04** oracle (slow) | `pytest tests/test_equilibrium_oracle.py -q`  ← validates vs published SiouxFalls UE |
| **P05** blast-radius | `pytest tests/test_blastradius.py tests/test_blastradius_parity.py -q` |
| **P06** backend API | `pytest tests/test_api_scenarios.py tests/test_ws_frames.py -q` |
| **P09** copilot | `pytest tests/test_copilot_plan.py tests/test_copilot_rag.py tests/test_api_copilot.py -q` |
| **P10** optimizer | `pytest tests/test_constraint_checker.py tests/test_optimizer_heuristic.py -q` |
| **P11** profiling | `pytest tests/test_timing.py -q` |
| **P08** transit | `pytest tests/test_transit_trajectories.py -q` |
| **P12** demo (slow, ~2 min) | `pytest tests/test_demo_scenarios.py -q` |

Tip: a single test → `pytest tests/test_bpr.py::test_bpr_at_capacity_is_t0_times_1_15 -v`.

## 3. Verify the product behaves (not just unit tests)
```bash
# A) The deterministic demo metric: baseline calm → surge gridlock → fix eased
python -m torontosim.demo.wc_surge --scenario all
#   expect exhib_p ≈ 0.00 → 0.90 → 0.51 (identical every run)

# B) Performance evidence: full-city vs blast-radius recompute (~15× speedup)
python -m torontosim.perf.bench           # writes data/bench/results.md

# C) The live app — two terminals:
scripts/run_api.sh                         # http://localhost:8000  (OpenAPI at /docs)
scripts/run_frontend.sh                    # http://localhost:5173

#    Then drive the API directly if you like:
curl -s localhost:8000/healthz
curl -s -XPOST localhost:8000/copilot/plan \
  -H 'content-type: application/json' \
  -d '{"prompt":"Ease post-match gridlock near BMO Field without breaking bylaws."}' | python -m json.tool
```
Frontend manual check (the 90-sec demo): **Load the twin → scrub past 17:05
(surge) → copilot hero chip → Apply & recompute (mitigated) → try "close Lake
Shore both ways" (blocked)**. See `demo/RUNBOOK.md`.

## 4. Frontend tests
```bash
cd frontend
npm install            # first time only
npm run test           # 12 vitest (pressure ramp, binary decoder, tickStore, transit)
npm run build          # tsc --noEmit + vite build must succeed
npm run dev            # interactive, against the API on :8000
```

## 5. GPU / LLM checks on the Spark (optional)
These are the 2 tests skipped locally. Run them on `gx10-4f5f` via the harness:
```bash
scripts/spark/push.sh                                              # rsync code up
scripts/spark/run.sh "python scripts/spark/smoke_rapids.py"        # → RAPIDS_OK
scripts/spark/run.sh "python scripts/spark/smoke_ollama.py"        # → OLLAMA_OK
scripts/spark/run.sh "python scripts/spark/smoke_cuopt.py"         # → CUOPT_UNAVAILABLE (expected)
# the two spark-marked tests:
scripts/spark/run.sh "pytest -m spark tests/test_equilibrium_oracle.py::test_gpu_matches_cpu -q"
scripts/spark/run.sh "pytest -m spark tests/test_copilot_plan.py -q"
```
Verdicts are recorded in `infra/README-spark.md`.

## 6. Lint (what CI enforces)
```bash
ruff check src tests          # must be clean
black --check src tests       # must be clean
```

## 7. What "green" looks like
- `pytest -q` → **100 passed, 2 skipped** (skips = Spark GPU + live Nemotron).
- `python -m torontosim.demo.wc_surge --scenario all` → metric monotone baseline→surge→fix, identical on re-run.
- `cd frontend && npm run build` → succeeds; `npm run test` → 12 passed.
- Spark (if reachable): RAPIDS_OK, OLLAMA_OK, both spark tests pass.

## 8. Common gotchas
- **Slow tests**: the equilibrium oracle (`-m slow`) and the demo scenarios load the
  real 18k-edge graph (tens of seconds each). Skip with `-m "not slow"` for speed.
- **`No module named torontosim`** → you forgot `source .venv/bin/activate`.
- **API/WS tests need `httpx`** → it's in the `dev` extra (`pip install -e ".[dev]"`).
- **First frontend run** → `npm install` in `frontend/` before `npm run test/build`.
- Determinism: every sim/demo number is reproducible — if a value changes between
  runs, that's a real regression, not noise.
