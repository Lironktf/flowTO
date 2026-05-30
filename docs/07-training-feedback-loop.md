# 07 — Lane-Closure Feedback Loop & Training Plan

Handoff doc. Where the closure-prediction model is at, the locked decisions, the verified
training stack, and the next steps in order. Companion to the visual explainer (`docs/explainer.html`
§08 "Closing the Loop" + dev spec §I).

## The idea (the whiteboard)

A model learns how traffic flows on open roads → predicts what happens when a lane closes →
compare to what **actually** happened → the **delta** feeds back and corrects the model →
after the training arc it predicts future flow accurately.

We already have ~80% of this: the sim engine **is** the model (BPR + Frank-Wolfe equilibrium,
verified vs SiouxFalls), closure scenarios exist (`close` / `set_capacity` mutations), and ODME
calibrates the **open-road** case against TMC counts. The **gap** = the closed feedback loop:
comparing *predicted closure impact* vs *observed closure impact* and training on the delta.

## Decisions (locked 2026-05-30)

1. **Ground truth = historical TMC join.** Road Restrictions is a *live* feed, not a historical
   archive, so "what actually happened when that lane closed" is built by joining historical TMC
   counts to known closure/construction windows → observed before/after link deltas. (Optional
   stretch: also log the live Road Restrictions feed forward on a cron for a real-time demo.)
2. **Real GNN training on the Spark** (not calibration-only). Two-stage:
   - **Stage 1 — pre-train on sim-generated data.** The existing Frank-Wolfe engine emits
     thousands of `(random closure → equilibrium flow)` pairs (cheap, unlimited labels; teaches
     the physics). Generation is GPU-parallelizable (Warp / cuGraph).
   - **Stage 2 — fine-tune on real closures** (the TMC join). Small but real; closes the
     sim-to-real gap. **This fine-tune step is the whiteboard's feedback loop.** Held-out real
     closures are the test set; "Δ below threshold" is the verifiable reward.
   - Model: spatio-temporal GNN over the Centreline graph (GraphSAGE/GAT) predicting the per-edge
     flow field (or the residual delta on top of the physics sim). XGBoost edge-regressor is the
     always-works fallback.

## Stack (verified on the Spark — see `06-spark-setup-verified.md`)

| Tool | Role | Status |
|---|---|---|
| PyTorch 2.12.0+cu130 (aarch64) | training backbone, bf16 on Blackwell | ✅ verified |
| PyTorch Geometric 2.7.0 (pure-Python) | GNN layers; no torch-scatter compile | ✅ verified |
| NVIDIA Warp 1.13 | GPU scenario generation | ✅ verified |
| RAPIDS cuDF / cuGraph (`gpu` extra) | feature eng on TMC parquet, graph ops | available |
| XGBoost 3.2.0 | fallback edge regressor | ✅ present |
| Prime Intellect Verifiers | wrap Δ-vs-observed as the reward (bounty) | to add |

NVIDIA-track fit: fully-local on DGX Spark/GB10/Arm; Nemotron copilot (existing) → Nemotron bounty;
Arm-native sim → Arm bounty; the Δ-verifier loop → Prime Intellect Verifiers bounty.

## Next steps (in order)

1. ✅ **Spark env check** — torch cu130 + pure-Python PyG GNN forward/backward on GB10. Done
   2026-05-30 (`06-spark-setup-verified.md`).
2. **Build the closure ground-truth set** — join historical TMC to known closure windows →
   observed before/after link deltas, keyed by `CENTRELINE_ID`. *Hard blocker; nothing trains
   without it.* First scope how many real closures are actually queryable.
3. **Scenario generator** — script the existing Frank-Wolfe sim to emit `(closure → flow)`
   training pairs at scale (Warp/cuGraph to parallelize).
4. **Train** — Stage 1 (sim pre-train) → Stage 2 (real fine-tune); log MAE/RMSE on held-out
   closures.
5. **Wrap as a Verifiers env** — reward = `rmse(predicted − observed) < ε`.

## Pointers

- Visual explainer: `docs/explainer.html` → §08 "Closing the Loop" and dev spec §I.
- Existing ODME (the open-road calibration to generalize): see `03-demand-and-od.md` (§B in the
  explainer dev reference).
- Blast-radius fast re-solve for the predict step: `05-blast-radius.md` (§D).
- Architecture context (3 AI layers, Verifiers optimizer): `02-architecture.md`.
