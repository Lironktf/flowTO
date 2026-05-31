# P09 — Copilot: implementation spec for all remaining TODOs

The build order after the routing rebuild + flyTo + de-hardcode (all merged-ready on
`feat/copilot-routing`). Each item: **Goal · Approach · Files · Contract · Tests · Effort · Risks**.
Tiers are priority bands; within a tier, order is flexible. Pairs with
`09-copilot-capabilities-routing.md` (taxonomy/contract) and `09-copilot-constraints-ux.md` (warnings).

Current contract recap: one `classify()` → dispatch; `ToolCall` already carries
`warnings[]` + `view`; `/copilot/route` is the single entry; `deepMode` = depth override.

---

## Tier 0 — Confirm/preview UX bugs (from live testing — DO FIRST)

Surfaced testing "block dubarry ave": a staged plan shows **two** apply surfaces (one broken),
**no preview highlight** of the proposed road, and a confusing **"2 changes"** label. These are
correctness bugs in the apply flow — fix before new features.

### 0a. Two confirm surfaces, one wired to the wrong source
**Symptom:** chat shows "Confirm & run (2 changes)" *and* the map shows a "Copilot plan ready ·
Apply & recompute / Discard" banner — two ways to apply one plan.
**Root cause:**
- Chat button → `copilotConfirm(msgIndex)` reads `m.interventions`, materializes a closure scene
  object, and applies via `applyEdits()` — **correct**.
- Map banner → `applyPlan()` → `set({planStaged:false}); applyEdits()`. `applyEdits()` flattens
  **`get().objects`** — but staging never adds the plan to `objects`. So the banner applies whatever
  scene objects pre-existed (a prior Edit), **not** the staged copilot plan. Wrong source.
**Fix (single source of truth for the staged plan):**
- Add state `stagedPlan: { msgIndex: number; interventions: Intervention[]; edgeIds: string[] } | null`,
  set in `afterPlan`/`renderPlan` when a plan stages (replaces the bare `planStaged` boolean; keep a
  derived `planStaged = !!stagedPlan`).
- **One apply path:** both the chat button and the map banner call `copilotConfirm(stagedPlan.msgIndex)`.
  Delete `applyPlan()`'s `applyEdits()`-on-objects path. `discardPlan` clears `stagedPlan`.
- **Decision (consolidate):** keep the **chat confirm** as the primary (it carries the rationale,
  citations, result card, revert). Make the **map banner non-duplicative** — either (rec.) a
  preview-only indicator ("Plan staged — review in chat", no apply button), or a thin mirror that
  also calls `copilotConfirm`. Do not keep two independent apply buttons.
**Files:** `appStore.ts` (`stagedPlan` state, `afterPlan`/`renderPlan`, `applyPlan`/`discardPlan`,
`copilotConfirm` clears it), `MapCanvas.tsx` (banner → preview-only or `copilotConfirm`),
`CopilotPanel.tsx` (confirm button unchanged or reads `stagedPlan`).
**Tests:** vitest — staging sets `stagedPlan`; banner-apply and chat-confirm both go through
`copilotConfirm` and apply the **plan's** edges (not pre-existing objects); discard clears it.
**Effort:** M.

### 0b. No preview highlight of the proposed closure
**Symptom:** staging only frames the camera (`applyView → fitToBounds`); the road to be closed isn't
highlighted. The grey road + "1" marker on the map is a *previously applied* closure; the blue road
is `selectedRoadId` from an earlier selection — neither is the staged Dubarry plan.
**Fix:** render a distinct **staged-preview overlay** for `stagedPlan.edgeIds` (e.g. dashed/amber
outline, visually separate from applied grey closures and the blue selection) so "preview before
apply" is literally visible. Clear on confirm/discard.
**Files:** `appStore.ts` (`stagedPlan.edgeIds` from the plan's `close_edge` ops / `view.edge_ids`),
`MapCanvas.tsx` (new preview `PathLayer` keyed on `stagedPlan`), `flowto.css` (preview style).
**Tests:** vitest — staging populates `edgeIds`; component renders the preview layer; clears on apply.
**Effort:** S–M. **Note:** pairs with 0a (both hang off the new `stagedPlan` state).

### 0c. "2 changes" reads wrong for one road
**Symptom:** closing one road (2 directional segments) shows "Confirm & run (2 **changes**)".
**Fix:** make the label road-centric. Count **distinct roads** vs **segments**: button
"Confirm & run" with a sub-line like "Close Dubarry Avenue · 2 segments" (rationale already says
"2 road segment(s)"). Don't label directional twins as "changes." For mixed plans, summarize by op
type ("close 1 road · scale 1 road"). Keep the "Sealed edges: N" tile (accurate) but it's
*edges/segments*, not *changes*.
**Files:** `CopilotPanel.tsx` (confirm label from the plan's interventions — group by `road_name`/op),
optionally a small `summarizeInterventions(interventions)` helper.
**Tests:** vitest — 2 close_edge on one road → label says 1 road / 2 segments, not "2 changes".
**Effort:** S.

**Sequence for Tier 0:** 0a (the `stagedPlan` state) first — 0b and 0c both build on it.

---

## Tier 1 — Capabilities (deliver what the taxonomy promises)

### 1. `demand_surge` backend op  *(unblocks the agent + the Edit surge tool)*
**Goal:** make demand surge a real, simulatable op. Today it's a *phantom* — the Edit tool
emits it and `client.ts` types it, but it's not in `InterventionType` and the sim rejects it.
Also reconcile the **naming split**: `appStore.ts` emits `op:"demand_change"`, `client.ts` types
`"demand_surge"`. Pick **`demand_surge`** everywhere.

**Approach:** surge mutates **OD demand**, not graph topology — so it can't ride through
`apply_scenario` (graph-only, `simulate_traffic.py:391`). Instead:
- Extract `demand_surge` ops *before* the sim and fold them into the OD matrix (add/scale trips
  at a node or nearest-node-to-(lng,lat), optionally biased to compass directions).
- Generalize the injection already in `demo/wc_surge.py` (post-match egress) into a reusable
  `apply_demand_surge(od, graph, surge) -> od'`.

**Files:**
- `api/schemas.py` — add `"demand_surge"` to `InterventionType`; add fields `amount`,
  `directions: list[str]`, `lng`, `lat`, `mode` ("absolute"|"relative") to `Intervention`.
- `simulation/simulate_traffic.py` — in `simulate_scenario`, split ops: graph ops → `apply_scenario`,
  `demand_surge` ops → OD transform before solving. Or a thin `apply_demand_ops(od, graph, ops)`.
- `graph/mutations.py` or new `simulation/demand.py` — `apply_demand_surge`.
- `demo/wc_surge.py` — refactor its injection to call the shared helper (no behaviour change).
- `copilot/planner.py` — `_dispatch` already has no surge intent; add a `surge` intent path OR let
  the agent emit it. Frontend `interventionsFromObjects` → rename `demand_change`→`demand_surge`.
**Contract:** `{op:"demand_surge", node_id?|lng?+lat?, amount, directions?, mode?}`.
**Tests:** unit — `apply_demand_surge` raises OD at the target node; sim with a surge op runs and
raises downstream pressure vs baseline; `apply_scenario` no longer raises on the op.
**Effort:** M–L (touches sim core). **Risks:** OD-vs-graph plumbing; keep blast-recompute correct.

### 2. Query gaps — `explain_congestion` + `inspect_road`
**Goal:** answer "*why* is X jammed?" and "give me stats on X" with real data (taxonomy A, ◐ today —
`explain.py` only explains *comparisons*).

**Approach:** both are read-only over the cached baseline graph (like `_answer_congestion`).
- Add intents **`explain`**, **`inspect`** to `classify.Intent` + the classifier prompt.
- `explain_congestion(state, road_name)` — resolve the road (resolve.py), read its edges' pressure
  vs capacity, and the **upstream contributors**: incoming edges / OD pairs routing through it
  (use `graph.in_edges` + routing). Report v/c, the binding constraint (capacity vs demand), and
  the top 1–2 feeder roads. Optionally cite the GNN-predicted demand (main's model).
- `inspect_road(state, road_name)` — flat stats: class, lanes, capacity, current pressure/load,
  open/closed, # segments.
**Files:** `copilot/classify.py` (+2 intents), `copilot/planner.py` (`_dispatch` branches +
`_explain_congestion`/`_inspect_road` helpers), reuse `resolve.road_edges_by_name`.
**Contract:** both return `ToolCall(tool="answer", rationale=…, view=fit on the road)`.
**Tests:** mocked-baseline state → explain names the binding constraint + a feeder; inspect returns
the right class/lanes; both attach a `fit` view.
**Effort:** M. **Risks:** upstream-contributor calc can be slow on 81k — cap the traversal.

### 3. SSOT warning system — `assess()` + `POST /assess`  *(warn-don't-block)*
**Goal:** one module both manual closures (clickops) and the copilot call, grounded in the bylaw
RAG + Nemotron, returning severity-coded `Warning[]` — never refuses. Folds in the current hard
`check_request` block. Full design in `09-copilot-constraints-ux.md`.

**Approach:**
1. `assess(interventions, state) -> list[Warning]`: resolve affected roads (resolve.py) → deterministic
   **severity floor** from `constraints.py` (fire-route/transit = danger, arterial = warn) →
   **RAG-grounded Nemotron** pass (`rag.retrieve` + `ollama_client.generate`) for the cited bylaw §
   + plain-English detail → merge/dedupe.
2. `POST /assess {interventions}` → `{warnings}`.
3. Replace the `_blocked_call` hard-refuse with `assess()` warnings on the ToolCall (`warnings[]`
   field already exists); copilot `plan`/`route` attach them. Clickops `placeAt`/`applyEdits` call
   `/assess` and push to `store.warnings` (RightDock `WarningsBody` already renders `.warn-row`).
**Files:** `copilot/assess.py` (new), `api/app.py` (+`/assess`), `api/schemas.py` (Warning req/resp),
`copilot/planner.py` (`_dispatch` attaches warnings, drop `_blocked_call` hard path),
`frontend/src/state/appStore.ts` (`placeAt`/`applyEdits`/`copilotConfirm` → `api.assess`),
`frontend/src/api/client.ts` (`assess()`).
**Contract:** `Warning {severity: info|warn|danger, title, detail, ref}` (already in `tools.py` +
frontend). **Perf:** deterministic floor instant; Nemotron detail async; cache per edge-set.
**Tests:** mocked model → fire-route closure = danger + cited §; never returns `blocked`; clickops
and copilot produce identical warnings for the same edges.
**Effort:** L. **Risks:** overlaps main's restricted-road warnings (frontend `restrictedClosureWarnings`)
— unify, don't double-warn. Coordinate with roommate (this was a shared/handoff thread).

---

## Tier 2 — Robustness & UX

### 4. Stream agent steps live (SSE) + dedup repeated sims
**Goal:** the agent loop freezes ~12 s with no feedback; stream each step as it happens. Also stop
the model re-running an identical `simulate`.
**Approach:** new `POST /copilot/agent/stream` (SSE) yielding `{type:"step", tool, thought, observation}`
per loop iteration, then a terminal `{type:"result", …}`. Frontend consumes like the chat stream,
appending to `agentSteps` live. In `agent.run_agent`, key observations by `(tool, args-hash)` and
short-circuit a repeat with the cached observation + a nudge.
**Files:** `copilot/agent.py` (yield steps; dedup map), `api/app.py` (+SSE route),
`frontend/src/api/client.ts` (`copilotAgentStream`), `appStore.ts` (agent branch consumes stream),
`CopilotPanel.tsx` (trace fills live).
**Tests:** agent.py dedup unit (identical sim returns cached, no 2nd sim call); SSE yields N steps.
**Effort:** M. **Risks:** SSE + abort wiring (reuse the chat-stream plumbing/AbortController).

### 5. Model keep-alive ping loop
**Goal:** kill the ~8–11 s cold-load stall mid-session (`ollama_client` has one-shot `warmup()` +
`keep_alive`, but the model still ages out when idle).
**Approach:** a background task in the API lifespan that pings `ollama_client.warmup()` (or a 1-token
generate) every ~`KEEP_ALIVE/2`. Guard behind `TS_COPILOT_LIVE` + `available()`; no-op if unreachable.
**Files:** `api/app.py` (lifespan: add an `asyncio`/thread heartbeat), maybe `ollama_client.ping()`.
**Tests:** unit — ping loop calls warmup on schedule (inject a fake clock/counter); disabled when
`TS_COPILOT_LIVE=0`.
**Effort:** S. **Risks:** don't leak the task on shutdown; keep it daemon/cancellable.

### 6. Confirm → register as a saved simulation
**Goal:** an applied copilot plan should appear in the Simulate left-rail (selectable/revertable),
not just repaint. Today `copilotConfirm` runs + paints but doesn't enter `savedSims`.
**Approach:** after confirm, `loadSavedSims()` (the scenario is already created server-side) or
explicitly `saveCurrent`; ensure `scenarioId` is set so revert/compare work.
**Files:** `frontend/src/state/appStore.ts` (`copilotConfirm` → register + refresh rail).
**Tests:** vitest — confirm path sets `scenarioId` and calls `loadSavedSims`.
**Effort:** S. **Risks:** low; mostly wiring.

### 7. Finish the view/flyTo family
**Goal:** the lower-value view actions: `focus_point` (fly to a landmark/lat-lng), timeline
`set_time` ("show the evening peak"), `recenter`/`tilt` voice.
**Approach:** `focus_point` — geocode a landmark via the existing `lib/search.ts` index → `fly` view.
`set_time` — classifier extracts a minute/period → `view{action:"time", minute}` → frontend
`setScrubber`. Add `set_time`/`recenter`/`tilt` to classifier intents.
**Files:** `copilot/classify.py` (intents), `copilot/planner.py` (view builders), `appStore.ts`
`applyView` (handle `time`/`recenter`/`tilt` — recenter/tilt already exist as store fns).
**Tests:** dispatch returns the right `view` per intent; applyView calls the right store fn.
**Effort:** S–M. **Risks:** landmark geocoding accuracy (reuse search.ts, fall back to "couldn't find").

---

## Tier 3 — Multimodal & memory

### 8. Transit-impact awareness
**Goal:** when a closure hits a streetcar/bus route, say so (multi-modal copilot).
**Approach:** check the affected `edge_ids`/road against GTFS route geometries (P08 `transit/`).
Surface as a `Warning` (severity warn) via `assess()` — so it composes with #3.
**Files:** `copilot/assess.py` (+transit check), `transit/` lookups.
**Tests:** closure on a route edge → a transit warning naming the route.
**Effort:** M. **Risks:** mapping edges→routes (spatial join) cost; precompute an index.

### 9. Multi-turn memory + chat history + new-chat
**Goal:** the copilot remembers the conversation; a "new chat" button; switchable history.
**Approach:** thread prior turns into the prompt context (cap to last K). Persist sessions in the
store (+ localStorage); "new chat" clears `copilotLog` + starts a session id. Classifier/plan get a
short rolling summary so "now close it" resolves the prior road.
**Files:** `appStore.ts` (session model, history, newChat), `CopilotPanel.tsx` (history UI + button),
`api/app.py` (`/route`/`/plan`/`/stream` accept optional `history`).
**Tests:** vitest — newChat resets log; history passed to the API; backend uses it.
**Effort:** M–L. **Risks:** scope creep; keep history bounded; classification must stay stateless-safe.

---

## Tier 4 — Quality & ship

### 10. Tests
- **CopilotPanel component test** (vitest + jsdom — note: no testing-library installed; render via the
  store like `copilotRouting.test.ts`): mode badge, confirm, stop, the single loader label, chips.
- **Playwright e2e** of route→plan→confirm→revert across modes — a CI gate replacing manual click-through.
- **Golden-prompt regression** — rehearsed prompts through a mocked classifier+model, snapshot the
  structured `ToolCall` (intent, ops, view, warnings). Catches routing drift.
**Files:** `frontend/tests/*`, `tests/test_copilot_golden.py`.
**Effort:** M.

### 11. Push branch + open PR
**Goal:** get `feat/copilot-routing` (routing + flyTo + de-hardcode + loader/chips) reviewed.
**Approach:** push; open PR → main; ensure CI green (lint + tests). Bundle the spec docs.
**Effort:** S. **Risks:** main may have drifted (roommate) → rebase, not merge.

---

## Suggested sequence
0. **Tier 0** (0a→0b→0c) — fix the broken/duplicate apply + preview + wording FIRST (correctness) →
1. **#1 demand_surge** (capability the UI already pretends to have) →
2. **#5 keep-alive** + **#6 confirm-saves** (quick, high-felt-quality) →
3. **#2 explain/inspect** (data already there) →
4. **#3 /assess warning system** (coordinate w/ roommate; folds in #8 transit) →
5. **#4 agent SSE** → **#7 view family tail** → **#9 memory** →
6. **#10 tests** alongside each, **#11 PR** when a coherent slice is done.

## Cross-cutting
- Every new intent → add to `classify.Intent` **and** the classifier system prompt **and** a
  `_dispatch` branch **and** a test. Keep "model names, code resolves."
- New user-facing text must be data-derived or model-generated — no rehearsed strings (de-hardcode rule).
- `warnings[]` + `view` are already on the contract; new handlers populate them, don't reshape.
