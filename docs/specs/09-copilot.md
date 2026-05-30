# P09 — Copilot: Nemotron NL→validated tool calls, preview-before-apply, local RAG

| | |
|---|---|
| **Priority** | High |
| **Depends on** | P06 |
| **Owner hint** | AI owner |
| **Status** | not started |

## Goal
A **local planner copilot** (Nemotron via Ollama on the Spark) that turns plain English into **validated structured
tool calls** against the scenario API, explains results, and cites local bylaw/policy docs via RAG. **Read-only by
default; preview-before-apply; never mutates the sim directly** — it calls the same validated tools the UI does.

**Why / rubric tie-in:** Best-use-of-Nemotron bounty + Usability. NL → JSON scenario edit → run → spoken-language
summary is the headline interaction.

## Current state
- None. (Memory note: Nemotron reasoning models need `think:False` + `format:json` or empty responses.)

## Target state
- `copilot/` module + P06 endpoints: NL request → `format=`-constrained JSON tool call (Pydantic schema shared with P06) → validate (+ semantic checks: edge ids exist, bylaws) → **preview** → user confirms → apply. Plus "explain this result" (free-text) and bylaw citations (RAG). Demo-safe model defaults, Spark-gated.

### In scope
Tool-call generation + validation + re-ask loop; the tool schema set; result explanation; local RAG over a small bylaw set; preview-before-apply guardrail; Ollama serving config.
### Out of scope
The optimizer (P10 — copilot may *invoke* it). Fine-tuning/LoRA (stretch). NIM/TRT-LLM (stretch; Ollama is the path).

## Design / implementation plan
(Specifics + snippet in **`research/05-local-ai-stack.md`**.)
1. **Model** — `ollama pull nemotron-3-nano:30b` (copilot brain), `nemotron-mini:4b` (fast fallback / pure tool-router). Reasoning models: `think:False` + `format:json`.
2. **Tool schemas** (`copilot/tools.py`) — Pydantic models **imported from P06 `api/schemas.py`** (single source of truth): `preview_intervention`, `create_scenario`, `run_simulation`, `compare_scenarios`, `retrieve_policy`, `explain_edge`. Strict; generate JSON Schema from Pydantic.
3. **Constrained generation + validation** (`copilot/plan.py`) — Ollama `chat(format=<schema>, options={temperature:0})` → Pydantic validate → **semantic checks** (edge_ids ∈ current graph; bylaw/action-mask allowed) → re-ask loop (≤3) feeding back the error. Returns a validated tool call.
4. **Guardrails** — read-only default; every state-changing call returns `requires_user_confirmation=true` and goes through `/preview`; a deterministic **constraint checker** (`copilot/constraints.py`) can block/warn before anything reaches the planner.
5. **RAG** (`copilot/rag.py`) — `sentence-transformers all-MiniLM-L6-v2` (CPU) + **Chroma/FAISS**; chunk a small curated bylaw/standards set; top-k=4 into the system prompt for `explain`/`retrieve_policy`; cite source doc + section.
6. **Explain** (`copilot/explain.py`) — free-text (no `format=`) summarizing a `CompareResult` ("egress +12% on the 504; here's why"), grounded by the run's numbers + RAG.
7. **API** (extends P06) — `POST /copilot/plan` (NL → validated tool call, preview), `POST /copilot/explain`, `POST /copilot/confirm` (apply a previewed call).

## Data / models / sources
`research/05` (exact Nemotron tags, Ollama `format=`+Pydantic+re-ask pattern, RAG stack, NIM/TRT-LLM stretch verdict, cuOpt for P10). **`design/js/data.js`** has the rehearsed copilot scripts + exact bylaw citations to seed the corpus + the demo: `copilotHero` ("Ease post-match gridlock near BMO Field without breaking bylaws" → 3-step plan citing Toronto Municipal Code Ch. 950 / King St Transit Priority / Ch. 880 fire-route / AODA 2005) and `copilotBlocked` ("close Lake Shore both ways" → refuses, cites Ch. 880 + TTC streetcar-replacement, offers contraflow). Bylaw corpus = those citations curated under `data/bylaws/`.

## Files to create / modify
**Create:** `src/torontosim/copilot/{__init__,plan,tools,constraints,rag,explain,serve}.py`; `data/bylaws/` (curated docs + sources); `api/routes/copilot.py` (if not from P06); `tests/test_copilot_plan.py`, `tests/test_copilot_rag.py`; `scripts/spark/smoke_ollama.py` (from P00, extended).
**Modify:** `api/schemas.py` (shared tool schemas).

## Test-driven design
- `test_copilot_plan.py` (first, **mock Ollama**): given a canned model response, `plan()` validates it → tool call; an invalid `edge_id` triggers the re-ask loop; a malformed JSON is rejected. (No live model in CI.)
- Guardrail test: a state-changing call returns `requires_user_confirmation=true` and does not mutate the store.
- `test_copilot_rag.py`: a bylaw query retrieves the relevant chunk (top-k contains the expected doc).
- **Spark-only** (`@pytest.mark.spark`): live `nemotron-3-nano:30b` parses 2 rehearsed prompts into valid tool calls (the demo queries).

## Verification
**Local (CPU, mocked model):** unit tests green; RAG retrieves over the bylaw set with a local embed model.
**On Spark:** `scripts/spark/smoke_ollama.py` (model serves + emits valid JSON); run the 2 rehearsed demo prompts live → valid tool calls → preview → confirm → sim runs; measure first-token latency (feeds P11/demo).

## Tasks
- [ ] T09.1 Ollama serve config + `smoke_ollama.py` + model pulls on Spark — *0.5d*
- [ ] T09.2 Tool schemas (shared w/ P06) + `plan.py` constrained gen + validate + re-ask — *1d*
- [ ] T09.3 Constraint checker + preview-before-apply guardrail — *0.5d*
- [ ] T09.4 RAG (embed + Chroma + bylaw corpus + citations) — *1d*
- [ ] T09.5 `explain.py` result summaries — *0.5d*
- [ ] T09.6 Tests (mocked plan/rag/guardrail) + Spark live 2-prompt check — *0.5d*

## Risks / fallbacks
- **Nemotron pull/serve issues on aarch64** → pin a known-good Ollama version (a Spark hang was reported); fall back to `nemotron-mini:4b` or another cached `tools`-tagged model; **a button that fires the same scenario JSON** if NL parsing flakes on stage.
- **Model emits invalid JSON** → `format=` constrains decoding + Pydantic re-ask; temperature 0 for determinism-ish.
- **RAG noise on a tiny corpus** → keep the corpus small + curated; citations link to source so claims are checkable.
