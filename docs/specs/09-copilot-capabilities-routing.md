# P09 — Copilot: capability taxonomy + routing redesign (plan)

Defines (1) the **authoritative set of capabilities** the copilot agent may perform, and
(2) a **single-classifier routing** model to replace the three disagreeing routers we have
today. Plan only — no code yet. Pairs with `09-copilot-constraints-ux.md` (warnings) and
`09-copilot-flyto-and-actions.md` (camera/view actions); all three change the same response
contract, so settle the contract once.

## Part 1 — Routing today is misfiring

### Three independent routers that disagree

| Layer | Where | Rule |
|---|---|---|
| 1. Frontend regex | `copilotAsk` `appStore.ts:568` | `isQuestion` → **chat**, else **plan**; `deepMode` overrides → **agent** |
| 2. Backend keyword cascade | `plan_intervention` `planner.py:276–306` | `check_request` → `ease/gridlock` → `optimize` → `_COMMAND_HINTS` → `plan()` |
| 3. Backend Nemotron classifier | `_try_command` → `_INTENT_SCHEMA` `planner.py:214` | classifies intent + extracts names — **but only runs if a `_COMMAND_HINTS` keyword is present** |

Each layer re-guesses "what does the user want?" with a different heuristic. They disagree,
so the *same intent routes to different code paths depending on punctuation and vocabulary.*

### Misroute evidence (traced through layers 1+2)

| Prompt | Routes to | Should be | Bug |
|---|---|---|---|
| `where is congestion worst?` | chat (free stream) | `query_congestion` (reads baseline) | grounded data path **unreachable** at this phrasing |
| `what's the busiest road?` | chat | `query_congestion` | hallucination-prone chat instead of real numbers |
| `Can you close King St?` | chat | `close_road` | a command gets *talked about*, not staged |
| `close King between Bathurst and Spadina?` | chat | `close_segment` | trailing `?` sends a command to chat |
| `show me the Gardiner` | plan → `plan()` | a **view** action | tries to invent an intervention; no view capability exists |
| `take Yonge offline` | plan → `plan()` freeform | `close_road` | no hint word → skips the clean resolve path |
| `shut the DVP` | plan → `_try_command` | `close_road` | *same intent as the row above, different path* |
| `worst congestion right now` | plan → `query_congestion` ✓ | ✓ | works — but add `?` and it breaks |

Root problems:
- The grounded `query_congestion` reader is **only reachable** when the user avoids question
  words *and* includes a hint keyword. Natural questions miss it entirely.
- `_try_command` already asks the model to classify intent — but a brittle keyword gate
  decides whether we even call it. We keyword-match *to decide whether to do the real
  classification.*
- `deepMode` is wired as a **router** (separate `/agent` path) when it should be a **depth**
  hint (how many investigation steps are allowed).

## Part 2 — Proposed routing: one classifier

```
                      USER MESSAGE
                          │
            ┌─────────────▼──────────────┐
            │  classify()  — ONE Nemotron │   constrained JSON:
            │  intent pass, ungated       │   { intent, entities{road, from, to,
            │  (replaces FE regex +       │     area, time, scenario_name},
            │   BE keyword cascade)       │     read_only, depth_hint }
            └─────────────┬──────────────┘
                          │  dispatch by intent family
    ┌──────────┬──────────┼───────────┬─────────────┬─────────────┐
    ▼          ▼          ▼           ▼             ▼             ▼
  QUERY      PLAN       VIEW      SCENARIO       AGENT          CHAT
 (read)   (mutate→    (camera/   (save/load/   (compound:     (small talk /
          confirm)    time/3D)   compare)      investigate→   open question
                                                propose)      no data)
    │          │          │           │             │             │
 resolve.py / baseline reader / camera target / store ops / run_agent / stream
                          │
                  unified response { answer, interventions[], warnings[], view? }
```

- **`deepMode` → `depth_hint`.** Off = single-shot dispatch; On = the AGENT family gets more
  `max_steps`. It no longer forks the code path — a compound request can trigger the agent on
  its own merits.
- **Delete** the frontend `isQuestion` regex and the backend `_COMMAND_HINTS` cascade. The
  classifier is the only intent authority; `resolve.py` / the baseline reader / camera targets
  do the deterministic work after.
- Keep the **"model names, code resolves"** principle: the classifier extracts *entities only*
  (road/intersection/area/time names); never edge_ids.

## Part 3 — Capability taxonomy (authoritative)

Legend — **Surface**: `reply` (text, no confirm) · `plan` (staged, needs Confirm) · `view`
(camera/UI side-effect, no confirm). **Status**: ✓ exists · ◐ partial · ✗ to build.

### A. Query (read-only, no confirm)
| Capability | Trigger examples | Resolves via | Surface | Status |
|---|---|---|---|---|
| `query_congestion` | "where's it worst", "busiest road" | baseline reader (`_answer_congestion`) | reply (+`view` fit) | ✓ |
| `explain_congestion` | "why is Lake Shore jammed" | OD/flow read + RAG | reply | ◐ (`explain.py` does *compare* only) |
| `inspect_road` | "stats for the Gardiner", "how loaded is King" | graph read by name | reply | ✗ |
| `compare_scenarios` | "how does this compare to my saved plan" | `store.compare` | reply (+result card) | ◐ (confirm-only today) |
| `retrieve_policy` | "what does the bylaw say about closures" | RAG | reply | ✓ (agent tool) |

### B. Plan / propose (mutating → requires confirm)
| Capability | Trigger examples | Resolves via | Surface | Status |
|---|---|---|---|---|
| `close_road` / `reopen_road` | "close all of Yonge", "take the DVP offline" | `road_edges_by_name` | plan | ✓ |
| `close_segment` / `reopen_segment` | "close King between Bathurst and Spadina" | `road_between` | plan | ✓ |
| `change_capacity` | "halve capacity on Lake Shore eastbound" | `candidate_edges` + `plan()` | plan | ✓ |
| `demand_surge` / `relief` | "simulate a surge out of BMO Field" | **needs backend op** | plan | ✗ (frontend-only; not in `InterventionType`) |
| `optimize` | "recommend the best plan" | P10 `propose` | plan | ✓ |
| `mitigate_area` | "ease congestion near BMO Field" | resolve area → optimize/propose | plan | ◐ (hardcoded `_hero_*` — de-hardcode) |

### C. View / presentation (read-only, no confirm) — the flyTo family
| Capability | Trigger examples | Resolves via | Surface | Status |
|---|---|---|---|---|
| `focus_road` | "show me the Gardiner", "zoom to King St" | name → bbox (frontend search index) | view (`fitToBounds`+`selectRoad`) | ✗ |
| `focus_point` | "fly to BMO Field" | geocode/landmark → lng/lat | view (`flyToLocation`) | ✗ |
| `recenter` / `tilt_3d` | "reset the view", "show me 3D" | — | view (`recenter`/`toggleTilt`) | ✗ (store fns exist, unwired) |
| `auto_focus_on_plan` | *(implicit on every staged plan)* | intervention edge_ids → bbox | view | ✗ (biggest cheap win) |

### D. Timeline (read-only, no confirm)
| Capability | Trigger examples | Resolves via | Surface | Status |
|---|---|---|---|---|
| `set_time` | "show the evening peak", "what about 8am" | minute parse | view (`setScrubber`) | ✗ |
| `play` / `pause` / `speed` | "play it", "2× speed" | — | view (`setPlaying`/`setSpeed`) | ✗ |
| `set_season` | "what about a winter day" | day-of-year | view (`setDayOfYear`) | ✗ |

### E. Scenario lifecycle (stateful, not sim-mutating)
| Capability | Trigger examples | Resolves via | Surface | Status |
|---|---|---|---|---|
| `save_scenario` | "save this as 'Game-day plan'" | `saveCurrent` | view (confirm name) | ✗ |
| `load_scenario` | "load my earlier plan" | `selectSavedSim` | view | ✗ |
| `revert` | "undo that", "back to baseline" | `copilotRevert` | view | ✓ (button, not intent) |
| `new_sim` | "start fresh" | `newSim` | view | ✗ |

### F. Conversational
| Capability | Trigger examples | Surface | Status |
|---|---|---|---|
| `answer` | greetings, "what can you do", open questions | reply (stream) | ✓ |

### Out of scope (do NOT expose to the agent)
- Direct sim mutation without the confirm gate (always preview-first).
- `add_edge` / `remove_edge` / `close_node` from free text (geometry-creating; clickops only).
- Theme/density/dock toggles (cosmetic; not worth the routing surface).

## Part 4 — Unified response contract

One shape carries data + warnings + view so the three in-flight workstreams don't re-edit it:

```ts
interface CopilotResponse {
  intent: string;                 // classified capability
  answer: string;                 // user-facing text (reply families)
  interventions: Intervention[];  // plan families (staged, confirm-gated)
  warnings: Warning[];            // from /assess (warn-don't-block) — see constraints-ux spec
  view?: ViewDirective;           // focus/time/3D — frontend executes, no confirm
  citations: Citation[];
  requires_user_confirmation: boolean;
}
type ViewDirective =
  | { action: "fit";   road_name?: string; edge_ids?: string[] }
  | { action: "fly";   lng: number; lat: number; zoom?: number }
  | { action: "select"; road_name?: string }
  | { action: "recenter" } | { action: "tilt"; on: boolean }
  | { action: "time";  minute?: number; play?: boolean; day_of_year?: number };
```

## Part 5 — Build order (gated on the contract)

1. **Contract first** — add `warnings[]` + `view?` to `ToolCall`/`CopilotResponse`/agent result.
2. **Single classifier** — `classify()` replaces FE `isQuestion` + BE `_COMMAND_HINTS`; `deepMode`→depth.
3. **View family** — auto-focus on staged plans (frontend-only, derive bbox from edge_ids) →
   `focus_road`/`focus_point` → wire `query_congestion` to also emit `view{fit}`.
4. **Fill query gaps** — `explain_congestion`, `inspect_road`, chat-reachable `compare_scenarios`.
5. **Timeline + scenario** families.
6. **`demand_surge` backend op** (currently frontend-only; add to `InterventionType` + sim).
7. De-hardcode (`_hero_*`/`_blocked_call`/`_generic_preview`) — folds into the new dispatch.

## Open questions
1. **Classifier latency** — one always-on model call per message (vs today's keyword skip). On
   Spark this is ~hundreds of ms; acceptable? Or keep a fast-path regex *only* for obvious
   small talk to skip the call?
2. **Confidence threshold** — when `classify()` is unsure between two intents, fall back to
   `answer` (ask a clarifying question) or to the agent loop?
3. **Should `compare_scenarios` / scenario-load be agent-reachable**, or stay manual-only UI?
4. **View actions on every plan** — always auto-focus, or only when the user didn't just
   manually move the camera (avoid yanking their view)?
