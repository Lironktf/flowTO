# P10 — Optimizer: heuristic + cuOpt constrained proposals, constraint checker

| | |
|---|---|
| **Priority** | High |
| **Depends on** | P04, P06 |
| **Owner hint** | AI owner |
| **Status** | not started |

## Goal
An **auto-optimizer** that proposes intervention plans which improve a metric (reduce delay/egress time) under
**bylaw + budget constraints** — a reliable heuristic/cuOpt baseline that always returns *something better*, with
RL as a stretch layer (S4). Each candidate is **scored by actually running the sim** (the sim is the judge).

**Why / rubric tie-in:** Prime Intellect / Verifiers bounty (sim-as-verifier) + Innovation. "One constrained
problem, returns a plan that improves the metric, one-click apply."

## Current state
- None. The sim (P04) + blast-radius (P05) provide fast candidate scoring; `compare_simulations` gives the metric.

## Target state
- `optimizer/` module + `POST /optimize`: given a problem (objective + constraints + action space + budget), generate candidate plans (heuristic + cuOpt where it fits), **score each by simulating** (blast-radius for speed), enforce constraints via a checker (illegal/unsafe actions masked), return ranked plans the planner one-click applies.

### In scope
Action space, objective + constraints + budget, heuristic candidate generation, cuOpt for constrained sub-problems, constraint checker / action masks, sim-based scoring loop, ranking, API.
### Out of scope
RL proposal layer (stretch S4) — exposed only as a ranking layer after it's validated. GNN surrogate (stretch S3).

## Design / implementation plan
(cuOpt details in **`research/05-local-ai-stack.md`**.)
1. **Problem spec** (`optimizer/problem.py`) — objective = −(total person-travel-time) − penalties(bylaw violations) − cost(budget); action space = reroutes, lane allocations, signal-timing offsets, transit-frequency bumps, contraflow; constraints = bylaws + budget + safety.
2. **Constraint checker / action masks** (`optimizer/constraints.py`) — hard-reject illegal/unsafe actions (no through-truck on residential, min sidewalk width, transit-priority corridors) **before** they enter optimization or the planner view. Shared with the copilot's checker (P09). (Bylaw→mask extraction via txt2kg is stretch S5.)
3. **Heuristic baseline** (`optimizer/heuristic.py`) — greedy / bandit / CMA-ES over the action space using graph pressure + betweenness to pick candidate edges; **always returns a valid improving-or-neutral plan**.
4. **cuOpt** (`optimizer/cuopt_client.py`) — self-hosted cuOpt container; map *constrained sub-problems* (OD-bundle reassignment as VRP+capacity, work-window scheduling as VRP-TW/MILP, constrained detours) to `POST /cuopt/request`. **Caveat documented:** city traffic ≠ pure VRP — cuOpt does the constrained assignment/scheduling piece, the sim does realism.
5. **Sim-based scoring (the verifier)** (`optimizer/score.py`) — each candidate → `simulate_scenario(recompute="blast")` → metric from `compare_simulations`; rank. This is the "Verifiers" story: every plan is *verified by running it*.
6. **Search loop** (`optimizer/search.py`) — generate → mask → score → keep top-N; budget-bounded iterations; deterministic (seeded).
7. **API** (extends P06) — `POST /optimize` (problem → ranked plans + metrics + constraint notes); plans are previewable/one-click-applyable via existing scenario endpoints.

## Data / models / sources
`research/05` (cuOpt availability/API/fit + caveat). Reuses P04 sim + P05 blast-radius for scoring, P09 constraint checker. Budget/cost + bylaw constraints curated with the copilot corpus.

## Files to create / modify
**Create:** `src/torontosim/optimizer/{__init__,problem,constraints,heuristic,cuopt_client,score,search}.py`; `api/routes/optimize.py`; `tests/test_optimizer_heuristic.py`, `tests/test_constraint_checker.py`; `scripts/spark/smoke_cuopt.py`.
**Modify:** `api/schemas.py` (OptimizeRequest/Plan), share `optimizer/constraints.py` with P09.

## Test-driven design
- `test_constraint_checker.py` (first): an illegal action (through-truck on residential) is rejected/masked; a legal one passes; budget-exceeding plan is penalized.
- `test_optimizer_heuristic.py`: on a small network with an obvious bottleneck, the heuristic returns a plan whose **simulated** metric ≥ do-nothing (never worse); deterministic across runs.
- Scoring: a known-good intervention scores better than a known-bad one via the sim.
- **Spark-only** (`@pytest.mark.spark`): `smoke_cuopt.py` solves a tiny VRP locally; the cuOpt sub-problem path returns a feasible solution.

## Verification
**Local (CPU):** `POST /optimize` with a constrained closure problem → ranked plans, each with a simulated metric + constraint notes; heuristic alone produces an improving plan (no cuOpt needed).
**On Spark:** cuOpt container up; `smoke_cuopt.py` green; the cuOpt sub-problem path runs on-device; time the search loop using blast-radius scoring (feeds P11).

## Tasks
- [ ] T10.1 Problem spec + objective/constraints/budget model — *0.5d*
- [ ] T10.2 Constraint checker / action masks (shared w/ copilot) — *0.5d*
- [ ] T10.3 Heuristic candidate generator (greedy/bandit) — *1d*
- [ ] T10.4 Sim-based scoring via blast-radius (the verifier) + ranking — *1d*
- [ ] T10.5 cuOpt client + sub-problem mapping + `smoke_cuopt.py` — *1d*
- [ ] T10.6 `POST /optimize` + tests — *0.5d*

## Risks / fallbacks
- **cuOpt install/license/container issue on Spark** → heuristic baseline alone always returns improving plans; cuOpt is clearly separated as a validated add-on (don't put it on the critical path).
- **Optimizer doesn't converge in time** → greedy baseline returns *something* better immediately; cache a canned optimizer result for the demo so the apply step never waits.
- **Overclaiming cuOpt** → frame it as solving the constrained sub-problem, not "solving traffic."
