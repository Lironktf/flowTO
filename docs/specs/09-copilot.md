# P09 — Copilot: fully-live Nemotron agent, data-backed guardrails, apply-and-run, streaming

| | |
|---|---|
| **Priority** | High |
| **Depends on** | P06 (API), P10 (optimizer) |
| **Owner hint** | AI owner |
| **Status** | rebuild in progress (was: scripted scaffold) |

## Goal
A **fully-live local planner copilot** (Nemotron via Ollama on the Spark) that turns plain English into
**validated, structured tool calls** against the scenario API, **applies and runs** them on confirmation,
**explains** the result, and **refuses** illegal/unsafe requests against **real Toronto open data** — citing
the actual Municipal Code via RAG. **Read-only by default; preview-before-apply; never mutates the sim
directly** — it calls the same validated tools the UI does.

**Why / rubric tie-in:** Best-use-of-Nemotron bounty + Usability. NL → JSON tool call → preview → confirm →
run → spoken-language summary, with **grounded refusals backed by real city data**, is the headline interaction.

## Scope decisions (locked 2026-05-30)
- **Fully live.** Every off-script prompt goes to real Nemotron (`nemotron3:33b`); the two rehearsed prompts
  may still resolve deterministically as a stage safety net, but live is the default path, not a fallback.
- **Full apply loop + auto-run.** `POST /copilot/confirm` applies a previewed tool call to a scenario, runs it,
  compares vs baseline, and returns the explanation — the user sees results immediately.
- **Embeddings RAG with TF-IDF fallback.** `sentence-transformers` (all-MiniLM-L6-v2) + Chroma on the Spark;
  auto-degrade to the existing dependency-free TF-IDF retriever when the `ai` extra / embed model is absent.
- **Data-backed constraints.** Replace the hardcoded keyword refusal with checks against **real Toronto open
  data** (fire-route corridors, road classification, transit-priority corridors) mapped to graph edges.
- **Multi-tool agent loop.** Nemotron can chain tools (plan → run → compare → explain → optimize) with
  preview/confirm as human gates — a real agent, not single-shot translation.
- **Streaming + latency HUD.** Token-stream Nemotron output to the chat panel; surface first-token + total
  latency + tok/s (the cold-load ~11s vs warm ~1s story).
- **Copilot invokes the optimizer.** A tool that calls P10 `optimizer.propose` and previews the optimized plan.
- **Corpus baked offline + committed.** A bake script (`scripts/bake_bylaws.py`) downloads the Municipal Code
  PDFs, extracts + sections them, and writes `src/torontosim/copilot/corpus/mc*.md` with provenance (kept
  **in-package** so the RAG loader needs no runtime path config; the raw PDF cache under `data/raw/` is
  gitignored). Constraints are backed directly by the graph's real `road_class`/`road_name` edge data plus a
  curated protected-corridor table — no separate constraints file needed. Committed → demo is fully offline.

## Environment (verified 2026-05-30)
- Spark Ollama reachable over Tailscale at `http://100.124.76.16:11434` (SSH/22 blocked from dev; dev points
  the Ollama base URL there). On-Spark deploy uses `http://localhost:11434`. Configurable via `TS_OLLAMA_HOST`.
- Live mode gated by `TS_COPILOT_LIVE=1`. Model `TS_COPILOT_MODEL` (default `nemotron3:33b`; `nemotron-3-super:latest`
  for max quality). `nemotron3:33b` + `format=<schema>` + `think:false` + `temperature:0` returns clean
  schema-valid JSON (verified). Warmup ping at startup + `keep_alive` to dodge the ~11s cold load.
- See memory `spark-ollama-access` for the full access notes.

## Tool set (the agent's tools — schemas in `copilot/tools.py`, shared with `api/schemas.py`)
`preview_intervention` (now carries **real `Intervention` ops**, not just prose) · `create_scenario` ·
`run_simulation` · `compare_scenarios` · `optimize` (P10) · `retrieve_policy` (RAG) · `explain_edge` · `refuse`.

## Architecture
```
CopilotPanel → appStore.copilotAsk → POST /copilot/plan  (live Nemotron agent → validated ToolCall + citations)
                                    → POST /copilot/confirm (apply ops → run → compare → explain)   [auto-run]
                                    → GET  /copilot/stream  (SSE token stream + latency HUD)
constraints.check_request  ← data/bylaws/constraints.json (real fire-route / road-class / transit-priority data)
rag.retrieve               ← embeddings (Chroma) | TF-IDF fallback over data/bylaws/corpus/*.md
```

## Build phases
1. **Foundation (offline, local):** `bake_bylaws` (PDFs → chunked corpus + `constraints.json`); embeddings RAG
   with TF-IDF fallback; data-backed `constraints.check_request`. Tests: corpus loads, embed/fallback parity,
   real-data refusal (fire route / residential through-traffic / transit priority).
2. **Live brain:** configurable Ollama host/model + warmup; rewrite `plan.py` into a real multi-tool agent loop
   (validate + semantic checks + re-ask ≤3); **attach real `Intervention` ops** to plans; wire `use_live` through
   `/copilot/plan` (gated by `TS_COPILOT_LIVE`). Tests: mocked-model plan/validate/re-ask + live Spark 2-prompt check.
3. **Apply loop:** `POST /copilot/confirm` → create/patch scenario → validate edges → apply → **run** → compare vs
   baseline → explain; frontend confirm action + render results into map/metrics. Guardrail test: no mutation
   without confirm.
4. **Streaming + latency HUD:** SSE `/copilot/stream` (Ollama `stream:true`); frontend incremental render +
   first-token/total/tok-s HUD; startup warmup.
5. **Optimizer tool + agent polish:** `optimize` tool → `optimizer.propose` → preview; multi-step chaining.
6. **Tests + Spark rehearsal:** full mocked suite green in CI; live rehearsal of both demo prompts on the Spark;
   record latencies for P11/demo.

## Files to create / modify
**Create:** `scripts/bake_bylaws.py` (or `datapipeline` subcommand); `data/bylaws/corpus/*.md` (+ provenance) and
`data/bylaws/constraints.json`; `src/torontosim/copilot/agent.py` (multi-tool loop); `src/torontosim/copilot/ollama_client.py`
(host/model config + warmup + stream); `tests/test_copilot_plan.py`, `tests/test_copilot_constraints.py`,
`tests/test_copilot_confirm.py`, `tests/test_copilot_stream.py`.
**Modify:** `copilot/{plan,planner,tools,constraints,rag,explain}.py`; `api/app.py` (`/copilot/confirm`, `/copilot/stream`,
live wiring); `api/schemas.py` (tool schemas + confirm payload); `frontend/src/{api/client.ts,state/appStore.ts,components/CopilotPanel.tsx}`;
`scripts/spark/smoke_ollama.py` (model tag); `pyproject.toml` (pdf extract dep for bake, if needed).

## Test-driven design
- `test_copilot_plan.py` (mock Ollama): canned response → validated ToolCall; invalid `edge_id` triggers re-ask;
  malformed JSON rejected; agent can chain plan→run→explain.
- `test_copilot_constraints.py`: a fire-route / residential-through / transit-priority intervention is refused with
  the correct real citation; a benign one passes.
- `test_copilot_confirm.py`: confirm applies + runs + returns compare/explain; a state-changing plan does **not**
  mutate the store before confirm.
- `test_copilot_rag.py` (exists): top-k retrieval; **add** embed/TF-IDF parity on the demo queries.
- **Spark-only** (`@pytest.mark.spark`): live `nemotron3:33b` parses both rehearsed prompts into valid tool calls.

## Risks / fallbacks
- **Cold-load latency (~11s)** → startup warmup ping + `keep_alive=10m`; HUD frames it as "loading model" once.
- **Model emits invalid/over-reasoned JSON** → `format=<schema>` + Pydantic re-ask (≤3) + `think:false` + temp 0.
- **Live decode flakes on stage** → rehearsed prompts resolve deterministically; a button fires the same scenario JSON.
- **RAG noise on a small corpus** → keep curated; citations link to source section so claims are checkable.
- **City site down at bake time** → corpus + constraints are committed; bake is a pre-event step, not runtime.

## Tasks
- [x] T09.1 `bake_bylaws` — Municipal Code PDFs → in-package §-section corpus (49 real sections, committed) — *1d*
- [x] T09.2 Embeddings RAG (MiniLM + in-memory cosine) with TF-IDF fallback + `backend_name()` + parity test — *0.5d*
- [x] T09.3 Data-backed `constraints.check_request` (graph road_class/name + protected corridors) + `advisories()` — *0.5d*
- [ ] T09.4 `ollama_client` (host/model config + warmup + stream) + live `plan.py` agent loop + re-ask — *1d*
- [ ] T09.5 Real `Intervention` ops on plans + `POST /copilot/confirm` (apply → run → compare → explain) — *1d*
- [ ] T09.6 Streaming `/copilot/stream` + frontend incremental render + latency HUD — *0.5d*
- [ ] T09.7 `optimize` tool → P10 + multi-tool agent chaining — *0.5d*
- [ ] T09.8 Tests (mocked plan/constraints/confirm/stream) + live Spark 2-prompt rehearsal — *0.5d*
</content>
