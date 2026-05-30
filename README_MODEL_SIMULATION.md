# flowTO — Demand Model & Traffic Simulation Layer

This layer sits on top of the road graph (`src/graph`, `data/graph/`) and turns a
**time/date/weather context** into a **congested road network**: it predicts how
much traffic wants to exist, routes that traffic across the graph, and computes
load / pressure / travel-time / risk for every edge. It is built so that
**scenario changes** (close / add / remove / re-capacity an edge) re-run the
exact same engine and can be diffed against the baseline.

```
time context ──▶ DEMAND MODEL ──▶ node demand
                                     │
                                     ▼
                              OD MATRIX (gravity)
                                     │
                                     ▼
        ┌────────── PROPAGATION LOOP (×N iterations) ──────────┐
        │  assign trips to top-k paths (by current_time_min)   │
        │  → add load to edges                                 │
        │  → pressure = load/capacity                          │
        │  → current_time_min = base × congestion(pressure)    │
        │  (next iteration reroutes on the new times)          │
        └──────────────────────────────────────────────────────┘
                                     │
                                     ▼
                         baseline_result.json
```

## 1. What the model predicts

`location + time/date/weather + road context → vehicle_count`

Features (`src/model/features.py`, `FEATURE_ORDER`):
`lat, lon, hour, day_of_week, month, is_weekend, weather_code, road_degree,
distance_to_downtown, near_highway, road_class_rank`.

Target: `vehicle_count` — a **numeric** demand estimate per node (not a
low/med/high class). Model: `HistGradientBoostingRegressor` (sklearn), saved to
`models/demand_model.pkl`. An optional GPU `xgboost` backend exists for training
on a box like the ASUS GX10 (see §8).

## 2. Why it predicts *baseline* demand, not scenario impact

The model never sees road closures or additions. It answers only **"how many
cars want to move near here, normally, at this time?"** That separation is
deliberate:

- **ML model** → how much traffic *wants* to exist (stable, learnable from
  historical counts).
- **Graph routing** → *where* that traffic flows given the current graph.
- **Propagation** → what happens when the graph changes.

If the model tried to predict closure impact directly, it would need training
examples of every possible closure — impossible. Instead, demand stays fixed and
the **graph algorithm** reacts to changes. Close a road and the same cars simply
reroute; the engine, not the model, discovers the new congestion.

## 3. How OD demand is generated (`generate_od_matrix.py`)

A gravity model converts per-node demand into origin→destination trips:

```
OD(i, j) = origin_strength(i) · destination_strength(j) / (1 + distance_km)
```

- `origin_strength` / `destination_strength` start from predicted node demand.
- **Road-class biasing**: endpoints on bigger roads get more strength; pure
  residential stubs get less, so trips load arterials, not side streets.
- **Time-of-day biasing**: weekday morning sends outer→downtown, evening sends
  downtown→outer, weekend evening adds downtown/venue pull.
- **Distance penalty** `1 + distance_km` keeps trips local-ish.
- We enumerate only the top-N strongest origins × destinations, keep the top
  `max_pairs` (default 1000), drop pairs <0.4 km or >25 km, and scale the total
  to a nominal volume (the simulator can re-calibrate — see §5).

Output: `[{"origin": node_id, "destination": node_id, "trips": float}, ...]`.

## 4. How cars are assigned to best paths (`assign_paths.py`)

For each OD pair we take up to **k=3** good paths and split trips by
attractiveness `1 / route_time`, then add the result to every edge on each path.
We do **not** dump everything on the single shortest path.

Performance: per origin we run one single-source Dijkstra (shortest path to all
its destinations at once), then get alternates by **penalising** already-used
edges and re-running. Routing uses a plain `_eff_w` edge weight so NetworkX
takes its fast C path; `_eff_w` also encodes closures (huge weight) so closed
edges are avoided automatically.

## 5. How pressure / congestion is calculated (`congestion.py`)

```
pressure = load / capacity

risk:  <0.50 low · <0.75 moderate · <1.00 high · ≥1.00 severe

congestion multiplier:
  <0.50 →1.0 · <0.75 →1.2 · <1.00 →1.6 · <1.25 →2.2 · else →3.0

current_time_min = base_time_min × multiplier
```

Closed edge → `capacity=0`, `pressure=∞`, `current_time_min=∞`, no route uses
it. Bad weather (rain/snow/fog) stretches base time via a speed factor.

**Auto-calibration**: pressure scales linearly with trips for a fixed routing
pattern, so the simulator does one trial pass, measures the mean loaded-edge
pressure, and scales total trips to hit a target (~0.55). This keeps output
plausible regardless of the raw demand magnitude. Turn off with
`auto_calibrate=False` (scenarios use the baseline's already-calibrated trips so
the comparison is apples-to-apples).

## 6. How propagation works (`simulate_traffic.py`)

```
simulate_traffic(graph, od_matrix, iterations=4, k_paths=3)
```

Each iteration: zero loads → assign on the **current** (congested) edge times →
recompute pressure/time/risk → snapshot a frame. Because each pass routes on the
previous pass's times, congestion spreads: an overloaded road becomes slower, so
some drivers shift to alternates, which may then congest too. The loop runs a
fixed number of **adjustment steps** (not literal minutes); the last frame is the
stabilised baseline. Per-iteration frames are saved for animation.

## 7. How this supports scenarios later (already wired)

```python
baseline = simulate_traffic(graph, od)                       # auto-calibrated
scenario = simulate_scenario(graph, baseline["od_matrix"],   # same trips
                             [{"op": "close_edge", "edge_id": eid}])
impact   = compare_simulations(baseline, scenario)
```

`apply_scenario` supports `close_edge, reopen_edge, remove_edge,
change_capacity, close_node, add_edge` (it calls the graph-layer mutations).
When an edge is closed/removed, paths through it become invalid, demand reroutes
to the next-best paths, those congest, travel times rise, and later iterations
shift traffic again — impact propagates with **no model retraining**.
`compare_simulations` returns summary deltas and the most-impacted edges.

## 8. Training on the ASUS GX10 (optional)

The demand model is small tabular gradient boosting — it trains in **seconds on
CPU** (≈40k rows), so the GX10's GPU is genuinely overkill *for this model
today*. It pays off when you scale up: real high-frequency count data, a
deep/temporal/graph model, large hyper-parameter sweeps, or running many
simulations in parallel.

Two ways to use it:

```bash
# A) GPU-accelerated gradient boosting (xgboost) — local or on the GX10:
FLOWTO_MODEL_BACKEND=xgboost python -m src.model.train_demand_model --train

# B) Remote train on the GX10, model pulled back automatically:
scripts/train_on_gx10.sh user@gx10-host xgboost
```

The backend (`sklearn` default, or `xgboost` with `device=cuda`) is selected via
`--backend` or the `FLOWTO_MODEL_BACKEND` env var; everything downstream
(prediction, OD, simulation) is unchanged. The GX10 is aarch64 + CUDA, so use
the CUDA `xgboost` aarch64 build on that box. Inference and simulation always run
locally — only training is offloaded.

## Files

```
src/model/
  features.py            # shared feature engineering (train & predict)
  train_demand_model.py  # synthetic data gen + training -> demand_model.pkl
  predict_node_demand.py # predict_node_demand(graph, model, ctx); heuristic fallback
  generate_od_matrix.py  # gravity OD with time-of-day + road-class biasing
src/simulation/
  congestion.py          # pressure, risk, congestion multiplier, update_edge_congestion
  assign_paths.py        # k-path assignment via Dijkstra + penalisation
  simulate_traffic.py    # propagation loop, scenario sim, comparison
  export_results.py      # baseline_result.json writer
scripts/train_on_gx10.sh # remote/GPU training helper
data/model/training_dataset.csv     models/demand_model.pkl
data/simulation/baseline_result.json
tests/test_simulation.py
```

## Required function signatures (all implemented)

```python
train_demand_model(training_data_path) -> model
predict_node_demand(graph, model, time_context) -> dict[node_id, demand]
generate_od_matrix(graph, node_demands, time_context, max_pairs=1000) -> list
simulate_traffic(graph, od_matrix, iterations=4, k_paths=3) -> simulation_result
update_edge_congestion(graph) -> graph
export_baseline_result(simulation_result, path)
simulate_scenario(graph, od_matrix, scenario, iterations=4) -> scenario_result
compare_simulations(baseline_result, scenario_result) -> impact_result
```

## How to run

```bash
# (build needs the road graph in data/graph/ — see src/graph/README.md)
pip install -r requirements.txt          # adds scikit-learn, pandas, numpy

# 1. (re)generate synthetic training data + train the demand model
python -m src.model.train_demand_model --generate --train

# 2. run the full baseline simulation test (predict → OD → simulate → export)
python -m tests.test_simulation
```

Outputs: `data/model/training_dataset.csv`, `models/demand_model.pkl`,
`data/simulation/baseline_result.json`.

## Training data — important note

**The training data is currently synthetic**, generated from the real road
graph using Toronto-plausible patterns (rush-hour curve, downtown pull,
arterials carry more, weather dampening). This makes the whole pipeline run
end-to-end *today*. The model learns those relationships and recovers them well
(holdout R² ≈ 0.93), but it is learning a generator, not ground truth.

To use **real** Toronto counts, drop a CSV at `data/model/training_dataset.csv`
with the `FEATURE_ORDER` columns + a `vehicle_count` target (a `weather` string
column is also accepted) and re-run training — nothing else changes. Good public
sources: Toronto Open Data "Traffic Volumes at Intersections for All Modes" and
the permanent/short-term count programs. Map a count location to the nearest
graph node with `src.graph.routing.get_nearest_node`.

## Output format

`baseline_result.json` contains `time_context`, `summary`
(`total_assigned_trips`, `average_pressure`, `high_risk_edges`, `severe_edges`),
full `edges` (with load/capacity/pressure/current_time_min/risk), top `nodes` by
predicted demand, an `od_matrix_sample`, and per-iteration `iterations` frames
(active edges only, to bound size). Infinity is encoded as the string
`"Infinity"`.
