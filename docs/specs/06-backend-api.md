# P06 — Backend API: FastAPI, scenario CRUD (REST), binary tick frames (WebSocket)

| | |
|---|---|
| **Priority** | Core |
| **Depends on** | P04, P05 |
| **Owner hint** | Glue/PM owner |
| **Status** | not started |

## Goal
A single **FastAPI** process that exposes the simulation to the frontend: **REST** for scenario CRUD + runs +
optimizer/copilot calls, **WebSocket** for streaming binary edge-pressure tick frames. In-memory scenario state +
JSON snapshots (no DB). It orchestrates sim ⇆ blast-radius ⇆ copilot ⇆ optimizer.

**Why / rubric tie-in:** Usability + Completeness. This is the seam that turns the engine into an interactive tool;
long GPU tasks must not block requests (async jobs + progress).

## Current state
- None. Liron's pipeline is invoked via scripts/tests; results land in `baseline_result.json`. No server.

## Target state
- `api/` FastAPI app: scenario CRUD, run baseline / run scenario (blast-radius), before/after compare, copilot + optimizer endpoints, health/debug. **Pydantic schemas** shared with the copilot tool-call layer. WebSocket pushes compact binary tick frames; REST for slower control calls. Async job pattern for GPU/LLM work (never block the event loop).

### In scope
REST endpoints, WS tick streaming, Pydantic schemas, in-memory scenario store + JSON snapshots, async job runner, CORS for the Vite dev server.
### Out of scope
The sim/optimizer/copilot internals (P04/P05/P09/P10 — this wraps them). Auth/multi-tenant (explicitly cut).

## Design / implementation plan
1. **Schemas** (`api/schemas.py`) — Pydantic models: `Scenario`, `Intervention` (closure / lane_reduction / one_way / signal_retiming / capacity / add_edge — mirrors `mutations.py`), `RunRequest`, `RunResult`, `CompareResult`, `TickFrame`. **These are the same schemas the copilot emits** (P09) — single source of truth.
2. **REST** (`api/routes/`):
   - `POST /scenarios` create · `GET/PATCH/DELETE /scenarios/{id}` · `GET /scenarios/{id}/interventions`
   - `POST /scenarios/{id}/run` → baseline or scenario run (`recompute={full,blast}`) → returns summary + job id
   - `GET /scenarios/{id}/compare?against=baseline` → before/after deltas
   - `POST /scenarios/{id}/preview` → preview-before-apply (no mutation committed)
   - `POST /copilot/plan` (P09) · `POST /optimize` (P10) · `GET /healthz`, `GET /debug/state`
3. **WebSocket** (`api/ws.py`) — `WS /scenarios/{id}/stream`: on each sim iteration/frame, pack edges into a **binary record** `[edge_id:u32, load:f32, speed:f32, pressure:f32, closure:u8]` (matches `research/06` frontend contract); throttle/downsample to a target rate; HTTP/JSON for control.
4. **Scenario store** (`api/store.py`) — in-memory dict keyed by scenario id; JSON snapshot to `data/scenarios/{id}.json`; loads the baseline graph once at startup (shared, read-only) + per-scenario mutated copies.
5. **Async jobs** (`api/jobs.py`) — long sim/optimizer/copilot calls run in a thread/process pool; WS/poll emits progress events; the event loop never blocks (per `research/06` + spec backend-risk note).
6. **Frame encoding** (`api/encoding.py`) — struct-pack helpers; shared edge-id index so the client maps records → geometry uploaded once.

## Data / models / sources
`research/06` (binary tick frame fields, async-job requirement, no-DB). Reuses P04 `simulate_traffic`/`compare_simulations`, P05 `recompute`. Schemas shared with P09 copilot.

## Files to create / modify
**Create:** `src/torontosim/api/{__init__,app,schemas,store,jobs,ws,encoding}.py`, `api/routes/{scenarios,run,copilot,optimize,health}.py`; `tests/test_api_scenarios.py`, `tests/test_ws_frames.py`; `scripts/run_api.sh`.
**Modify:** `pyproject.toml` `[api]` extra (fastapi, uvicorn, websockets, pydantic).

## Test-driven design
- `test_api_scenarios.py` (first, `TestClient`): create scenario → add closure → run → compare returns deltas; preview does **not** mutate stored state; bad `edge_id` → 422.
- `test_ws_frames.py`: connect WS, run a scenario, assert ≥1 binary frame decodes to the expected record layout; throttling caps frame rate.
- Determinism: same scenario via API twice → identical compare result (ties into P04 determinism).
- Async: a long-running run returns a job id immediately; `/healthz` stays responsive during it.

## Verification
**Local:** `scripts/run_api.sh` (uvicorn) → `curl` create/run/compare; a tiny WS client prints decoded frames; OpenAPI docs at `/docs`.
**On Spark:** run the API on the Spark over SSH, tunnel the port via Tailscale, hit it from the dev box; confirm GPU sim path + Nemotron/cuOpt endpoints work end-to-end on-device.

## Tasks
- [x] T06.1 Pydantic schemas (shared with copilot) — *0.5d*
- [x] T06.2 Scenario store + JSON snapshots + startup graph load — *0.5d*
- [x] T06.3 REST routes (CRUD, run, preview, compare) — *1d*
- [x] T06.4 WS binary tick streaming + encoding + throttle — *1d*
- [x] T06.5 Async job runner + progress events — *0.5d*
- [x] T06.6 Tests (REST, WS, determinism, async) + `run_api.sh` — *0.5d*

## Risks / fallbacks
- **GPU/LLM call blocks the loop** → async job pool + progress; mitigated by design.
- **WS frame storms** → server-side throttle + downsample edges sent; client coalesces (P07).
- **Scenario state races** → single-writer per scenario; copy-on-mutate graph (Liron already copies).
