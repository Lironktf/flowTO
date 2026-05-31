# P13 — Closure/Opening Feedback Loop: sim-pretrained GNN, real fine-tune, sim-as-judge gate

| | |
|---|---|
| **Priority** | High (stretch-core) |
| **Depends on** | P04 (sim), P03 (ODME), `models/gnn/` baseline (merged), **P14 (dataset)**, P10 (consumer) |
| **Owner hint** | AI owner (GNN = Liron's area — this **extends** `models/gnn/`, does not replace it) |
| **Status** | not started |

## Goal
Close the loop the whiteboard describes: learn open-road flow → **predict an intervention's
impact** (a closure *or* a reopening) → compare to **what actually happened** → train on the
**delta**. Concretely: a GNN that, given an intervention (edge mask: close / capacity-down /
reopen / capacity-up), predicts the **per-edge flow residual on top of the deterministic
Frank-Wolfe sim**, pre-trained on unlimited sim-generated scenarios and fine-tuned on real
Toronto interventions, shipped **only if it beats the sim's own residual** on a held-out real set.

**Why / rubric tie-in:** the "AI that learns from reality" story (NVIDIA local-training on the
GB10 + Prime Intellect / Verifiers bounty — Δ-vs-observed is the verifiable reward). The sim
stays the source of truth; the GNN is a fast, reality-corrected pre-screen for the optimizer (P10).

## Current state
- **Sim (P04)** — `simulate_traffic(engine="equilibrium", backend="scipy")` runs deterministic
  Frank-Wolfe/BPR (verified vs SiouxFalls) and writes per-edge `load`. `apply_scenario()` +
  `src/torontosim/graph/mutations.py` give `close_edge` / `reopen_edge` / `change_capacity` /
  `add_edge`. `compare_simulations()` diffs two runs. This **is** the intervention predictor today.
- **Baseline GNN (`models/gnn/`, merged — Liron's)** — `GraphSAGEEdgePredictor` predicts
  open-road `pressure = observed_count / capacity` per edge from **7 node + 21 edge + 14 context**
  feats (`utils.py: NODE_/EDGE_/CONTEXT_FEATURE_NAMES`). **No intervention input.** Full
  `build_gnn_dataset → train_gnn → predict_gnn_baseline → gnn_to_sim_adapter` pipeline with
  standardizers + CLI. Open-road baseline **only**, by design.
- **Real intervention dataset already exists (v1)** — on branch `dataset-creation`:
  `data/dataset/restriction_traffic_dataset.csv` (**313 rows / 111 distinct closures / 173 with a
  before–during baseline**, signed `vol_delta` labels) built by `build_dataset.py` (cuDF) from a
  **snapshot of the live CART road-restrictions feed** (`v3.csv` → `restrictions_clean.csv`,
  2,696 restrictions) joined to TMC. **P14 hardens and extends this** (openings, confounders, more
  sources, sim-counterfactual). The live feed is live-only — but it *was* snapshotted, so real
  closures **are** in hand (forward-from-snapshot, not deep history).
- **ODME (P03)** — `odme_calibrate.build_grounded_od()` scales seed OD to match real TMC counts.
- **Validation core** — `model/validate_past.py:compare_predicted_observed()` returns
  `{n, mae, rmse, pct_error}` over shared edge_ids. This is the gate metric; do not reinvent it.
- **Gap** — no intervention-conditioned model, no sim-generated training set, no two-stage train,
  no activation gate. P13 is that loop; P14 is the data that feeds it.

## Target state
- `src/torontosim/feedback/` module + a two-stage pipeline:
  1. **Scenario generator** emits `(intervention mask → equilibrium flow)` pairs from the sim at
     scale — closures **and** openings (`add_edge` / capacity-up).
  2. **Intervention-conditioned GNN** (GraphSAGE backbone reused) predicts per-edge **residual
     Δflow over the deterministic baseline**, given the edge mask.
  3. **Stage-1** pre-train on sim pairs (unlimited labels, teaches rerouting physics both ways) →
     **Stage-2** fine-tune on the **real intervention dataset** (P14 — the feedback step).
  4. **Activation gate**: on held-out real interventions, ship the GNN **iff** its residual
     MAE/RMSE beats the deterministic sim's. Optional Verifiers reward wraps the same comparison.
  5. The fine-tuned model is a **fast pre-screen for P10**; the sim verifies top-K.

### In scope
Sim scenario generator (close + open) + sampling; intervention mask as a GNN input; residual
target; two-stage train; consuming the P14 real dataset; held-out gate; P10 integration.
**Optional (flagged):** Verifiers reward env; live-feed forward-logging cron.

### Out of scope
The dataset build itself (**P14**). Re-speccing the baseline GNN (Liron's). Demand/OD (P03). The
optimizer search (P10). Signal-timing / multimodal interventions beyond road-edge close/open.

## Design / implementation plan

### A. Ground truth — the real intervention labels (owned by P14)
The hard blocker (historical closures) is resolved pragmatically: the live CART feed was
**snapshotted** (`v3.csv`), giving 2,696 real restrictions with `StartTime`/`EndTime`; **P14**
joins them to TMC and produces signed observed deltas. **The full sourcing table, the
sim-as-counterfactual join, confounder controls, openings, and the honest yield live in
`docs/specs/14-closure-dataset.md` and the catalogue `research/07-feedback-datasets.md`.** What
P13 needs from that data:

- **Real label = signed observed delta** per affected/nearby link: the existing dataset gives
  `vol_delta = during_vol_mean − base_vol_mean` (observed during the intervention vs a matched
  pre-intervention baseline at the same `centreline_id`). Openings reuse the same machinery on the
  *after-EndTime* window (during-vs-after-reopening delta).
- **Residual framing for training.** Run the sim **open** and **intervened** on the same OD →
  `sim_open`, `sim_int`. The GNN's Stage-2 target is the **real residual**
  `r_obs = observed − sim_open` at links with an observed count in the window; the sim's own
  residual is `r_sim = sim_int − sim_open`. The gate asks whether the GNN predicts `r_obs` better
  than `r_sim`. Where a site has **no** observed pre-baseline (the common case — see yield), the
  sim's `sim_open` *is* the counterfactual "before", so the residual is still defined.
- **Honest yield** (scoped from disk + the realized v1 dataset): the on-disk TMC subset has 1,897
  `centreline_id`s, 70% surveyed once, only 30% repeat (median 212 days apart); the realized real
  dataset is **313 rows / 111 closures / 173 with baseline**. Openings will be **thinner** still.
  → enough to **fine-tune + gate**, not to train from scratch. **Stage-1 sim pre-training carries
  the physics.** Real labels are "calibration-ready" where thin; never overstated.

### B. Scenario generator (sim pre-train data) — `feedback/scenario_gen.py`
Script the engine to emit `(intervention mask → residual flow)` pairs, **both directions**:
1. Load the Toronto graph + an ODME-grounded OD for a sampled time context.
2. **Baseline:** `simulate_traffic(graph, od, engine="equilibrium", backend="scipy",
   auto_calibrate=False, copy_graph=True)` → `sim_open` per-edge `load`.
3. **Sample an intervention** on a copy, road-class-stratified (bias toward arterials/collectors
   that actually reroute), single- and multi-edge:
   - **Closures:** `{op:"close_edge"}` and partial `{op:"change_capacity", multiplier:<1}`.
   - **Openings:** `{op:"change_capacity", multiplier:>1}` and `{op:"add_edge", …}` (new
     link/lane) — the symmetric case the optimizer's "fix" plans need.
4. **Intervened:** re-solve same OD → `sim_int`.
5. **Label** = residual `Δpressure(e) = (sim_int(e) − sim_open(e)) / capacity(e)` per edge (the
   target type Stage-1 and Stage-2 share — see §C). Store the mask, both flow fields, OD id, time
   context, intervention sign.
6. **Scale + GPU.** Embarrassingly parallel over scenarios; use the existing `backend="gpu"`
   (cuGraph) / Warp path on the GB10 for O(10⁴–10⁵) solves. Determinism preserved (float64,
   stable sort, seeded sampling; vary by index, not `random`).

### C. Model & training — `feedback/{model,dataset,train}.py`

**Feature design — put features in the right half of the architecture.**
`README_MODEL_SIMULATION.md` §1–2 documents the deliberate split: the **ML model** predicts *how
much traffic wants to exist* (demand), **graph routing** decides *where it flows*, and
**propagation** handles *what changes when the graph changes*. The baseline GNN inherited the
**demand model's** features (`src/model/features.py:FEATURE_ORDER` — `distance_to_downtown`,
`near_highway`, `road_class_rank`), which answer the demand question. But the closure/opening
**residual GNN lives in the routing/propagation half** — it models how the network *reacts*, and
the sim already injected demand via the OD matrix. So we **prune the demand priors** and add
closure-aware + sim-base channels. Features are organized into **named channels** so new
attributions/layers plug in additively (a missing channel → zero/learned default), enabling weather
enrichment and the S1/S2 multimodal layers **without retraining from scratch**:

| Channel | Features | vs baseline |
|---|---|---|
| **Node (structural + spatial PE)** | `in_degree`, `out_degree`, **learned positional encoding of `lat/lon`** | DROP `degree` (=in+out, redundant), `distance_to_downtown_km` (demand prior — wrong half), `pagerank` (dead-by-default). **KEEP** the spatial signal — but as a learned PE, not raw coords. *Benchmarked (research/08): dropping the redundant + downtown features was a small **win**; dropping coords outright cost ~9% MAE → encode them.* |
| **Edge static (road)** | `length_m`, `capacity`, `base_time_min`, `speed_kmh`, `lanes`, `one_way`, `bearing_sin/cos`, `road_class` one-hot (10) | DROP `road_class_rank` (dup of one-hot), `from/to_node_degree` (dup of node feats) |
| **Edge intervention (NEW)** | `intervention_mask ∈ {0,1}`, `capacity_mult ∈ [0,∞)` (0 closed · <1 partial · 1 unchanged · >1 added), `graph_dist_to_intervention` (hops), `alt_capacity_headroom` (do parallel routes exist) | net-new — the closure/opening conditioning |
| **Edge sim-base (NEW)** | `sim_open_load`, `sim_open_pressure` | net-new — **residual learning**: the equilibrium baseline the GNN corrects |
| **Context (time+weather)** | keep hour/dow/month/weekend/rush/season; **ENRICH weather** to continuous `temp_c`, `precip_mm`, `snow`, `visibility_km`, `wind_kmh` (per `research/07`), keeping categorical flags | replaces the coarse clear/rain/snow bucket |
| **Context (attribution flags)** | `event_nearby` (FIFA/festival/venue), `incident_nearby` (KSI), `ttc_disruption_nearby`, `holiday/school` | net-new plug-in channel (P14 Phase 5) |
| **Multimodal layers (FUTURE)** | per-edge `transit_load` (P08), `ped_volume`/`bike_volume` | TMC already carries `*_appr_peds`/`*_appr_bike` → ped/bike labels exist; wires S1/S2 in additively |

- **Intervention is an input, not a retrain.** One forward pass scores any closure/opening via the
  intervention channel; the graph topology is unchanged.
- **Reuse the GraphSAGE backbone** with the new `edge_in_dim` and a **signed residual head** — drop
  the `softplus` (`model.py:76`) so the residual can be negative; identity or `asinh` for heavy
  tails. Keep the standardizer machinery from `utils.py`. Feeding `sim_open` as input keeps the
  shallow 2-hop receptive field viable (the global reroute is already in the input) and is
  data-efficient — critical given the thin real labels.
- **Target = residual Δpressure over the deterministic baseline** = `(sim_int − sim_open)/capacity`
  (signed, scale-free, in the baseline's pressure units; handle closed-edge `capacity→0`).
  Justification: (i) the sim gives the bulk of the response for free — the model learns only the
  *correction*; (ii) the gate is *literally* "beat the sim's residual"; (iii) sim stays source of
  truth; (iv) matches the S3 surrogate framing.
- **Loss = blast-radius-weighted** `SmoothL1` (reuse P05 cones to up-weight edges inside the
  intervention's blast radius) so the zero-residual majority doesn't drown the affected edges.
- **Two-stage:** **Stage-1** sim pre-train (B pairs; reuse `train_gnn.py` loop — AdamW, lr 1e-3,
  seed 42; unlimited labels, both directions). **Stage-2** warm-start → fine-tune on the P14 real
  residuals (low lr, early-stop on the held-out real set). **This is the feedback step.**
- **Flagged-optional refinements:** flow-conservation penalty (net Δflow at each node ≈ 0,
  PhysicsNeMo-style); per-edge uncertainty/variance head (so P10 knows when to trust the GNN vs the
  sim); bidirectional message passing (reverse edges so each edge sees up- and downstream context).
- **Code deltas (additive — import Liron's helpers, don't edit in place):** `feedback/dataset.py`
  wraps `build_gnn_dataset.py` helpers (`fit_standardizer`, `context_vector`, node/edge builders)
  to emit the channels above for intervention-conditioned samples; `feedback/model.py` thin subclass
  (new `edge_in_dim`, residual head); `feedback/train.py` Stage-1/2 driver →
  `models/gnn/gnn_intervention_residual.pt` + `data/gnn/intervention_training_metrics.json`.

### D. Validation & the activation gate — `feedback/gate.py`
- **Held-out real interventions** (grouped split by `centreline_id` so no location leaks; plus a
  **temporal split** — train earlier interventions, test later — to mimic deployment). Metrics:
  residual **MAE/RMSE** via `compare_predicted_observed()` (`predicted` = GNN Δpressure, `observed`
  = `r_obs`) **and** a **rank / top-K impacted-edge** overlap + scenario summary-delta (what P10
  actually consumes — exact per-edge flow matters less than getting the worst edges right). Report
  closures and openings separately.
- **Gate:** `err_sim = rmse(r_sim, r_obs)` vs `err_gnn = rmse(r_gnn, r_obs)` on the **same** links
  (and the rank metric vs the sim's). **Ship the GNN iff `err_gnn < err_sim − ε`** with a
  minimum-n guard. Else the sim stays the predictor — fail honestly, no silent ship.
- **Optional — Verifiers env** (flagged): wrap "Δ-vs-observed < ε" as a Prime Intellect Verifiers
  reward over the held-out set. Off the critical path.

### E. Integration with the optimizer (P10) — `feedback/predict.py`
`predict_intervention_residual(graph, mask, time_context) → {edge_id: Δflow}`, applied on top of
one cached `sim_open` solve. P10's search uses it as a **fast pre-screen** to rank many candidate
interventions (closures *and* capacity-adds), then **the sim verifies top-K**
(`simulate_scenario(recompute="blast")`). Sim stays the judge; the GNN narrows the search. Reuses
the `gnn_to_sim_adapter.py` write-back pattern.

### G. Benchmarks & regression — `feedback/benchmark.py`
Prove the reworked GNN is *better, not just different*, and guard against silent regressions. Two
distinct comparisons (don't conflate them):

**(1) Same-task A/B — "is the branch's GNN better than main's?"** Both configs train on the **same
frozen dataset + split + seed**; only the **feature config** varies, so any delta is the model's,
not env/data skew. This is the rigorous way to compare main vs this branch (a naive branch-checkout
would skew on data/env — keep it only as a fallback for true model-*code* diffs).
- **Configs:** `baseline` (main's 7-node/21-edge features, softplus pressure head) vs `pruned`
  (the §C lean set) — plus ablation variants: `−distance_to_downtown`, `−redundant`, `pruned+PE`.
- **Metrics:** val **MAE / RMSE / R² / risk-accuracy** (reuse `utils.py` metrics) **and** a
  **spatial-holdout** eval (train on a subset of `centreline_id`s, test on *unseen* ones) — the
  direct probe of the `lat/lon` memorization risk. **Decision rule:** ship the prune iff val error
  is within tolerance **and** spatial-holdout error is ≤ baseline (ideally lower).
- **Result (ran 2026-05-31, GB10 — see `research/08-gnn-feature-benchmark.md`):** over 30 epochs ×
  3 seeds, dropping the redundant features + `distance_to_downtown` was a **small win**
  (`ablate_redundant` MAE 0.2019 vs `baseline` 0.2026, std 0.0002); dropping `lat/lon` outright was
  clearly worse (`pruned` MAE 0.2210, R² 0.41 — ~9% regression). → drop the dead weight, **keep
  coords as a learned PE**. (Pressure-task A/B; the residual-task verdict is the §D gate.)

**(2) New-capability — "does the closure GNN beat the sim?"** main can't do this, so the comparison
is to the **deterministic sim**, i.e. the activation gate (§D): `err_gnn` vs `err_sim` on held-out
real interventions, plus the rank/top-K metric. Supporting ablations:
- **`sim_open`-as-input** on vs off → quantify the residual-learning data-efficiency gain.
- **Loss** blast-weighted vs plain → confirm plain collapses toward predicting ~0.
- **Data-efficiency curve:** metric vs #real fine-tune examples (matters at ~173 rows).
- **Speed:** GNN inference ms/intervention vs full-sim seconds (the P10 pre-screen value prop;
  reuse P11 `perf/bench`).

**Regression guard.** Before any change, capture the current baseline's `training_metrics.json` as
the **locked reference** (none exists on disk today — establish it on the first Spark run). A CI
check fails if a config's metrics drift beyond tolerance from its frozen reference; determinism
(same seed+data → byte-identical metrics) is asserted. The harness emits a side-by-side
`benchmark_report.{json,md}` (config · metric · delta · winner).

**Local vs Spark.** Metric computation, the config registry, comparison, and reporting are **pure
NumPy/Python** → unit-tested locally without torch. The train/eval that produces the per-config
metrics needs torch/PyG → runs on the GB10/Spark (`scripts/spark/benchmark_gnn.sh`), with a
CPU-fallback for tiny smoke configs.

## Data / models / sources
- **Real intervention dataset + sourcing + confounders:** `docs/specs/14-closure-dataset.md`
  (build) + `docs/specs/research/07-feedback-datasets.md` (catalogue). Both cross-reference
  `research/01-toronto-datasets.md` for CKAN/TMC/centreline mechanics.
- **Sim + OD:** P04 (`simulation/*`), P03 (`model/odme_calibrate.py`).
- **Baseline GNN reused:** `models/gnn/{model,utils,build_gnn_dataset,train_gnn,
  gnn_to_sim_adapter}.py`.
- **Stack (verified, `06-spark-setup-verified.md`):** torch 2.12 cu130 + pure-Python PyG 2.7 +
  Warp 1.13 on the GB10; XGBoost edge-regressor as the always-works residual fallback.

## Files to create / modify
**Create:** `src/torontosim/feedback/{__init__,scenario_gen,dataset,model,train,gate,predict}.py`;
`scripts/spark/gen_scenarios.py` (GPU fan-out); `tests/test_scenario_gen.py`, `tests/test_gate.py`;
optional `scripts/feedback/log_road_restrictions.py` (live-feed cron) + `feedback/verifier_env.py`.
**Modify:** `models/gnn/README_GNN.md` (add an "intervention-residual extension → P13/P14"
pointer; do **not** edit Liron's model code in place); `docs/07-training-feedback-loop.md` (mark
P13/P14 as the build-ready specs).

## Test-driven design
- `test_scenario_gen.py` (first): closing a known bottleneck yields `sim_int ≠ sim_open` with flow
  conserved (Σ OD trips preserved minus stranded); **adding** capacity attracts flow (signed Δ has
  the right sign); generation is deterministic (same seed → identical Δflow).
- `test_gate.py`: a model reproducing `r_obs` passes; one returning the sim's residual
  (`r_gnn == r_sim`) does **not** pass (must beat the sim by ε); gate refuses below min-n; closures
  and openings reported separately.
- **Spark-only** (`@pytest.mark.spark`): `gen_scenarios.py` produces N pairs on the GPU backend
  matching the CPU backend's Δflow within tolerance (cross-backend determinism).
- *(Dataset-side TDD lives in P14.)*

## Verification
**Local (CPU):** run `scenario_gen` for a handful of closures **and** openings → inspect Δflow
plausibility (reroute around closures; attract onto added capacity; conserved); run the gate on a
tiny held-out set and confirm it reports `err_gnn` vs `err_sim` and ships only on a strict win.
**On Spark:** Stage-1 pre-train on O(10⁴) GPU-generated pairs (bf16 on Blackwell), then Stage-2
fine-tune on the P14 real residuals; log Stage-1/2 MAE/RMSE + the final gate decision to
`intervention_training_metrics.json`. Target: Stage-1 converges; Stage-2 either beats the sim on
held-out real interventions (ship) or not (keep the sim — reported honestly).

## Tasks
- [ ] T13.1 Scenario generator (`scenario_gen.py`, close + open) + `test_scenario_gen.py` — *1d*
- [ ] T13.2 GPU fan-out (`scripts/spark/gen_scenarios.py`, cuGraph/Warp) + cross-backend test — *1d*
- [ ] T13.3 Intervention-conditioned dataset/model/residual head (`dataset.py`, `model.py`) — *1d*
- [ ] T13.4 Two-stage trainer (`train.py`): Stage-1 sim pre-train → Stage-2 real fine-tune — *1d*
- [ ] T13.5 Activation gate (`gate.py`) + `test_gate.py` (GNN must beat the sim) — *0.5d*
- [ ] T13.6 P10 pre-screen integration (`predict.py`) — *0.5d*
- [ ] T13.7 **Benchmark harness** (`benchmark.py`): config registry + NumPy metrics + spatial-holdout
      + A/B comparison + `benchmark_report.{json,md}` + `test_benchmark.py` (local, no torch) — *1d*
- [ ] T13.8 Regression guard: freeze baseline `training_metrics.json` on Spark + CI drift/determinism
      check + `scripts/spark/benchmark_gnn.sh` — *0.5d*
- [ ] T13.9 *(optional)* Live-feed forward-logging cron — *0.5d*
- [ ] T13.10 *(optional)* Verifiers reward env (`verifier_env.py`) — *0.5d*
- [ ] *(dataset tasks T14.x in `14-closure-dataset.md`)*

## Risks / fallbacks
- **Real yield too thin to fine-tune** (likely, esp. openings) → Stage-1 sim-pretrained model
  still ships if it beats the sim; real data labeled "calibration-ready"; pursue deeper sources
  (P14: BDIT RoDARS, utility-cut, forward-logging). Never overstate real volume.
- **Confounders dominate the residual** (effect not separable from weather/incidents/events) →
  P14's matched-control + adjustment; drop unidentifiable cases; report how many survived.
- **GNN doesn't beat the sim** → the gate keeps the sim — a *correct* outcome, not a failure to
  hide. The verified comparison is the value either way.
- **GPU scenario gen diverges from CPU** → cross-backend determinism test (T13.2) gates it;
  CPU/scipy generation is the always-works fallback.
- **XGBoost fallback** — if PyG/GNN training is unstable on the GB10, an XGBoost edge-regressor on
  the same intervention-conditioned features predicts the residual; the gate is model-agnostic.
