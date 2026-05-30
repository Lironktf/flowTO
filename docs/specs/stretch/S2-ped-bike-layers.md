# S2 — Pedestrian + bike network layers [STRETCH]

| | |
|---|---|
| **Priority** | Stretch |
| **Depends on** | P02 (graph), P07 (frontend) |
| **Status** | optional |

## Goal
Add **pedestrian** and **bike** networks as 4th/5th toggleable layers — geometry + simple volumes — so the city
reads as fully multimodal and planners can test active-transport interventions (bike lanes, pedestrian corridors).

**Why:** Cultural/accessibility + completeness; supports the demo's "pedestrian corridor on Bremner" fix. Low-to-medium effort (geometry is easy; demand is the work).

## Current state
- Drive network only (P02). OSMnx already supports `network_type="walk"` / `"bike"`; City has a cycling network dataset.

## Target state
- Walk + bike graphs (OSMnx walk/bike or City cycling-network dataset); render as distinct layers; coarse pedestrian/bike volumes from TMC ped/bike counts + proximity heuristics; bike-lane / pedestrian-corridor interventions.

## Design / implementation plan
1. **Networks** (`graph/build.py` `--source` already supports modes) — build `walk` + `bike` graphs; City **Cycling Network** dataset for official bike infra; canonical schema parity.
2. **Volumes** (`model/active_demand.py`) — TMC `_peds`/`_bike` columns (P01) snapped to nodes → coarse volumes; simple gravity for spread.
3. **Interventions** — add `add_bike_lane`, `pedestrianize` to `mutations.py`.
4. **Frontend** (P07) — bike-route + ped-path `PathLayer`s (distinct non-congestion colors), toggles.

## Files to create / modify
**Create:** `src/torontosim/model/active_demand.py`; `tests/test_active_layers.py`. **Modify:** `graph/build.py`, `mutations.py`, P07 layers/toggles, P01 (ensure ped/bike counts baked).

## Test-driven design
- Walk/bike graphs build + pass `validate_graph`; ped/bike volumes attach; a `pedestrianize` op closes the segment to cars but keeps walk access.

## Verification
**Local:** toggle ped/bike layers; apply a bike-lane intervention. **On Spark:** citywide walk/bike build.

## Risks / fallbacks
- **Ped/bike demand thin** → render geometry + counts only; skip behavioral modeling.
- **Visual clutter** → zoom-gated, off by default.
