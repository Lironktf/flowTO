# S1 — Full multimodal mode-choice (car ↔ transit coupling) [STRETCH]

| | |
|---|---|
| **Priority** | Stretch (only after core demo is stable) |
| **Depends on** | P03 (demand), P04 (sim), P08 (transit overlay) |
| **Status** | optional |

## Goal
Upgrade transit from a **visual overlay** (P08) to a **modeled alternative**: each OD pair splits across car vs
transit via a logit mode-choice, so interventions that make driving worse (or transit better) cause **riders to
shift modes** — and shutting a transit line floods nearby roads/other lines. This is the original vision's hard
part and the most behaviorally realistic upgrade.

**Why:** Insight quality — the emergent "close Line 1 → 504 overloads → roads absorb the rest" behavior the
explainer promises. Big credibility jump; biggest effort/risk → strictly post-core.

## Current state
- P08 renders transit but riders are decoupled. P03 produces car OD only; mode shares are static (calibrated to TTS but not responsive).

## Target state
- A transit network (from GTFS) with in-vehicle + wait + transfer times (RAPTOR-style pathfinding); a logit mode-choice splitting each OD across {car, transit}; a feedback loop so congested car times ↑ transit share and crowded transit ↑ car share, settling to a multimodal equilibrium. Interventions on either network propagate across both.

## Design / implementation plan
1. **Transit graph + RAPTOR** (`transit/network.py`, `transit/raptor.py`) — build a time-dependent transit graph from GTFS; RAPTOR for fastest transit path (in-vehicle + wait + transfer penalty) → transit skim.
2. **Mode choice** (`model/mode_choice.py`) — multinomial logit `P(m|i,j)=exp(V_m)/Σexp(V_m')`, `V_m=β_t·time_m+β_c·cost_m+ASC_m`; `time_car` from P04 skim, `time_transit` from RAPTOR; ASCs calibrated to Toronto shares (~70/24/6). Splits OD → car OD + transit OD.
3. **Crowding** (`transit/crowding.py`) — rider load vs vehicle capacity → discomfort penalty feeding back into mode choice.
4. **Multimodal feedback** — outer loop: car assignment (P04) + transit loading → updated skims → re-run mode choice → repeat to convergence. Deterministic.
5. **Interventions** — extend `mutations.py` to transit (close line, change headway); both networks respond.

## Files to create / modify
**Create:** `src/torontosim/transit/{network,raptor,crowding}.py`, `src/torontosim/model/mode_choice.py`; `tests/test_mode_choice.py`, `tests/test_raptor.py`.
**Modify:** P03 `generate_od_matrix` (emit per-mode OD), P04 outer loop (multimodal feedback), P08 (transit headway interventions), `mutations.py` (transit ops).

## Test-driven design
- `test_raptor.py`: fastest transit path on a tiny GTFS fixture matches a hand-computed answer; transfer penalty applied.
- `test_mode_choice.py`: raising car time shifts share toward transit (monotonic); shares sum to 1; deterministic.
- Feedback: closing a transit line increases car OD on parallel corridors (integration).

## Verification
**Local:** mode shares respond to a car closure + a transit headway change; multimodal loop converges.
**On Spark:** full citywide multimodal run; confirm convergence + perf.

## Risks / fallbacks
- **Too big for the window** → this is *why* it's stretch; P08 visual overlay remains the demo path.
- **Calibration hard** → anchor ASCs to TTS mode shares; accept approximate.
- **Convergence instability** → MSA damping + fixed iteration cap.
