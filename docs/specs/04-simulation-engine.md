# P04 — Simulation engine: BPR + Frank-Wolfe equilibrium, AequilibraE oracle, cuGraph path

| | |
|---|---|
| **Priority** | Core (the heart of the product) |
| **Depends on** | P02 (graph), P03 (OD demand) |
| **Owner hint** | Data/sim owner |
| **Status** | not started |

## Goal
Add a **principled, deterministic traffic-assignment engine** — BPR volume-delay + Frank-Wolfe user
equilibrium — alongside Liron's existing k-path loop, with **AequilibraE as a correctness oracle** and an
optional **cuGraph GPU path** for the shortest-path inner loop. Selectable by flag; the existing engine stays as
the CPU fallback. Replace the lookup-table congestion with BPR.

**Why / rubric tie-in:** Technical depth + Insight quality. A real equilibrium solver (provably correct vs
AequilibraE) is the difference between "a demo" and "a planning tool." The cuGraph inner loop is the honest
NVIDIA-acceleration story for the sim.

## Current state (Liron's prototype)
- `simulation/assign_paths.py` — all-or-nothing on top-`k=3` paths via NetworkX `single_source_dijkstra` + 3× edge penalization; trips split by inverse travel time. **Not equilibrium.**
- `simulation/congestion.py` — `congestion_multiplier(pressure)` is a **piecewise lookup table** (1.0/1.2/1.6/2.2/3.0), not BPR; weather speed factor applied.
- `simulation/simulate_traffic.py` — 4 fixed iterations, auto-calibrates OD to `target_pressure=0.55`; produces frames; `apply_scenario`/`simulate_scenario`/`compare_simulations`.
- Deterministic given fixed graph+OD, but **convergence not guaranteed** (fixed 4 iters ≠ user equilibrium). CPU/NetworkX only.

## Target state
- **`congestion_model` flag:** `bpr` (new default) | `legacy` (Liron's lookup). BPR: `t = t0·(1 + α·(v/c)^β)`, α=0.15, β=4 (configurable per road class).
- **`engine` flag:** `equilibrium` (new Frank-Wolfe/BFW) | `kpath` (Liron's, fallback/fast-preview).
- **`backend` flag:** `cpu` (NetworkX) | `gpu` (cuGraph SSSP) — `gpu` only on the Spark, gated by the P00 smoke test.
- **Oracle tests:** assignment matches AequilibraE `bfw` on TNTP networks within tolerance.
- **rgap convergence:** stop on relative gap ≤ target or `max_iter`, both fixed (deterministic).

### In scope
BPR; Frank-Wolfe (→ bi-conjugate FW) UE; rgap convergence; AON loading via SSSP trees; cuGraph SSSP path; AequilibraE oracle harness; determinism hardening; keep frames + scenario compare API stable.
### Out of scope
Blast-radius incremental recompute (P05). Stochastic/logit SUE (note as a flag stub; Dial's algorithm is a stretch). Dynamic/time-stepped DTA.

## Design / implementation plan

### 1. BPR congestion (`simulation/bpr.py`)
```python
def bpr_time(t0, v, c, alpha=0.15, beta=4.0):
    if c <= 0: return float("inf")          # closed/zero-capacity
    return t0 * (1.0 + alpha * (v / c) ** beta)
```
- Per-road-class α/β table in `graph/config.py` (defaults global 0.15/4.0; allow motorway vs arterial tuning).
- Weather factor stays multiplicative on `t0` (reuse `features.weather_speed_factor`).
- `congestion.update_edge_congestion(..., congestion_model="bpr"|"legacy")` dispatches.

### 2. Frank-Wolfe user equilibrium (`simulation/equilibrium.py`)
Standard static UE (ref: Sheffi 1985, *Urban Transportation Networks*):
1. Init link flows `x = 0`; link times `t = t0`.
2. **AON loading:** for each origin zone, SSSP tree under current `t`; load full OD onto shortest paths → auxiliary flow `y`. (This is the parallelizable hot loop — see backend.)
3. **Line search** for `λ∈[0,1]` minimizing the Beckmann objective (fixed-iteration bisection/golden-section — deterministic).
4. `x ← x + λ(y − x)`; recompute `t = bpr_time(...)`.
5. **rgap** `= (Σ t·x − Σ t·y)/(Σ t·x)`; stop when `≤ rgap_target` (default 1e-4) or `iter ≥ max_iter` (default 50).
6. **Upgrade to BFW** (bi-conjugate Frank-Wolfe): combine the last two auxiliary directions — same fixed point, ~3–5× fewer iterations; matches AequilibraE's recommended solver.

### 3. Backends (`simulation/backends/`)
Single interface `sssp_tree(graph, origin, weight) -> (dist, pred)` with two impls:
- **`cpu_networkx.py`** — `nx.single_source_dijkstra` (Liron's current path).
- **`gpu_cugraph.py`** — build `cudf` edge list once; per origin `cugraph.sssp(G, source=o)`; reconstruct predecessor trees; aggregate OD→link loads with cuDF group-bys. **No native multi-source** → loop origins (each call is GPU-parallel over targets). `float64` weights; ordered group-by reductions (not atomics) for determinism.
The FW driver calls the interface; `backend=gpu` requires `RAPIDS_OK` from P00 smoke test, else auto-falls-back to CPU with a logged warning.

### 4. AequilibraE oracle (`simulation/oracle.py`, test-only)
- Fixtures: **TNTP** standard networks (SiouxFalls, Anaheim) — ship `_ab`/`_net`/`_trips` in `tests/fixtures/tntp/`.
- Build the same network in AequilibraE; run `bfw` to tight `rgap_target` (1e-8); capture per-link `results().matrix_ab`.
- Assert our engine's link flows match within tolerance (relative L∞ ≤ 1e-2) and rgap reached.
- Document: assert *within tolerance*, not bit-exact (different FW iterates reach the same UE).

### 5. Determinism hardening
- Fixed `max_iter` + `rgap_target`; never stop on wall-clock.
- **Tie-breaking:** add `+ edge_id_hash·1e-9` epsilon to link costs OR canonicalize predecessors to lowest-id — kills shortest-path-tie nondeterminism (the #1 risk, esp. on parallel cuGraph).
- `float64` everywhere; ordered reductions; no Monte-Carlo. Seed any RNG explicitly.
- CPU↔GPU asserted within tolerance, not bit-identical.

### 6. Keep the public API stable
`simulate_traffic(...)`, `simulate_scenario(...)`, `compare_simulations(...)`, and the frame/`baseline_result.json`
schema stay **unchanged** so P06 (API) and Liron's tests don't break. New behavior is opt-in via the flags above;
default `engine=equilibrium, congestion_model=bpr, backend=cpu`.

## Data / models / sources
- Research: `docs/specs/research/04-sim-engine-rapids.md` (AequilibraE API, BPR/FW math, cuGraph SSSP, RAPIDS-on-ARM risk, determinism).
- AequilibraE 1.6.2 (CPU, pip): https://www.aequilibrae.com/latest/python/static_traffic_assignment.html
- TNTP test networks: https://github.com/bstabler/TransportationNetworks (SiouxFalls, Anaheim — published equilibrium solutions).
- Sheffi (1985) *Urban Transportation Networks* — FW + Beckmann reference.
- cuGraph SSSP: https://docs.rapids.ai/api/cugraph/stable/api_docs/api/cugraph/cugraph.sssp/
- **Risk:** RAPIDS on GB10/sm_121 unverified (`research/04`) → GPU path gated by P00 `smoke_rapids.py`.

## Files to create / modify (delegation list)
**Create**
- `src/torontosim/simulation/bpr.py`
- `src/torontosim/simulation/equilibrium.py` (FW/BFW driver + rgap)
- `src/torontosim/simulation/backends/__init__.py` (interface), `cpu_networkx.py`, `gpu_cugraph.py`
- `src/torontosim/simulation/oracle.py` (test-only AequilibraE harness)
- `tests/fixtures/tntp/` (SiouxFalls + Anaheim)
- `tests/test_bpr.py`, `tests/test_equilibrium_oracle.py`, `tests/test_determinism.py`
**Modify**
- `src/torontosim/simulation/congestion.py` (add `congestion_model` dispatch → `bpr.py`)
- `src/torontosim/simulation/simulate_traffic.py` (add `engine`/`backend`/`congestion_model` flags; route to equilibrium driver; keep k-path path)
- `src/torontosim/simulation/assign_paths.py` (refactor AON loading to use the `sssp_tree` backend interface)
- `src/torontosim/graph/config.py` (per-class α/β table)
- `scripts/spark/smoke_rapids.py` (extend to run a tiny SSSP — already created in P00)

## Test-driven design
Write these **first**:
1. `test_bpr.py` — `bpr_time` monotonic in v; `v=0 → t0`; `v=c → t0·1.15`; `c=0 → inf`. Property: increasing.
2. `test_equilibrium_oracle.py` — load SiouxFalls TNTP; run our `engine=equilibrium`; load AequilibraE `bfw` flows; assert per-link relative L∞ ≤ 1e-2 and rgap ≤ target. (Marked slow.)
3. `test_determinism.py` — run the same scenario twice (CPU); assert byte-identical link flows + summary. Run with an injected tie (two equal-cost paths); assert the tie-break makes it deterministic.
4. **Regression:** Liron's `tests/test_simulation.py` stays green under `engine=kpath` AND under the new default `engine=equilibrium` (loosen only the assertions that assume the old congestion table).
5. **Spark-only** (`@pytest.mark.spark`): `test_gpu_matches_cpu` — on the Spark, `backend=gpu` link flows match `backend=cpu` within tolerance.

## Verification
**Local (CPU):**
```
pytest tests/test_bpr.py tests/test_equilibrium_oracle.py tests/test_determinism.py -q
# + full pipeline still runs:
python -m torontosim.simulation.simulate_traffic --engine equilibrium --congestion bpr   # baseline_result.json written
```
Sanity: equilibrium rgap converges < target within max_iter; SiouxFalls matches AequilibraE.
**On Spark (over SSH):**
```
scripts/spark/run.sh "python scripts/spark/smoke_rapids.py"             # RAPIDS_OK?
scripts/spark/run.sh "pytest -m spark tests/test_equilibrium_oracle.py::test_gpu_matches_cpu -q"
scripts/spark/run.sh "python -m torontosim.simulation.simulate_traffic --backend gpu --engine equilibrium"
```
Record: rgap curve, CPU vs GPU wall-clock on the downtown graph (feeds P11 perf evidence).

## Tasks (subtickets)
- [ ] T04.1 `bpr.py` + per-class α/β config + `congestion_model` dispatch; `test_bpr.py` — *0.5d*
- [ ] T04.2 `backends/` interface + `cpu_networkx` SSSP tree; refactor `assign_paths` AON to use it — *1d*
- [ ] T04.3 `equilibrium.py` Frank-Wolfe + line search + rgap; wire into `simulate_traffic` behind `engine` flag — *1.5d*
- [ ] T04.4 AequilibraE oracle + TNTP fixtures; `test_equilibrium_oracle.py` (SiouxFalls) — *1d*
- [ ] T04.5 Upgrade FW → bi-conjugate FW (BFW); confirm faster convergence, same flows — *0.5d*
- [ ] T04.6 Determinism: tie-break epsilon, float64, ordered reductions; `test_determinism.py` — *0.5d*
- [ ] T04.7 `gpu_cugraph` backend (CPU-authored, Spark-tested); `test_gpu_matches_cpu` (spark) — *1.5d*
- [ ] T04.8 Regression-fix Liron's sim test under new defaults; verify on Spark; record perf — *0.5d*

## Risks / fallbacks
- **RAPIDS won't run on GB10 (sm_121)** → `backend=gpu` auto-falls-back to CPU; the demo runs CPU (18k-edge downtown graph is small — CPU equilibrium is seconds). GPU becomes a "we accelerated where supported" footnote, not a dependency. *This is the single biggest external risk and it is fully contained.*
- **Equilibrium too slow / won't converge live** → `engine=kpath` for interactive preview, `engine=equilibrium` for the committed "accuracy" result; or cap `max_iter` and show rgap. Blast-radius (P05) is the real interactivity answer.
- **AequilibraE aarch64 build friction** → it's CPU/pip; if the Spark build is painful, run the oracle test only on the x86 dev box (it's a correctness check, not a runtime dep).
- **Scenario compare semantics change** with equilibrium → keep `simulate_scenario` using the baseline's calibrated OD (Liron's apples-to-apples approach) so before/after deltas stay interpretable.
