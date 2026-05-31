# TorontoSim — Engineering Roadmap

> **Codename:** TorontoSim (working name; public name flowTO/TorontoSim TBD)
> **Repo:** `Lironktf/flowTO` · **Planning branch:** `bentobranch`
> **Target:** NVIDIA Spark Hack — local-first 3D Toronto traffic digital twin on a DGX Spark (GB10).
> **Demo hero:** FIFA World Cup 2026 surge at BMO Field, over a general closure-planning engine.
> **Status:** planning. Specs below are built to be executed by `/goal` and split across teammates.

---

## 0. How to read this roadmap

Each **Phase** is a ticket; each phase spec (`docs/specs/NN-*.md`) contains **Tasks** (subtickets). Every
spec follows the same template: Goal → Current state → Target → Design → Data/sources → **Files touched**
(for delegation) → **Test-driven design** → **Verification (local + on-Spark)** → Tasks → Risks.

**Three sources are being reconciled** — read this before anything else:

| Source | What it is | Role |
|---|---|---|
| **Liron's prototype** (`liron/model`) | Working CPU pipeline: OSMnx graph, ML demand, gravity OD, k-path assignment, congestion, scenarios, tests, real data | **The demo-safe baseline.** We build on it, don't discard it. |
| **TorontoSim spec** (`TorontoSim_Final_Technical_Spec.pdf`) | Rubric-optimized target: Centreline graph, BPR equilibrium, RAPIDS, blast-radius, copilot, optimizer | **The target.** Each phase moves one piece toward it. |
| **Research briefs** (`docs/specs/research/`) | Verified datasets, library versions, APIs, compat risks | **The ground truth** for implementation detail + links. |

### The guiding strategy
1. **Baseline always runs.** Liron's CPU pipeline stays green at every step. New engines land *behind a flag* (`ENGINE=baseline|equilibrium`, `BACKEND=cpu|gpu`).
2. **CPU-first, GPU-validated-on-Spark.** We build and unit-test here (no NVIDIA GPU); GPU paths (RAPIDS/cuGraph, Nemotron, cuOpt) are gated behind a Spark smoke test reached over SSH (`asus@gx10-4f5f`, Tailscale `100.124.76.16`).
3. **Correctness is provable.** The principled assignment is cross-checked against **AequilibraE** on standard test networks (oracle tests), not self-asserted.
4. **Determinism is a feature.** Same scenario JSON → identical result. Fixed iteration caps, id-tie-breaks, float64, no Monte-Carlo.

---

## 1. The reconciliation decisions (locked)

| Axis | Prototype (today) | Spec (target) | **Decision** |
|---|---|---|---|
| **Road graph** | OSMnx, 7 km downtown, 6834 nodes / 18190 edges | Centreline (official) | **Keep OSMnx as baseline; add Centreline loader as a fidelity upgrade** (P02). Centreline IDs also link TMC + restrictions. |
| **Demand** | ML node-demand (HistGBR/XGB) on time+weather+road context → gravity OD | gravity + IPF from counts | **Keep the ML model** (real differentiator: weather-aware, validated on past) **and add IPF calibration to TMC marginals + TTS/Census seed/validation** (P03). |
| **Assignment** | NetworkX all-or-nothing, top-k=3, 4 fixed iters, lookup-table congestion | deterministic BPR equilibrium, RAPIDS cuGraph | **Add BPR + Frank-Wolfe equilibrium engine with AequilibraE oracle + cuGraph SSSP path; keep k-path loop as CPU fallback** (P04). |
| **Congestion** | piecewise lookup multiplier | BPR `t=t0(1+α(v/c)^β)` | **Replace with BPR** (α=0.15, β=4), lookup kept as `congestion_model=legacy` flag (P04). |
| **Blast-radius recompute** | — | adaptive subgraph recompute | **Net-new — the headline performance feature** (P05). |
| **Transit** | — | (absent) | **Net-new: visual + schedule overlay** (TTC/GO/UP from GTFS), no rider coupling yet (P08). Full mode-choice = stretch. |
| **Demand source access** | synthetic + real TMC | — | TTS interactive system is gated; **use TTS2016R (open, CC-BY) + Census + TMC** (see research). |

---

## 2. Phase list (tickets)

**Core path to the demo** (P00 → P12). **Stretch** layers only after the core demo is stable.

| # | Phase | Priority | Depends on | Spec |
|---|---|---|---|---|
| **P00** | Repo restructure, monorepo, dev env, CI, Spark SSH test harness | Core | — | `00-repo-and-environment.md` |
| **P01** | Data pipeline — CKAN/GTFS/weather fetch → versioned Parquet feature store | Core | P00 | `01-data-pipeline.md` |
| **P02** | Road graph — OSMnx baseline hardening + Centreline loader + capacity/confidence | Core | P00, P01 | `02-graph.md` |
| **P03** | Demand & OD — ML node-demand + gravity + **IPF calibration** + TTS/Census seed | Core | P01, P02 | `03-demand-and-od.md` |
| **P04** | Simulation engine — **BPR + Frank-Wolfe equilibrium**, AequilibraE oracle, cuGraph path | Core | P02, P03 | `04-simulation-engine.md` |
| **P05** | **Blast-radius** adaptive subgraph recompute | Core | P04 | `05-blast-radius.md` |
| **P06** | Backend API — FastAPI, scenario CRUD (REST), binary tick frames (WebSocket) | Core | P04, P05 | `06-backend-api.md` |
| **P07** | Frontend — deck.gl + MapLibre instrument; **visual tokens dropped in by Claude design** | Core | P06 | `07-frontend.md` |
| **P08** | Transit overlay — GTFS ingest, server-side trajectories, TripsLayer | Core | P01, P07 | `08-transit-overlay.md` |
| **P09** | Copilot — Nemotron (Ollama) NL→validated tool calls, preview-before-apply, local RAG | High | P06 | `09-copilot.md` |
| **P10** | Optimizer — heuristic + cuOpt constrained proposals, constraint checker | High | P04, P06 | `10-optimizer.md` |
| **P11** | Profiling & performance — Nsight on Spark, latency counters, perf panel | High | P04, P05 | `11-profiling-and-perf.md` |
| **P12** | FIFA WC demo — match-day surge scenario, before/after, demo script, fallbacks | Core | all core | `12-demo-fifa-wc.md` |

### Stretch (optional `.md`, tackled only if ahead) — `docs/specs/stretch/`
| # | Phase | Notes |
|---|---|---|
| S1 | Full multimodal mode-choice (car↔transit coupling) | the original vision's hard part |
| S2 | Pedestrian + bike layers | 4th/5th network layers |
| S3 | GNN / surrogate (Modulus/PhysicsNeMo) | fast emulator for the optimizer |
| S4 | RL proposal layer (Verifiers / constrained PPO) | ranks interventions; sim is the judge |
| S5 | txt2kg bylaw knowledge graph → optimizer action masks | creativity-bounty hook |
| S6 | VSS traffic-camera validation layer | optional camera markers |
| S7 | Feature-engineering audit for the GNN | Drop spatial proxies a GNN learns for free (`distance_to_downtown`, `road_degree`, `near_highway`) + add richer **edge** features (capacity, lanes, speed limit, one-way, current load) and cheap node signals (transit-stop adjacency, venue/POI flag, continuous temp/precip, holiday flag). Touches `model/features.py` (shared train+predict contract; retrain required). Do alongside S3. See `docs/gnn-explainer.md` §8b. |

> **Feedback-loop track (S3 + S4 realization):** the closure/opening GNN that learns from real
> closures and ships only if it beats the sim — sequenced with go/no-go checkpoints in
> **`ROADMAP-feedback-loop.md`** (phases P13 training + P14 dataset; specs `13`/`14`, research
> `07`/`08`).

---

## 3. Dependency graph

```
P00 ─┬─ P01 ─┬─ P02 ─┬─ P03 ─┬─ P04 ─┬─ P05 ─┬─ P06 ─┬─ P07 ─── P08
     │       │       │       │       │       │       │
     │       └────── P08 (GTFS ingest part)  │       └── P09 (copilot)
     │                                       └────────── P10 (optimizer)
     └─ P11 (profiling harness, lands early, used throughout)
P12 (demo) consumes everything.
```
Critical path for a working demo: **P00 → P01 → P02 → P03 → P04 → P06 → P07 → P12**.
P05/P08/P09/P10 each make the demo *better* but the demo survives without any single one.

---

## 4. Target repository layout (after P00)

```
flowTO/
├── docs/                      # planning docs + specs (this dir)
│   └── specs/
│       ├── ROADMAP.md
│       ├── NN-*.md            # one per phase
│       ├── research/          # the 6 research briefs (verbatim, with links)
│       └── stretch/
├── src/torontosim/            # python package (was Liron's src/)
│   ├── graph/                 # build_graph, config, mutations, routing  [Liron] + centreline_loader [new]
│   ├── model/                 # demand ML, od gen [Liron] + ipf, tts_seed [new]
│   ├── simulation/            # assign_paths, congestion, simulate [Liron] + equilibrium, bpr, oracle [new]
│   ├── blastradius/           # adaptive subgraph recompute [new]
│   ├── transit/               # gtfs ingest, trajectories [new]
│   ├── api/                   # FastAPI app, ws, schemas [new]
│   ├── copilot/               # nemotron tool-calling, rag [new]
│   ├── optimizer/             # heuristic, cuopt, constraints [new]
│   └── datapipeline/          # CKAN/GTFS/weather fetch + bake [new, absorbs scripts/fetch_data.sh]
├── frontend/                  # React+Vite+TS deck.gl app [new]; design tokens drop-in
├── data/                      # gitignored feature store (raw + parquet + graph + models)
├── models/                    # trained .pkl / engines (gitignored except small)
├── scripts/                   # spark SSH helpers, smoke tests, run helpers
├── tests/                     # pytest [Liron tests migrate here]
├── infra/                     # env, requirements, spark setup notes
└── pyproject.toml             # package + tooling config
```

**Naming:** the Python package is `torontosim`. Liron's `src/{graph,model,simulation}` move under `src/torontosim/`
with import shims so nothing breaks mid-migration (see P00).

---

## 5. Conventions every spec assumes

- **Language/stack:** Python 3.12 backend; React + Vite + TypeScript frontend; FastAPI + WebSockets glue.
- **Flags over forks:** new engines are selected by config/env, never by deleting the baseline.
- **TDD:** write the failing test first; the AequilibraE/TNTP oracle is the correctness anchor for the sim.
- **Determinism:** fixed caps, `edge_id`/`node_id` tie-breaks, float64, seeded everything, no wall-clock stops.
- **Verification has two tiers:** (1) local `pytest` (CPU) must pass; (2) GPU/LLM features carry a
  `scripts/spark/verify_<feature>.sh` run over SSH on `gx10-4f5f` that gates the GPU path.
- **Attribution:** ship `Contains information licensed under the Open Government Licence – Toronto` for City data;
  OGL-Ontario for Metrolinx.
- **The sm_121 risk:** RAPIDS on the GB10 is **unverified**. Every GPU phase keeps a CPU fallback and a smoke
  test (`scripts/spark/smoke_rapids.py`) as its first task. If the smoke test fails, the CPU path is the demo path.

---

## 6. Research briefs (sources, verbatim)

Stored under `docs/specs/research/` — each is link-dense and feeds the matching phase:
- `research/01-toronto-datasets.md` → P01, P02
- `research/02-transit-gtfs-deckgl.md` → P08, P07
- `research/03-demand-tts-ipf.md` → P03
- `research/04-sim-engine-rapids.md` → P04, P05
- `research/05-local-ai-stack.md` → P09, P10
- `research/06-frontend-deckgl-ux.md` → P07

> **Headline findings:** TTS interactive system is gated → use **TTS2016R (open)** + Census + TMC. Real
> dataset IDs differ from the spec's filenames (no `tmc_..2000-2029.csv`; it's per-decade
> `tmc_raw_data_2020_2029`; road restrictions is a *live* `secure.toronto.ca` feed; 3D massing goes to 2025).
> **cuDF/cuGraph ship aarch64+CUDA13 wheels, but RAPIDS on sm_121/GB10 is unconfirmed — must smoke-test.**
> Nemotron runs locally via Ollama (`nemotron-3-nano:30b` recommended). cuOpt is Apache-2.0, self-hostable.
> deck.gl v9.3 + MapLibre v5: interleaved `MapboxOverlay`, congestion on **road lines** (per-tick
> `updateTriggers`), tick data **never** touches React.
