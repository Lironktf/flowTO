# P03 — Demand & OD: ML node-demand + gravity + IPF calibration + TTS/Census seed

| | |
|---|---|
| **Priority** | Core |
| **Depends on** | P01, P02 |
| **Owner hint** | AI/data owner |
| **Status** | not started |

## Goal
Keep Liron's **weather-aware ML node-demand model** (a real differentiator), but upgrade OD construction to be
**survey-seeded and IPF-calibrated to observed TMC counts**, with confidence-aware outputs. Demand becomes both
*believable* (calibrated to reality) and *deterministic* (reproducible for validation against past events).

**Why / rubric tie-in:** Insight quality + Technical depth. The original vision was "train a model, validate on
past events" — this delivers exactly that, now grounded by survey + counts, not just synthetic data.

## Current state (Liron's prototype)
- `model/features.py` (11-feature schema, FEATURE_ORDER — incl. weather, downtown distance, road class), `model/train_demand_model.py` (HistGradientBoostingRegressor / XGBoost, synthetic 40k rows or real TMC), `model/predict_node_demand.py` (per-node demand + `HeuristicDemandModel` fallback), `model/generate_od_matrix.py` (gravity from node demand with time-of-day + road-class biasing, top-N filtering), `model/ingest_real_data.py` (TMC+weather → training CSV, KD-tree snapping). Trained `models/demand_model.pkl` present. Auto-calibration to `target_pressure=0.55` lives in the simulator. **No survey seed, no IPF-to-counts.**

## Target state
- **Two-stage OD calibration** added downstream of the gravity step:
  - **Stage 1 — IPF/Furness** to production/attraction marginals (from node demand + employment).
  - **Stage 2 — ODME** (under-determined) so assigned link/turn volumes match observed **TMC counts**; pragmatic version = IPF-on-turn-flows treating counts as marginals.
- **Survey seed** (`tts_seed.py`): use **TTS2016R** (open, CC-BY) TAZ OD + skim as a prior, mapped to graph zones; fall back to Census-pop×Employment gravity if unavailable.
- **Validation harness:** recreate a past scenario, run, compare predicted vs observed → an accuracy number (the demo's credibility stat).
- Keep the ML node-demand model + heuristic fallback intact; keep `generate_od_matrix` interface (`[{origin,destination,trips}]`) stable.

### In scope
IPF (`ipfn`), ODME (pragmatic), TTS2016R/Census seed, time-of-day factoring, validation-against-past harness, confidence propagation.
### Out of scope
Mode choice / transit demand coupling (stretch S1). Full SPSA ODME (pragmatic IPF-on-counts is the MVP; SPSA is a stretch task). The assignment itself (P04).

## Design / implementation plan
1. **Zone system** — pick **neighbourhoods (158)** or **wards (25)** as TAZ proxies (no Toronto TAZ layer); map graph nodes → zones; map TTS2016R GTA06 zones → these proxies via spatial join.
2. **Seed** (`model/tts_seed.py`) — load TTS2016R OD + skim (or Census-pop productions × Employment-Survey attractions gravity); produce a prior OD at zone level; explode to node level using Liron's node-demand as within-zone weights.
3. **IPF Stage 1** (`model/ipf.py`, via `ipfn`) — balance the gravity OD to production/attraction marginals.
4. **ODME Stage 2** (`model/odme.py`) — pragmatic: assign seed OD to paths once (uses P04 backend), treat observed TMC turn/link counts as marginals, IPF the path/turn flows; expose `method={ipf_counts, spsa}` (SPSA = stretch). Document under-determination.
5. **Time-of-day** (`model/timeofday.py`) — factor daily OD → AM/PM peak (derive from TTS time bands; fall back to ~9% AM / ~10% PM peak-hour, AM 65/35 inbound).
6. **Validation harness** (`model/validate_past.py`) — given a past date + known event/closure, build the scenario, simulate, compare predicted congestion/travel-time vs observed (TMC, or news/known delays); emit MAE/% error. Deterministic.
7. **Confidence propagation** — OD pairs carry a confidence derived from seed source + calibration coverage.

## Data / models / sources
**`research/03-demand-tts-ipf.md`** (TTS gating + TTS2016R escape hatch, Census `98-10-0459-01`, Employment Survey, `ipfn`, AequilibraE `Ipf`/gravity, ODME refs, time-of-day factors). TMC counts from P01 parquet. Liron's `demand_model.pkl` + FEATURE_ORDER.

## Files to create / modify
**Create:** `src/torontosim/model/{tts_seed,ipf,odme,timeofday,validate_past}.py`; `tests/test_ipf.py`, `tests/test_odme.py`, `tests/test_validate_past.py`.
**Modify:** `model/generate_od_matrix.py` (insert IPF/ODME stages behind `calibration={none,ipf,ipf_counts}` flag; default `ipf_counts`), `model/ingest_real_data.py` (read parquet from P01).

## Test-driven design
- `test_ipf.py` (first): a 3×3 seed + known row/col marginals → `ipf` output matches marginals within tolerance; deterministic across runs.
- `test_odme.py`: synthetic network where the true OD is known → assign → recover counts → ODME-from-counts moves the seed toward truth (error decreases); assert it doesn't diverge.
- `test_validate_past.py`: a fixture "past closure" → harness returns a finite error metric + identical result on re-run (determinism).
- **Regression:** Liron's `test_simulation.py` still produces a plausible OD under `calibration=none`.

## Verification
**Local:** `python -m torontosim.model.generate_od_matrix --calibration ipf_counts --time "Fri 17:00"` → OD whose assigned counts track TMC; `validate_past --date 2024-… --event gardiner_closure` prints an accuracy number.
**On Spark:** retrain the demand model on the full real dataset (XGBoost `device=cuda`) over SSH (`scripts/train_on_gx10.sh`); pull the `.pkl` + metrics back; confirm IPF/ODME run on the larger graph.

## Tasks
- [ ] T03.1 Zone proxy + node↔zone mapping + TTS2016R spatial join — *1d*
- [ ] T03.2 `tts_seed.py` (TTS2016R or Census×Employment gravity prior) — *1d*
- [ ] T03.3 `ipf.py` Stage-1 marginal balancing (`ipfn`) — *0.5d*
- [ ] T03.4 `odme.py` Stage-2 IPF-on-counts (SPSA = stretch task) — *1d*
- [ ] T03.5 `timeofday.py` AM/PM factoring — *0.5d*
- [ ] T03.6 `validate_past.py` accuracy harness — *1d*
- [ ] T03.7 Wire calibration into `generate_od_matrix` + tests — *0.5d*

## Risks / fallbacks
- **TTS2016R mapping to graph zones imperfect** → Census-pop×Employment gravity prior (fully open) is the fallback; the ML node-demand still drives within-zone weights.
- **ODME from sparse counts under-constrained** → regularize hard toward the seed; report coverage + confidence honestly; don't overfit to a few intersections.
- **Validation ground-truth thin** → pick one well-documented past closure with known impact; frame the number as "directionally accurate," not exact.
