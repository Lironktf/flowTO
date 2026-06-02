# FlowTO — a live digital twin of Toronto

> **Team:** FlowTO · **Challenge:** Environmental Impact (urban mobility) ·
> **NVIDIA Spark Hack Series** — *"Your Code. Your Hardware. Your Edge."*
> **100% on-device** on a DGX Spark (GB10). No cloud.

A city-scale traffic + transit **digital twin**: simulate the network, apply
interventions, and watch it recompute — driven by a principled equilibrium
engine, an adaptive blast-radius recompute, and an on-device Nemotron copilot.
**Hero scenario:** FIFA WC 2026 post-match egress at BMO Field.

The web app is a two-mode planner's instrument:

- **Simulate** — a 3-D camera + a non-linear-editor timeline; scrub the matchday,
  cross full-time, watch the egress surge, and compare Before / After.
- **Edit** — a top-down workspace with a tool rail; click the map to drop
  closures / lane reductions / one-ways / signal retiming, snapped to real roads,
  recomputed via blast-radius.

Everything on the map is **real engine output** — the actual committed Toronto
graph (27,411 nodes / **73,036 directed edges**) recolored by the assignment
engine, not canned data.

---

## Submission at a glance

| Rubric item | Where |
|---|---|
| **Team name** | FlowTO (see [Team roster](#team-roster)) |
| **Project description** | This section + [Architecture](#architecture) |
| **Challenge selected** | [Challenge & bounties](#challenge--bounties) — Environmental Impact / urban mobility |
| **3–5 min demo video** | [Demo video](#demo-video) (link + run-of-show) |
| **Quick start** | [Quick start](#quick-start) |
| **Tech stack & architecture** | [Architecture](#architecture) |
| **Reproduce the demo (env / keys / .env)** | [Reproduce the demo](#reproduce-the-demo) |
| **Datasets / synthetic data + provenance** | [Datasets & provenance](#datasets--provenance) |
| **Known limitations & next steps** | [Known limitations & next steps](#known-limitations--next-steps) |
| **Deployed URL** | On-device only — see [Demo video](#demo-video) for a screen capture |
| **Team roster** | [Team roster](#team-roster) |

A copy of this map also lives in [`SUBMISSION.md`](SUBMISSION.md).

---

## Challenge & bounties

**Track: Environmental Impact — urban mobility.** FlowTO is a planning instrument
for moving a city's people with less delay and less wasted fuel: a planner can
test a year of interventions before a single cone goes down, entirely on their
own hardware.

We also target the three bounties:

| Bounty | Our hook |
|---|---|
| **Best use of NVIDIA Nemotron** | NL planner copilot — parses intent → validated tool calls, explains results, cites Toronto bylaws (local RAG). Live `nemotron3:33b` via Ollama on the Spark. |
| **Arm Architecture Innovation** | The whole stack is built and tuned on the GB10 (aarch64): cuGraph SSSP assignment backend + cuDF data pipeline, validated byte-equivalent to the CPU path. |
| **Prime Intellect — Verifiers** | The auto-optimizer is *sim-as-verifier*: every candidate plan is scored by actually running the simulation under bylaw + budget constraints. |

---

## Demo video

> 🎥 **3–5 min demo video:** **https://youtu.be/Yh3Qg2grTw0**

If the live box hiccups, a pre-recorded screen capture stands in (FlowTO is
on-device only, so there is **no public deployed URL** — the video / capture is
the deployed artifact). The exact 90-second click sequence, fallbacks, and the
rubric/bounty close are in **[`demo/RUNBOOK.md`](demo/RUNBOOK.md)**.

**The story (baseline → surge → fix):** scrub to a weekday 5pm (calm network) →
inject the BMO Field post-match surge (Gardiner / Lake Shore melt deep red) →
ask the copilot to *"ease the post-match gridlock without breaking any bylaws"* →
it returns a cited, bylaw-checked plan → apply & recompute via blast-radius →
corridors melt red → green, with a headline Before/After metric, computed
on-device.

---

## Quick start

```bash
# 1. Python env + tests (CPU — works on any laptop)
make install          # Python 3.12/3.13 venv + pip install -e ".[dev,api,data]"
make test             # pytest -q -m "not spark"  (all green; Spark GPU/LLM tests gated)

# 2. Run the API (loads the real graph, warms the baseline assignment)
scripts/run_api.sh                         # http://localhost:8000  (OpenAPI at /docs)

# 3. Run the frontend (Vite dev server, proxies /api → :8000)
cd frontend && cp .env.example .env        # then add your Mapbox token (see below)
npm install && npm run dev                 # http://localhost:5173

# 4. Headless demo + perf evidence (no browser needed)
.venv/bin/python -m torontosim.demo.wc_surge --scenario all  # baseline → surge → fix
.venv/bin/python -m torontosim.perf.bench                    # full-city vs blast-radius
```

Then open **http://localhost:5173**, click **Load the twin**, and use the
**Simulate / Edit** switch. On the first click, the browser downloads the Toronto
graph, builds its local intersection index, and reveals the map; baseline
pressures paint once the API's background warm-up finishes (the API warms only
the initial baseline — surge and fix are computed on demand).

`make install` uses `python3` by default; select another interpreter with
`make install PYTHON=python3.13`. The CPU demo falls back to a deterministic
heuristic demand model if the optional XGBoost model can't load (on macOS,
`brew install libomp` then `.venv/bin/pip install -e ".[model]"`).

> **The map needs a free Mapbox token** to render the Standard basemap (3-D
> buildings + time-of-day lighting). See [Reproduce the demo](#reproduce-the-demo).

More: phase-by-phase test commands in
[`docs/specs/TESTING.md`](docs/specs/TESTING.md); browser QA in
[`docs/specs/VISUAL_TESTING.md`](docs/specs/VISUAL_TESTING.md).

---

## Reproduce the demo

**Prerequisites:** Python 3.12 or 3.13, Node 18+ (for the frontend), and a free
[Mapbox access token](https://account.mapbox.com/access-tokens/) for the basemap.
GPU and the local LLM are **optional upgrades** — the CPU path is the demo path.

### 1. API keys / secrets

Only **one secret** is required, and only for the frontend map:

| Key | Required? | Purpose |
|---|---|---|
| `VITE_MAPBOX_TOKEN` | **Yes** (UI) | Mapbox *Standard* basemap (3-D buildings, time-of-day lighting). Free tier is plenty. |

The repo ships [`frontend/.env.example`](frontend/.env.example); copy it to
`frontend/.env` and paste your token. `frontend/.env` is **not tracked by git**,
so your token stays local.

```bash
# frontend/.env  (sample — copy from frontend/.env.example)
VITE_MAPBOX_TOKEN=pk.your_token_here
# VITE_API_BASE=/api          # optional; defaults to /api (proxied to :8000 in dev)
```

### 2. Backend environment variables (all optional — sensible defaults)

```bash
# .env-style reference for the backend (export these, or just use the defaults)

# Data / graph
TS_DATA_DIR=./data                 # data root (default: <repo>/data)
TS_GRAPH_SOURCE=osmnx              # "osmnx" (committed JSON, default) | "centreline" (real bake)
TS_MAX_PAIRS=12000                 # OD pairs warmed at startup (citywide coverage vs warm-up cost)

# Compute backend
TS_BACKEND=cpu                     # "cpu" (default) | "gpu" (cuGraph; Spark only)

# Copilot (Nemotron via Ollama) — only needed for live NL copilot
TS_OLLAMA_HOST=http://localhost:11434
TS_COPILOT_MODEL=nemotron3:33b
TS_COPILOT_LIVE=1                  # 1 = live Nemotron; copilot has a deterministic demo router otherwise
TS_RAG_BACKEND=auto               # "auto" | "embed" | "tfidf" (falls back to TF-IDF automatically)

# Demand model
FLOWTO_MODEL_BACKEND=sklearn       # training backend: "sklearn" (default) | "xgboost"
FLOWTO_DEMAND_MODEL=xgboost        # prediction model: "xgboost" | "gnn"

# Server bind (read by scripts/run_api.sh)
HOST=0.0.0.0
PORT=8000
```

Every one of these has a working default — a clean `make install` + `scripts/run_api.sh`
runs the full offline demo with **no env vars set** (the copilot uses its
deterministic demo router when no Ollama host is reachable).

### 3. Optional GPU / real-data path (DGX Spark)

```bash
# cuGraph assignment + the real full-city Centreline graph (requires a prior parquet bake)
TS_BACKEND=gpu TS_GRAPH_SOURCE=centreline scripts/run_api.sh
# Bake the real store on the Spark first:
scripts/spark/fetch_and_bake.sh
```

See [`infra/README-spark.md`](infra/README-spark.md) for the DGX Spark harness,
the `RAPIDS_OK` / `OLLAMA_OK` gating verdicts, and the SSH/tmux deploy mechanics.

---

## Architecture

```
 Toronto open data ─► datapipeline ─► graph (OSMnx baseline + Centreline loader)
                                         │
                          demand & OD (ML node-demand + IPF/ODME)
                                         │
                 simulation engine ──────┴───────────────────────────┐
                 BPR + Frank-Wolfe user equilibrium                   │
                 (oracle-validated vs SiouxFalls; CPU + cuGraph)      │
                 blast-radius adaptive recompute ──────────► FastAPI ─┼─► deck.gl + MapLibre/Mapbox
                                                              REST +  │   two-view IDE
                 copilot (Nemotron via Ollama) ─────────────► WS      │   (Simulate · Edit)
                 optimizer (heuristic, sim-as-verifier; cuOpt-ready)  │
```

**The CPU path is the demo path.** GPU (cuGraph) and the LLM (Nemotron) live
behind flags and are validated on the Spark via an SSH smoke harness — they
upgrade the demo but never block it.

### Tech stack

- **Backend:** Python 3.12+, FastAPI + Uvicorn + WebSockets, NumPy/SciPy,
  NetworkX, OSMnx, scikit-learn; optional cuGraph/cuDF (GPU), Ollama (Nemotron),
  PyTorch + PyG (GNN), DuckDB + PyArrow + Shapely (data pipeline).
- **Frontend:** React + Vite + TypeScript, deck.gl + MapLibre/Mapbox GL, Zustand;
  design system in `frontend/src/styles/flowto.css`.
- **Hardware:** NVIDIA DGX Spark (GB10, aarch64), 100% on-device.

### Python package — `src/torontosim/`

| Module | What it does |
|---|---|
| `datapipeline/` | Fetch (CKAN/GTFS/weather/restrictions) → Parquet + DuckDB + manifest |
| `graph/` | Canonical road graph: OSMnx baseline + Centreline loader, capacity calibration, per-field confidence |
| `model/` | Weather-aware ML node-demand → gravity OD + **IPF/Furness** + pragmatic **ODME** + TTS/Census seed; cuDF acceleration with a pandas fallback |
| `simulation/` | **BPR + Frank-Wolfe / Conjugate-FW user equilibrium**; CPU (Dijkstra) + GPU (cuGraph SSSP) backends; TNTP oracle |
| `blastradius/` | Affected-OD detection + bounded cones + adaptive subgraph recompute |
| `api/` | FastAPI: scenario CRUD, run/preview/compare, binary WS tick frames, `/demo/run`, copilot/optimize |
| `copilot/` | Nemotron NL → validated tool calls (preview-first, re-ask), bylaw constraint checker, local RAG |
| `optimizer/` | Heuristic proposals scored by **running the sim** (sim-as-verifier); cuOpt client (Spark add-on) |
| `transit/` | GTFS → route lines + scheduled vehicle trajectories (visual overlay) |
| `perf/` | Timing harness + benchmark CLI (full-city vs blast-radius) |
| `demo/` | FIFA WC match-day surge + the three deterministic demo scenarios |

`frontend/` — React + Vite + TypeScript, deck.gl + MapLibre/Mapbox, Zustand.

---

## Datasets & provenance

All data is **open / free**. The repo commits a test-critical offline subset so
the demo runs with no network; the full citywide pulls are baked pre-event on the
Spark (gitignored). Provenance/lineage is tracked in `data/README.md` and (for
real bakes) `data/manifest.json`.

| Dataset | Real / synthetic | Source & license | In repo? |
|---|---|---|---|
| **Road drive graph** (27,411 nodes / 73,036 edges) | Real | OpenStreetMap via OSMnx (ODbL) + City of Toronto Centreline (OGL-Toronto) | ✅ `data/graph/toronto_drive_graph.json` |
| **Traffic counts (TMC)** | Real | City of Toronto Open Data — turning-movement counts (OGL-Toronto) | ✅ `data/raw/tmc_raw_data_*.csv` |
| **Weather (hourly)** | Real | Environment & Climate Change Canada (Crown copyright) | ✅ partial, `data/raw/weather/` |
| **TTC GTFS** | Real | TTC / City of Toronto Open Data (OGL-Ontario) | ✅ cached `data/transit/ttc_latest.json` |
| **GO + UP Express GTFS** | Real | Metrolinx open data (OGL-Ontario) | ⏭️ on-demand via `transit.gtfs_reader` |
| **Bylaw corpus** (Ch. 743/880/886/937/950) | Real | Toronto Municipal Code (City Legal) | ✅ `data/raw/bylaws/*.pdf` + `data/bylaws_provenance.json` |
| **Demand training set** | **Synthetic** | Generated from the real graph (see below) | ✅ `data/model/training_dataset.csv` |
| **Demand model** (`HistGradientBoostingRegressor`) | Trained on synthetic | sklearn; XGBoost/GNN optional | ✅ `models/demand_model.pkl`, `models/gnn/*.pt` |
| **Baseline sim result** | Computed | Output of the engine on the baseline OD | ✅ `data/simulation/baseline_result.json` |

**Synthetic-data provenance (important honesty note).** The demand training data
is **synthetic**, generated from the *real* Toronto road graph using
Toronto-plausible patterns (rush-hour curve, downtown pull, arterials carry more,
weather dampening) via `torontosim.model.train_demand_model`. The model recovers
those relationships well (holdout **R² ≈ 0.93**) but it is learning a generator,
not ground-truth counts. To use **real** Toronto counts, drop a CSV with the
`FEATURE_ORDER` columns + a `vehicle_count` target at
`data/model/training_dataset.csv` and re-train — nothing downstream changes. The
real TMC counts (committed) are the intended ground-truth source; the ODME path
(`calibration=ipf_counts`) reconciles assigned link flows to observed peaks. See
[`README_MODEL_SIMULATION.md`](README_MODEL_SIMULATION.md) and
[`docs/03-data-sources.md`](docs/03-data-sources.md) for full detail.

> **Graph size, stated honestly:** the committed offline graph is **73,036 edges**
> (downtown extent + arterials) — that's what the app and all tests load. The
> full citywide Centreline graph (~80k–94k edges) is baked on the Spark and is
> not committed.

---

## What's verified (not just asserted)

- **Engine correctness** — Conjugate-Frank-Wolfe link flows match the published
  **SiouxFalls** user-equilibrium to ~0.1%; assignment is byte-for-byte deterministic.
- **Blast-radius** — equals a full recompute exactly at the all-or-nothing layer;
  run `python -m torontosim.perf.bench` for machine-specific speedup evidence.
- **On the DGX Spark** — cuGraph SSSP backend matches CPU (`RAPIDS_OK`, cuDF/cuGraph
  26.04 on GB10); live `nemotron3:33b` parses NL → a valid, cited tool call (`OLLAMA_OK`).
- **cuDF data pipeline** — model ingest/training CSV paths run on cuDF when the
  `[gpu]` extra is installed and produce output byte-equivalent to pandas; CPU-only
  environments fall back automatically (see `benchmarks/`).
- **Determinism** — the three demo scenarios (`baseline → wc_surge → wc_fix`) reproduce
  identical numbers every run; the egress-area congestion melts red → green.
- **Tests** — `make test` runs the full CPU suite green (Spark GPU/LLM tests are
  marked `@pytest.mark.spark` and run on the box via the harness); frontend
  `npm run build` + `npm run test`.

---

## Known limitations & next steps

The MVP (all core phases P00–P12) is complete and green. Remaining items are
network- or hardware-bound, and each has a working fallback (full detail in
[`docs/specs/HANDOFF.md`](docs/specs/HANDOFF.md)):

| Limitation | Today's fallback | Next step |
|---|---|---|
| Full citywide data not committed (Centreline ~118 MB, TMC, GTFS) | Committed OSMnx graph + demand model carry the demo offline | Run `scripts/spark/fetch_and_bake.sh` pre-event on the Spark |
| cuOpt not installed on the Spark | Heuristic optimizer (sim-as-verifier) always returns an improving plan | Drop in the cuOpt client (`optimizer/cuopt_client`) when available |
| 3-D extruded buildings need the 3D-massing dataset | Mapbox Standard 3-D buildings + flat ground | Load City of Toronto 3D Massing for true footprints/heights |
| Interactive demo uses the fast k-path engine | Equilibrium engine behind a flag (seconds on the full graph) | Promote equilibrium to the interactive path with caching |
| Transit is **visual-only** (no rider model) | Schedule-driven GTFS overlay + frequency labels | Couple transit loading to demand surges (stretch S1) |
| Demand training data is synthetic | R² ≈ 0.93 recovery; real TMC counts committed | Retrain on real TMC via `scripts/train_on_gx10.sh` |

---

## Team roster

> Drafted from the git history — **confirm names, roles, and contacts before submitting.**

| Name | GitHub | Role | Contact |
|---|---|---|---|
| Kevin Jiang | [@ANonABento](https://github.com/ANonABento) | Developer | kevin.jiang53@gmail.com |
| Liron Katsif | [@Lironktf](https://github.com/Lironktf) | Developer | Lironktf@gmail.com |
| Shahar Philipp Mayorov | [@PhilippMayorov](https://github.com/PhilippMayorov) | Developer | smayorov@uwo.ca |
| Ben Petlach | [@ben-petlach](https://github.com/ben-petlach) | Developer | ben.petlach@gmail.com |
| Jefferson Chen | [@VirtualFlight](https://github.com/VirtualFlight) | Developer | jefferson8268@hotmail.com|

---

## Docs

- [`SUBMISSION.md`](SUBMISSION.md) — submission checklist mapped to this README
- [`demo/RUNBOOK.md`](demo/RUNBOOK.md) — 90-second run-of-show, fallbacks, rubric close
- [`docs/specs/ROADMAP.md`](docs/specs/ROADMAP.md) — phases, locked decisions, dependency graph
- [`docs/specs/BUILD_STATUS.md`](docs/specs/BUILD_STATUS.md) — per-phase status dashboard
- [`docs/specs/HANDOFF.md`](docs/specs/HANDOFF.md) — what's done/deferred + exact run commands
- [`docs/specs/TESTING.md`](docs/specs/TESTING.md) · [`docs/specs/VISUAL_TESTING.md`](docs/specs/VISUAL_TESTING.md) — how to test
- [`infra/README-spark.md`](infra/README-spark.md) — the DGX Spark harness + gating verdicts
- `docs/00-…05-…` — original planning briefs · [`README_MODEL_SIMULATION.md`](README_MODEL_SIMULATION.md) — demand/sim layer deep-dive

---

## Attribution

Contains information licensed under the **Open Government Licence – Toronto**
(City of Toronto open data) and **Open Government Licence – Ontario** (TTC /
Metrolinx GTFS); road geometry from **OpenStreetMap** (ODbL); weather from
**Environment and Climate Change Canada**. Code licensed MIT.
