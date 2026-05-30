# S4 — RL proposal layer (Verifiers / constrained PPO) [STRETCH]

| | |
|---|---|
| **Priority** | Stretch |
| **Depends on** | P04, P05, P10 (heuristic/cuOpt baseline first) |
| **Status** | optional |

## Goal
Wrap the simulator as a **Verifiers environment** and train a **constrained RL agent** (MaskablePPO) that *proposes
and ranks* interventions — reward = −person-travel-time − bylaw/budget penalties, with **action masks** blocking
illegal/unsafe moves. RL only ranks/proposes **after** the heuristic+cuOpt baseline (P10) is validated; the sim is
the verifier.

**Why:** Prime Intellect / Verifiers bounty (the headline use) + Innovation. Strictly post-core, post-P10.

## Current state
- P10 provides the action space, constraint checker/masks, and sim-based scoring — exactly the RL substrate.

## Target state
- A Verifiers-compatible env (state = edge capacity/flow/pressure/road-class/one-way/closure/restriction + node signal/intersection class + time/budget/OD-confidence; action = reroute OD to one of k alts / shift construction window / add-remove blocker / signal offset; reward = −mean travel time, −95th pct, −total delay, −local-road infiltration, −budget, −bylaw violations). MaskablePPO ranks interventions vs randomized scenarios; the deterministic sim verifies the chosen plan.

## Design / implementation plan
1. **Env** (`rl/env.py`) — Verifiers/Gymnasium env wrapping P04 sim (or S3 surrogate for speed); state/action/reward per spec §12; **hard invalidation** for illegal actions, large penalty for unsafe/budget-breaking.
2. **Masks** (`rl/masks.py`) — reuse P10 constraint checker → action masks (MaskablePPO).
3. **Train** (`rl/train.py`) — constrained PPO/MaskablePPO over randomized scenarios; the sim/surrogate scores.
4. **Serve** (`rl/propose.py`) — given a problem, RL proposes ranked interventions → **sim verifies top-K** → planner one-click apply. Disable RL if it produces nonsense (gate).

## Files to create / modify
**Create:** `src/torontosim/rl/{env,masks,train,propose}.py`; `scripts/train_rl_gx10.sh`; `tests/test_rl_env.py`. **Modify:** P10 `optimizer` (RL as an optional ranking/proposal layer behind a flag).

## Test-driven design
- `test_rl_env.py`: env step is deterministic given seed; masked illegal actions never selected; reward decreases with worse plans; a trained policy beats random on a small case (sim-verified).

## Verification
**On Spark:** train (GPU); RL proposals, sim-verified, improve the metric vs the heuristic baseline on a held-out scenario. Name-drop Verifiers in the demo.

## Risks / fallbacks
- **RL produces nonsense / planner trust damaged** → **disable RL; show heuristic/cuOpt proposals only** (P10 is the always-on path). RL is a clearly-separated, validated upgrade.
- **Training too slow** → train on the S3 surrogate, verify with the true sim.
- **Verifiers env friction** → a Gymnasium env + the sim-as-verifier still tells the story.
