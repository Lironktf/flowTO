# 02 — Architecture

Three AI/compute layers, all on the Spark. Browser is a thin renderer.

```
                          ┌─────────────────────────── DGX Spark (GB10) ───────────────────────────┐
  Browser (deck.gl)       │                                                                          │
  ┌───────────────┐  WS   │  ┌──────────────┐   ┌─────────────────┐   ┌──────────────────────────┐  │
  │ 3D Toronto    │◀──────┼──│ Sim engine   │◀──│ Nemotron copilot │   │ RL auto-optimizer        │  │
  │ map + layers  │       │  │ (GPU, agents)│   │ (Ollama, local)  │   │ (Verifiers env, RL loop) │  │
  │ + heatmap     │──────▶┼─▶│              │──▶│ intent → config  │◀─▶│ proposes reroutes/sched  │  │
  │ + controls    │  REST │  └──────┬───────┘   └─────────────────┘   └────────────┬─────────────┘  │
  └───────────────┘       │         │  reads                                       │ scores via     │
                          │  ┌──────▼───────────────────────────────────────────────▼─────────────┐ │
                          │  │ Scenario state + baked network (roads graph, GTFS, ped net, demand) │ │
                          │  └────────────────────────────────────────────────────────────────────┘ │
                          └──────────────────────────────────────────────────────────────────────────┘
```

## Layer 1 — Simulation engine (the GPU flex)
**Key decision: city-wide = mesoscopic; zoom-in = microscopic.** Full microscopic sim of
*all* of Toronto at car-by-car resolution is overkill and fragile for a demo. Instead:
- **Mesoscopic city-wide:** model link-level flows/densities across the whole road + transit
  graph (queues, capacities, travel-time functions). Fast, GPU-parallel, covers all of Toronto.
- **Microscopic on demand:** when the planner zooms into a corridor (e.g. BMO Field), run
  car/pedestrian agents there for the pretty animated dots.
- **Transit** is **schedule-driven** from GTFS (deterministic vehicle trajectories) + a
  rider-loading model that responds to demand surges and service changes.

**Engine options (decide in `04`):**
- **A. NVIDIA Warp** (Python, GPU kernels) — custom mesoscopic flow model. Max "Spark flex" + Arm/CUDA story. More build risk.
- **B. SUMO** (mature traffic simulator, CPU) — fast to believable results, huge ecosystem (osmWebWizard, TraCI control, GTFS import). Less GPU flex.
- **Likely winner: B for the baseline sim + A (Warp) for a GPU-accelerated layer** (e.g. demand assignment / shortest-path flooding) so we have a real GPU story AND reliability.

## Layer 2 — Nemotron copilot (Nemotron bounty)
- Served **locally via Ollama** on the Spark.
- **Tool-calling / structured output:** NL → JSON scenario edits (close link X, set lane count,
  add construction zone, scale demand at zone Z by N%, set time-of-day/date).
- Also **explains results** ("commute time +12% on the 504; here's why") and **cites bylaws**
  (retrieval over a small bylaw/standards doc set).
- Fallback: any strong local model already cached in Ollama if Nemotron pull is slow.

## Layer 3 — RL auto-optimizer (Prime Intellect / Verifiers bounty)
- **Action space:** reroutes, lane allocations, signal timing offsets, transit frequency bumps, contraflow.
- **Reward:** −(total person-travel-time) − penalties for bylaw violations, − cost (budget/resource cap).
- **Env:** wrap the sim as a **Verifiers** environment so each candidate plan is *verified/scored*
  by actually running the sim. Start with a strong baseline (greedy/CMA-ES/bandit) and layer RL on top.
- Output: ranked plans the planner can one-click apply and watch.

## Frontend
- **deck.gl + MapLibre** (Node 24 present). Layers: extruded building outlines (3D Massing/OSM),
  `TripsLayer` (animated vehicles), `PathLayer` (routes w/ directionality color), `HeatmapLayer`/
  `HexagonLayer` (congestion + crowd density), toggle UI, time-of-day/date scrubber.
- Talks to backend via **WebSocket** (agent position stream) + **REST** (scenario CRUD, optimizer runs).
- Served from the Spark; team views it over Tailscale or an SSH tunnel.

## Backend glue
- **FastAPI** (Python) orchestrates sim ⇆ LLM ⇆ optimizer ⇆ frontend. Single process to start.
- Scenario state in memory + JSON snapshots on disk (no DB needed for the hackathon).

## Proposed tech stack
- Sim: SUMO + TraCI, optional Warp GPU kernels
- Routing/graph: OSMnx (build the graph), igraph/networkit (fast shortest paths)
- Transit: GTFS via `gtfs_kit` / partridge
- LLM: Ollama (Nemotron), structured output via JSON schema
- Optimizer: Verifiers (Prime Intellect) + numpy/torch
- API: FastAPI + uvicorn + websockets
- Frontend: React + deck.gl + MapLibre GL
