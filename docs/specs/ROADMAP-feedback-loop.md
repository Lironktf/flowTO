# Feedback-Loop Roadmap — closure/opening GNN that learns from reality

> **Track:** the realization of stretch **S3 (GNN surrogate)** + **S4 (Verifiers/RL)** plus a new
> **dataset** phase, built on the merged **P03/P04/P10** + `models/gnn/` baseline. **Never** replaces
> them — the deterministic sim stays source of truth.
> **Specs:** `13-feedback-loop.md` (training) · `14-closure-dataset.md` (data) ·
> `research/07-feedback-datasets.md` (dataset catalogue) · `research/08-gnn-feature-benchmark.md`
> (feature evidence). Read those for detail; this sequences them with go/no-go checkpoints.

## 0. The loop in one line
Learn open-road flow → **predict a closure/opening's impact** → compare to **what actually
happened** → train on the **residual** → ship the GNN **only if it beats the sim**. The GNN becomes
a fast pre-screen for the optimizer (P10); the sim verifies the top-K.

## 1. Locked decisions (carry from the specs)
- **Real is the play.** The live CART feed was snapshotted (`v3.csv`, 2,696 restrictions); a v1
  real dataset already exists (313 rows / 111 closures / 173 baselined). Deepen via utility-cut
  permits, BDIT RoDARS (request), and a forward-logging cron. **Data honesty:** thin not fabricated.
- **Target = residual Δpressure over the sim** (signed; drop softplus). Sim stays source of truth.
- **Closures *and* openings** (symmetric; an `EndTime` is a reopening event).
- **Build on Liron's GraphSAGE**; closure enters as an edge channel, not a retrain.
- **Lean features** (`research/08`, run on the GB10): drop `degree`, `distance_to_downtown`,
  `road_class_rank`, `from/to_node_degree`, `pagerank` (a small *win*); **keep coords as a learned
  PE** (dropping them cost ~9% MAE).
- **All model runs on the GB10** (torch/PyG/cuDF live there); local is spec + torch-free tests.

## 2. Phases (track tickets)
| # | Phase | Depends on | Spec |
|---|---|---|---|
| **P14** | Intervention dataset — clean→join→label→openings→confounders→sim-counterfactual→package (8 build phases + cuDF parity) | P01, P02, TMC+weather | `14-closure-dataset.md` |
| **P13** | Feedback-loop training — scenario-gen → 2-stage train → activation gate → P10 integration + the **benchmark/regression** harness | P03, P04, `models/gnn/`, **P14** | `13-feedback-loop.md` |
| **P13-opt** | Verifiers reward env + live-feed forward-logging cron | P13 | `13` §D/appendix |

## 3. Checkpoints (go/no-go gates)
Each gate names the tests/verification that must be green before the next phase depends on it.

- **C-bench — Feature evidence** ✅ *(done 2026-05-31)*: GraphSAGE A/B on the GB10
  (`research/08`); `pytest tests/test_benchmark.py` green. **Verdict:** lean set wins; keep coords
  as PE. *Gate passed → §C feature design locked.*
- **C0 — Real labels reproduced** (P14 Ph0–3): `test_clean/spatial/temporal/labels` green; CLI
  reproduces 313 rows / 173 baselined / 109↓ 64↑. *Gate: real signed labels exist + leak
  invariants hold.*
- **C1 — Openings + confounders** (P14 Ph4–6): `test_openings/confounders/counterfactual` green;
  opening-row + confounder-clean counts reported honestly.
- **C2 — Dataset frozen** (P14 Ph7 + parity): `test_package` (no `centreline_id` leak) +
  `@pytest.mark.spark` cuDF↔pandas parity; manifest caveats present. *Gate: P13 may consume.*
- **C3 — Scenario generator** (P13 B): `test_scenario_gen` (closures reroute, openings attract,
  flow conserved, deterministic) + cross-backend GPU/CPU parity on the GB10. *Gate: Stage-1 data.*
- **C4 — Stage-1 pre-train**: sim-pair residual MAE converges on the GB10 (bf16).
- **C5 — Stage-2 fine-tune**: warm-start on P14 real residuals; held-out split (grouped +
  temporal) clean.
- **C6 — ACTIVATION GATE** (the ship decision, P13 D): `err_gnn < err_sim − ε` on held-out **real**
  interventions (closures + openings reported separately) + the rank/top-K metric; min-n guard.
  `test_gate` enforces "must beat the sim." *Else keep the sim — a correct outcome.*
- **C7 — Integration**: P10 pre-screen wired (sim verifies top-K); optional Verifiers env +
  forward-logging cron live.

## 4. Dependency graph
```
P03 (ODME) ─┐
P04 (sim) ──┼─► P14 ─(C0→C1→C2)─► P13 scenario-gen ─(C3)─► Stage-1 ─(C4)─► Stage-2 ─(C5)─►
models/gnn ─┘                                                                   ACTIVATION GATE (C6)
                                                                                      │
research/08 (C-bench ✅, feature design) ─────────────────────────────────────────────┼─► P10 pre-screen (C7)
P14 Ph0 cron + deeper sources (utility-cut, BDIT RoDARS) ── run in parallel, deepen labels over time
```
Critical path to a shippable GNN: **P14 Ph0–3 → C2 → P13 scenario-gen → Stage-1 → Stage-2 → C6.**
Scenario-gen (Stage-1 data) can run in parallel with P14, since it needs only the sim.

## 5. Verification & testing strategy (two tiers — matches `ROADMAP.md`)
1. **Local CPU `pytest`** per-phase fixtures must pass (torch-free): the P14 phase tests, the
   benchmark harness tests, the closure-join/gate logic on synthetic fixtures.
2. **GB10 / Spark** gates the GPU/training paths (`scripts/spark/*.sh`): GraphSAGE training,
   scenario-gen GPU parity, cuDF↔pandas dataset parity, the benchmark A/B (`benchmark_gnn.sh`).
   **All model runs execute here, never locally.**
- **Cross-cutting regression gates** (dedicated tests): site = `centreline_id` **not** `count_id`;
  signed labels; **no fabricated rows** for missing data; **no `centreline_id` leakage** across
  splits; determinism (same seed+data → byte-identical). A frozen baseline `training_metrics.json`
  is the regression reference; CI fails on drift beyond tolerance.

## 6. Effort + suggested order (rough)
P14 Ph0–3 (~2.5d) → **C0**; scenario-gen (P13 T13.1–2, ~2d) in parallel; P14 Ph4–7 (~3.5d) →
**C2**; intervention model + 2-stage train (P13 T13.3–4, ~2d) → **C4/C5**; gate (T13.5, 0.5d) →
**C6**; P10 integ (0.5d) + optional Verifiers/cron. Benchmark/regression (T13.7–8) lands early and
runs throughout. Build P14 Ph0–3 first to unlock real labels.

## 7. Risk register (consolidated)
- **Thin real yield** (esp. openings) → Stage-1 sim pre-train carries the physics; real labeled
  "calibration-ready"; the gate keeps the sim if the GNN doesn't beat it (a correct outcome).
- **Confounders inseparable** → matched-control + adjustment; drop unidentifiable cases; report
  survivors.
- **cuDF / env skew** → pandas CPU path is source of truth, cuDF is an accelerator with a parity
  gate. **GPU scenario-gen diverges from CPU** → cross-backend determinism test gates it.
- **GNN doesn't beat the sim** → ship nothing, keep the sim; the verified comparison is the value.
- **XGBoost residual fallback** if PyG training is unstable on the GB10 (gate is model-agnostic).

## 8. References
Specs `13`, `14`; research `07` (datasets), `08` (feature benchmark), `01` (Toronto open data);
`06-spark-setup-verified.md`; `07-training-feedback-loop.md` (the origin plan); `10-optimizer.md`
(the consumer); `models/gnn/README_GNN.md`; master `ROADMAP.md` + `BUILD_STATUS.md`.
