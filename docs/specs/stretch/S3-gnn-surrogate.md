# S3 — GNN / surrogate emulator (Modulus/PhysicsNeMo) [STRETCH]

| | |
|---|---|
| **Priority** | Stretch |
| **Depends on** | P04 (sim as data generator + oracle) |
| **Status** | optional |

## Goal
Train a **learned surrogate** that emulates the simulator — maps (network state + demand) → link flows/pressure in
**milliseconds** — so the optimizer (P10) / RL (S4) can score *millions* of candidate plans without running full
equilibrium each time. Optionally regularize with a Modulus/PhysicsNeMo flow-conservation term. **The analytic
simulator stays the source of truth;** the GNN only accelerates search.

**Why:** Performance + Innovation + a genuine "trained model with GPU" story. Activate **only if** validation shows
it beats the deterministic baseline.

## Current state
- None. P04 produces (state → flows) pairs that are perfect training data.

## Target state
- A spatiotemporal GNN (edge-pressure prior / residual after the deterministic baseline) trained on simulator outputs (+ optional real TMC), validated against held-out sim runs; used as a fast pre-screen in the optimizer, with the true sim verifying the top candidates.

## Design / implementation plan
1. **Dataset** (`surrogate/dataset.py`) — sample interventions, run P04, store (graph features + demand + intervention) → (link pressure). 
2. **Model** (`surrogate/gnn.py`) — start with **cuML/XGBoost residual** (faster, safer first learned layer per research) predicting residual edge-flow after the deterministic baseline; escalate to a GNN (Graph WaveNet / DCRNN style) if it helps.
3. **Physics regularizer (optional)** (`surrogate/physics.py`) — Modulus/PhysicsNeMo flow-conservation penalty.
4. **Integration** — optimizer (P10) uses the surrogate to rank, sim verifies top-K.
5. **Activation gate** — only ship if surrogate val error < deterministic baseline error on held-out runs.

## Files to create / modify
**Create:** `src/torontosim/surrogate/{dataset,gnn,physics,infer}.py`; `scripts/train_surrogate_gx10.sh`; `tests/test_surrogate.py`. **Modify:** P10 `optimizer/score.py` (surrogate pre-screen + sim verify).

## Test-driven design
- Surrogate predicts held-out sim flows within tolerance; optimizer-with-surrogate finds the same top plan as optimizer-with-sim on a small case (sim still verifies).

## Verification
**On Spark:** train (XGBoost/GNN `device=cuda`), measure surrogate latency vs full sim; confirm optimizer speedup.

## Risks / fallbacks
- **Insufficient/weak training labels** → use synthetic + simulator-generated data; present as "calibration-ready stretch," don't overclaim (per spec's data-honesty note).
- **GNN underperforms** → cuML/XGBoost residual is the safer first learned layer; if neither beats baseline, **don't ship it** (gate).
