# P09 Copilot — Roadmap (post-`main` merge)

Companion to `09-copilot.md`. Captures the agreed TODO backlog after merging `origin/main`
(`c959884`) into the copilot branch. Grouped by theme, prioritized at the end.

## Where we are (post-merge)
- **Copilot (ours) is the live one** — `main`'s was the old scaffold; the merge kept ours.
- **3 modes** via `/copilot/{plan,stream,agent}` + `/copilot/confirm` (apply→run→compare→explain) +
  `/copilot/debug` console. Frontend: mode selector, streaming, collapsible reasoning trace, latency HUD,
  stop, per-reply badge.
- **From `main` we now also have:** richer `Intervention` type (adds `demand_surge`, `add_edge` fields),
  Edit-mode UI (corridor **closure** + **demand surge/relief**), `api/graph.ts` helpers
  (`corridorBetween`, `nearestNode`, `streetsByDirection`…), scenario CRUD, the **warnings panel**, and the
  **GNN demand model**.
- Backend intervention vocabulary (both branches): `close_edge, reopen_edge, remove_edge, change_capacity,
  close_node, add_edge`. **`demand_surge` is frontend-only — no backend support yet.**

---

## A. UX: consolidate the 3 modes into one smart entry  *(design decision)*
**Goal:** the planner just types; we route. Keep manual control for demo determinism.

**Decision:** add an **"Auto" mode (new default)** alongside the explicit Plan / Chat / Agent (which stay as
overrides + power the debug console). Auto does **one lightweight intent classification**, then dispatches:
- *informational / question* → **chat** (stream)
- *clear single action* ("close X", "reduce capacity on Y") → **plan** (→ confirm)
- *complex / multi-step / "figure it out and check"* → **agent** loop

**Why a classifier, not "run chat then escalate":** chat-first-then-redo means two model calls for every
action (slow). A single classify→dispatch is one hop. Classifier options:
1. **Cheap heuristic** (verbs/keywords + "?") — deterministic, zero latency, brittle on phrasing.
2. **Fast LLM classify** (`nemotron-mini`/one constrained call) returning `{mode}` — smarter, ~sub-second.
Plan: heuristic first pass, LLM classify as the fallback/upgrade. Show the chosen mode as the reply badge so
the routing is transparent (and correctable via the explicit tabs).

- [ ] Backend `/copilot/route` (or a `mode:"auto"` arg) → returns chosen mode (+ optionally runs it)
- [ ] Frontend: "Auto" tab as default; badge already shows the resolved mode
- [ ] Keep explicit Plan/Chat/Agent as overrides

## B. Revamp confirm + wire it to the twin  *(design decision)*
**Problem:** `/copilot/confirm` applies→runs→compares→explains and posts a chat line, but the **map doesn't
repaint** with the post-intervention result, and the confirmed scenario isn't reflected in `main`'s
Sim/saved-scenario UI.

- [ ] After confirm, fetch `/scenarios/{id}/records` → `writeRecords` + bump `pressureSeq` so deck.gl recolors
      (show the *after* state on the twin)
- [ ] Register the confirmed scenario in `main`'s `savedSims`/scenario model so it's selectable + revertable
- [ ] Render the result as a **metric card** (Δ pressure, high-risk/severe deltas, most-impacted roads), not
      just a chat sentence
- [ ] "Discard / revert to baseline" affordance after apply
- [ ] Blocked path now pushes to the **warnings panel** (done in merge) — verify it surfaces in the UI

## C. New agent capabilities (give the agent what Edit-mode can do + read the twin)
- [ ] **Backend `demand_surge` intervention** — generalize `demo/wc_surge.py` into a real op (inject/reduce OD
      demand at a node/area + direction). Unlocks "add congestion near BMO" for the agent **and** the Edit UI
      (currently unbacked). Add to `graph/mutations.py` + `api/schemas.py` `InterventionType`.
- [x] **Corridor closure** (from PR #31 resolve.py: road_edges_by_name / road_between) — resolve "close King between Bathurst and Jarvis" → edge list
      (backend equivalent of `corridorBetween`), then N× `close_edge`.
- [~] **Diagnose / explain tools** — query_congestion done (PR #31); explain_edge still TODO — read the sim back: `diagnose_network` (top congested corridors by
      pressure/risk), `explain_edge` (why X is congested — upstream OD + capacity). Data already computed.
- [ ] **Transit-impact awareness** — check intervention edges against GTFS routes (P08); report streetcar/bus
      effect. Makes the copilot multi-modal.
- [ ] **Event & demand modeling** — generalize the WC surge: "model a concert at Scotiabank Arena at 10pm";
      scale OD for growth; time-of-day/weather already feed the sim.
- [ ] **Objective-driven optimize** — let the agent set the P10 optimizer's objective/budget from NL
      ("cheapest plan to cut egress 20%", "minimize delay, ≤2 closures"). Needs a small per-op cost model.
- [ ] **Cite GNN-predicted demand** in explanations (main's GNN model).

## D. Optimizations / cleanups
- [ ] Agent **step repetition** — it re-runs `simulate`; dedup identical (tool,args) + nudge to use prior
      observations. Consider streaming agent steps live (SSE) instead of a ~12s freeze.
- [ ] **Unify the frontend `Intervention` type** — one source (done in merge: dropped the duplicate; keep it so).
- [ ] **Model keep-alive ping loop** so the model never goes cold mid-demo (kills the ~11s first-call stall).
- [ ] Spoken-language summary (TTS) of the result — the hackathon brief calls this out.
- [ ] Copilot call logging (prompt/mode/latency/tool-calls) + a latency histogram for the demo.

## E. Tests (thin on UI + e2e today)
- [ ] **Component tests** (vitest + testing-library) for `CopilotPanel` — mode switch, confirm, stop, streaming render.
- [ ] **Automated Playwright e2e** of the 3 (4 with Auto) modes — a CI gate (replaces my manual click-through).
- [ ] **Golden-prompt regression** — rehearsed prompts through a mocked model, snapshot the structured output.
- [ ] Backend edge cases: abort mid-stream, concurrent requests, model-output fuzzing, demand_surge op.

---

## Suggested order
1. **B. Confirm revamp + map wiring** — the apply loop is the headline; it must visibly update the twin.
2. **C. `demand_surge` backend + corridor closure** — the capabilities you asked for ("add congestion / block corridor").
3. **C. diagnose/explain + transit-impact** — high value, data already there.
4. **A. Auto mode** — UX polish once the handlers are solid.
5. **D/E. optimizations + tests** — durability pass.
