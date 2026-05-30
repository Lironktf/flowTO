# P05 — Blast-radius adaptive subgraph recompute

| | |
|---|---|
| **Priority** | Core (the headline performance feature) |
| **Depends on** | P04 |
| **Owner hint** | Data/sim owner |
| **Status** | not started |

## Goal
When a planner makes an intervention, **recompute only the affected subgraph** instead of re-solving all of
Toronto — with adaptive boundary widening when edge pressure shifts past a threshold. This is what makes the tool
feel *instant* (sub-100ms target for a local closure) and is the spec's named core innovation.

**Why / rubric tie-in:** Performance + Insight quality + Spark story. Side-by-side "full-city recompute vs
blast-radius recompute" latency is the concrete performance evidence judges reward.

## Current state
- Liron's `simulate_scenario` re-runs the **whole** 4-iteration simulation on a graph copy for every scenario. Correct but not incremental — fine at 18k edges, doesn't showcase the "only recompute what changed" story and won't scale to citywide interactivity.

## Target state
- `blastradius/recompute.py`: given a **changed edge set `C`**, the baseline path cache, OD bundles, and current edge costs → identify affected OD paths, build an **adaptive subgraph**, re-run equilibrium **only there**, freeze boundary inflows/outflows, and widen if boundary pressure changes exceed threshold.
- Two modes: **speed** (cached alternatives only — for live dragging) and **accuracy** (full affected-OD recompute — on release / final compare).
- Returns the same edge-state delta shape `compare_simulations` already produces.

### In scope
Affected-path detection, subgraph extraction, boundary freezing + adaptive widening, speed/accuracy modes, the parameter table below, latency instrumentation.
### Out of scope
The full-city solver (P04 — used here as the "accuracy"/validation reference and to seed the path cache). GPU specifics beyond reusing P04's backend.

## Design / implementation plan
(Per the spec's algorithm + `research/04` graph ops.)
```
Input: changed edge set C, time slice, baseline path cache, OD bundles, current edge costs
1. affected_paths = all cached OD paths containing any edge in C
2. seed changed edges + endpoints
3. build upstream + downstream cones with bounded Dijkstra/BFS:
     - reverse from each changed-edge tail toward likely origins
     - forward from each changed-edge head toward likely destinations
4. weight cone expansion by road class, current pressure, edge betweenness
5. add parallel alternatives whose generalized cost within ε of the old path
6. always include expressway/highway connector core (non-local detours)
7. add a 1–2 intersection safety buffer
8. freeze boundary inflows/outflows from the previous (baseline) simulation
9. recompute OD bundles crossing the affected subgraph (equilibrium, P04 engine)
10. if boundary pressure change > threshold → widen radius and rerun
```
**Parameters (defaults):** start radius 8 min free-flow / 2 km; max radius 20 min / 6 km; boundary widening threshold 8% pressure change; flow-change cutoff 2% (prune low-impact frontier); highway core always included; **speed mode** = cached alternatives only; **accuracy mode** = full affected-OD recompute inside radius.
- **Path cache** (`blastradius/pathcache.py`) — precompute top-k routes per OD bundle at baseline (reused from P04's AON trees); store `{od_bundle_id: [path_id…]}` and reverse index `{edge_id: [path_id…]}` for O(1) affected-path lookup.
- **Determinism** — same `C` + baseline → identical subgraph + result (fixed widening order, id tie-breaks).

## Data / models / sources
`research/04` (cuGraph SSSP/BFS for cones, NetworkX fallback, determinism). Reuses P04 equilibrium engine + backends. Spec §8 parameter table.

## Files to create / modify
**Create:** `src/torontosim/blastradius/{__init__,recompute,pathcache,cones}.py`; `tests/test_blastradius.py`, `tests/test_blastradius_parity.py`.
**Modify:** `simulation/simulate_traffic.py` (`simulate_scenario` gains `recompute={full,blast}`; `blast` calls blastradius); `simulation/equilibrium.py` (accept a node/edge subset to solve over).

## Test-driven design
- `test_blastradius.py` (first): close one edge → affected subgraph **contains** the changed edge + its detour corridor and **excludes** far-away untouched edges; subgraph size << full graph.
- `test_blastradius_parity.py` (**the key correctness test**): blast-radius result ≈ full-recompute result on the affected edges within tolerance (accuracy mode); if boundary pressure exceeds threshold, widening kicks in and closes the gap. Assert blast-radius is **strictly faster** (node/edge count + wall-clock).
- Determinism: same closure twice → identical subgraph + deltas.

## Verification
**Local:** `simulate_scenario(..., recompute="blast")` on a downtown closure → returns deltas matching `recompute="full"` on affected edges; print affected subgraph size (% of graph) + local wall-clock.
**On Spark:** measure **full-city recompute latency vs blast-radius latency** side-by-side (the demo/perf evidence, feeds P11); target sub-100ms local closure (accept <250ms with visible progress).

## Tasks
- [x] T05.1 `pathcache.py` (top-k per OD + edge→paths reverse index) — *1d*
- [x] T05.2 `cones.py` upstream/downstream bounded Dijkstra/BFS + weighting — *1d*
- [x] T05.3 `recompute.py` subgraph build + boundary freeze + adaptive widening — *1.5d*
- [x] T05.4 speed vs accuracy modes; wire into `simulate_scenario` — *0.5d*
- [x] T05.5 Parity test vs full recompute + determinism + latency instrumentation — *1d*

## Risks / fallbacks
- **Blast-radius misses a non-local reroute** (highway/ravine detour) → the "always include expressway core" rule + accuracy-mode full-affected-OD recompute; parity test guards this.
- **Widening never converges** → hard max radius (20 min / 6 km); beyond that, fall back to full recompute (still seconds at downtown scale).
- **If it's too complex to finish** → `recompute="full"` (Liron's path) is the always-available fallback; blast-radius is a perf upgrade, not a correctness dependency.
