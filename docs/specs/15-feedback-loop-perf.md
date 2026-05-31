# P13 perf — speeding up the Stage-2 residual solves

| | |
|---|---|
| **Status** | proposed (current run uses the slow full-resolve path) |
| **Depends on** | `13-feedback-loop.md`, P05 blast-radius (`blastradius/`), the Stage-2 runner |
| **Owner hint** | AI owner |

## Problem
The Stage-2 pipeline's wall-clock is dominated by the **real-residual phase**: for each of
~111 real closures we run the city-scale equilibrium **open vs closed** and read per-edge
`load`. Today (`feedback/groundtruth/counterfactual.simulate_open_intervened`) each closed
case is a **full Frank–Wolfe re-solve of the entire 94k-edge graph** from free-flow:

- measured ~15–18 s per closed solve (CPU/scipy) → **~30+ min** just for residuals;
- the GPU (cuGraph) backend only helped modestly — each solve rebuilds the cuGraph, so the
  per-solve graph-build overhead caps the gain.

The open solve is already cached (computed once). The waste is **re-solving the whole city
for a single-edge closure** that only perturbs traffic locally, and **rebuilding the routing
structures every closure** even though the open graph + OD are identical across all of them.

## What already exists (reuse, don't rebuild)
- **Blast-radius recompute** — `simulation.simulate_traffic.simulate_scenario(..., recompute="blast")`
  → `_run_blast_scenario` → `blastradius.recompute.blast_assign`. Re-routes **only the OD
  bundles that used a closed link**, over an adaptive subgraph, and reports the affected
  fraction (`blast_stats`). Validated against a full re-solve by `tests/test_blastradius_parity.py`.
- **Path cache** — `blastradius.pathcache.build_path_cache(net, od, base_costs, backend=)`:
  the all-or-nothing shortest-path bundles for the open graph. `_run_blast_scenario` builds
  this **per call** today (line ~560), but it depends only on the open graph + OD → **identical
  for every closure**.
- `simulation.equilibrium.network_from_graph(graph, weather_factor)` → `(net, node_index,
  edge_keys)`; `net.cap[i] <= 0` flags a closed link; `res.flow[i]` is the per-edge load.

## Optimizations (ranked by payoff)

### 1. Blast-radius recompute for the CLOSED solve — the big one (~5–10×)
Replace the full closed re-solve with `blast_assign`. A single closure perturbs a small
subgraph, so we re-route only affected bundles instead of re-solving the whole city.
**Touch point:** add a blast variant of the sim adapter rather than editing
`counterfactual.simulate_open_intervened` in place (that one is the verified full-fidelity
path — keep it as the fallback/parity oracle):

- `feedback/real_residuals.py` (or a new `feedback/blast_sim.py`): build `net, node_index,
  edge_keys` **once**; build the **open path cache once**; expose
  `simulate_open()` = AON open loading from the cache, and `simulate_intervened(ops)` that
  flags the closed `edge_id`s (`net.cap[i] = 0`, `new_costs[i] = inf`) and calls
  `blast_assign(net, od, cache, changed, new_costs, backend=...)`, returning `{edge_id: load}`
  keyed exactly as `counterfactual._flows` (`d.edge_id or f"{u}-{v}-{k}"`).
- Thread a `solver="blast"|"full"` choice into `build_real_residuals` and the runner
  (`--residual-solver`, default `blast`).

### 2. Reuse the open path cache across all closures (stacks with #1; ~111× fewer cache builds)
`_run_blast_scenario` rebuilds `build_path_cache` every call. In our adapter the open graph +
OD are fixed, so build `net` + `cache` **once** and reuse for all closures — the per-closure
cost collapses to just `blast_assign` over the affected subgraph.

### 3. Warm-start — if we keep full equilibrium fidelity (middle ground)
If a run wants true BPR equilibrium (not the AON-blast approximation), start each closed
Frank–Wolfe from the **cached open flows** instead of free-flow so it converges in far fewer
iterations. Lower risk than blast (same model), smaller win. Needs a `warm_start=` hook on the
equilibrium solve (`_run_equilibrium` currently starts from `reset_loads`).

### 4. Parallelize the independent closures (orthogonal; N×)
The ~111 closures are independent. A process pool over the GB10 cores runs them concurrently.
Cost: one ~94k-edge graph copy per worker (memory) and more orchestration. Do **after** #1/#2,
since blast makes each solve cheap enough that parallelism may be unnecessary.

### Already applied
Capped Frank–Wolfe (`max_iter`), loose `rgap`, cached open solve, GPU backend default
(`--sim-backend gpu`, auto-fallback to CPU).

## Fidelity tradeoff — must keep residuals consistent
Blast is an **all-or-nothing** approximation over an adaptive subgraph: it drops the full BPR
congestion-equilibrium feedback the full solver has. That is *fine and the intended speed
feature*, but **both** sides of every residual must use the same method:
`r_sim = sim_int − sim_open` and `r_obs = observed − sim_open` require `sim_open` to be the
**matching AON open loading from the same cache**, not the equilibrium open solve. Mixing an
equilibrium `sim_open` with a blast `sim_int` would inject method-bias into the residual. The
runner must therefore pick one solver for *both* legs and record it in the metrics JSON.

## Verification
- **Parity:** on a handful of real closures, compare blast vs full per-edge `load` at the
  observed sites; reuse the tolerance from `tests/test_blastradius_parity.py`. Report the
  affected-subgraph fraction (`blast_stats`) — the speedup evidence.
- **Gate stability:** re-run the activation gate with `solver=blast` vs `solver=full` on the
  same held-out closures; the ship/keep verdict should not flip (or, if it does, that itself is
  worth reporting — the approximation changed the answer).
- **Timing:** log residual-phase seconds for full vs blast; target ~30 min → a few min.

## Tasks
- [ ] T-perf.1 Blast sim adapter (build net+cache once; blast_assign per closure) + edge-key parity with `counterfactual._flows`.
- [ ] T-perf.2 `--residual-solver {blast,full}` in the runner; record solver + `blast_stats` in the metrics JSON; ensure sim_open and sim_int share the solver.
- [ ] T-perf.3 Parity + gate-stability check (blast vs full on a held-out subset).
- [ ] T-perf.4 *(optional)* warm-start hook for the full-equilibrium path.
- [ ] T-perf.5 *(optional)* process-pool parallelism over closures.
