# P09 — Copilot: warn-don't-block UX + de-hardcode + baseline perf (plan)

Research + design for: (1) replace hard refusals with **colored warnings the user can override**,
(2) remove **all hardcoded copilot text**, (3) fix the **133 s baseline** blocker. Plan only — no code yet.

## Research findings

### A. Baseline perf (the blocker)
- Measured: `state.baseline()` = **133 s** on the merged **81,669-edge** graph (graph load alone 4.6 s).
- Everything that compares to baseline blocks on it: congestion query, `/copilot/confirm`, agent scratch sims → all time out on first use. Startup pre-warm runs it but takes 133 s; concurrent calls double-compute.
- A precomputed **`data/simulation/baseline_result.json` (24 MB)** exists (main dumps it via `export_results.py`), but **nothing loads it back**. Its shape is serialized **`{time_context, weather, summary, calibration_scale, edges, nodes, od_matrix_sample, iterations}`** — i.e. edge/node *lists* + summary, **not** a live `graph` object. So loading it needs a **rehydration step** (edges/nodes → `networkx` graph) for `compare_simulations` (`baseline_result["graph"]`) and `_answer_congestion` (`graph.edges(data=True)`). No loader exists yet.

### B. Warnings UI already exists (reuse it)
- `RightDock → WarningsBody` renders `store.warnings` as **`.warn-row.{severity}`** blocks with icons + `ref`. Severity palette in CSS: `danger`=red (`--c-sev`), `warn`=amber, default=orange (`--c-heavy`), `ok`=green (`--c-free`).
- `Warning = {id, severity: info|warn|danger, title, detail, ref?}`.
- The copilot's blocked path **already pushes to `store.warnings`** (wired in the merge). So the colored-block surface is built — we just change *what* feeds it and add inline blocks in the chat.

### C. Hardcoded copilot text (to remove)
`planner.py`: `_HERO_STEPS`, `_HERO_CITATIONS`, `_hero_call` rationale, **`_blocked_call` rationale** ("eastbound-contraflow…", shown for *any* blocked corridor), `_generic_preview` text, optimizer "no action" line.

## Proposed design

### 1. Warn, don't block
- **Remove the hard-refusal path** (`tool="refuse"` / `blocked`). The copilot *always proposes*; constraint conflicts attach as **warnings** on the ToolCall and the user can **Confirm anyway** (informed consent — preview-before-apply already covers safety).
- Reclassify the existing data-backed checks by severity (no new data):
  - fire-route / transit-priority corridor → **`danger`** (red)
  - major-arterial diversion / residential infiltration → **`warn`** (amber)
- ToolCall gains `warnings: [{severity, title, detail, ref}]` (drop `blocked`). `check_request` + `advisories` merge into one **`assess(prompt, interventions, state) -> [Warning]`** (severity-tagged, never refuses).

### 2. Colored warnings, integrated
- **In the chat bubble:** render the plan's warnings as inline colored blocks reusing `.warn-row.{severity}` under the rationale.
- **In the RightDock Warnings panel:** also push them (already wired) so copilot conflicts sit alongside bylaw/risk flags.
- **Confirm button:** when any `danger` warning is present, label it **"Confirm anyway"** with a red accent (still allowed).

### 3. De-hardcode the copilot
- Delete `_blocked_call` (gone with hard-block).
- **Hero:** drop the canned steps/citations/rationale. The *intervention resolution* can stay deterministic (resolve.py / name→edges), but the **narration comes from the live model** (or is omitted) — no rehearsed prose. *(Demo-determinism tradeoff — see decision 1.)*
- `_generic_preview` canned text → non-actionable input already auto-routes to a live **Chat** reply; drop the canned string.
- Citations only from RAG/real data (already the live-plan rule).

### 4. Baseline perf
- **Recommended:** add a **rehydration loader** — `state.baseline()` loads `baseline_result.json` (rebuild a `MultiDiGraph` from `nodes`/`edges`, keep `summary`) when present, else compute. Makes congestion/confirm/agent **instant**. Medium effort; must match edge-attr names (`pressure`, `load`, `status`, `road_name`, `edge_id`).
- Alt: lock + pre-warm (one 133 s compute at boot, then instant) — simplest, no rehydration risk, but ~2 min warm-up.

## Single source of truth: RAG+Nemotron warning system (clickops ⇄ copilot)

Decision (2026-05-31): the closure warning system is **one module** that both manual
block-placement (clickops) and the copilot call — grounded in the bylaw RAG (Ch. 937
Temporary Closing of Highways, Ch. 743 Use of Streets, Ch. 880 Fire Routes, Ch. 886, 950).
The model reasons over the *retrieved bylaw text*, so warnings cite real sections — not
invented, not hardcoded.

```
 manual closure (placeAt/applyEdits) ─┐
 copilot closure (plan/agent/confirm) ─┤
                                       ▼
                       POST /assess  { interventions }
                                       │
                 ┌─────────────────────┼───────────────────────────┐
                 ▼                     ▼                            ▼
        resolve affected roads   RAG retrieve relevant       Nemotron assess
        (resolve.py: edge→        bylaw sections for the      (constrained JSON):
        road_name/class/          closure type + roads        rank severity, cite the
        fire-route/transit)       (937 permit/conditions,     retrieved §s, explain
                 │                 880 fire route, 743         │
                 └──── deterministic floor ───────────────────┘
                       (fire-route/transit = danger, always-on, instant)
                                       ▼
                       Warning[] { severity, title, detail, ref }
                                       ▼
                 store.warnings → RightDock panel (colored .warn-row)
                 + copilot also renders them inline in the chat bubble
```

- **Backend `copilot/assess.py` + `POST /assess`** — the SSOT. `assess(interventions, state)`:
  1. resolve affected roads (resolve.py) → names/class/fire-route/transit flags;
  2. **deterministic floor** (fire-route/transit/major-arterial) → instant severity-coded warnings;
  3. **RAG-grounded Nemotron** pass → enrich with the cited bylaw §s + a plain-English rationale;
  4. merge/dedupe → `Warning[]`. Never refuses (warn-don't-block).
- **Both surfaces call it:** clickops `placeAt`/`applyEdits` → `/assess` on the placed closure; copilot
  `plan`/`agent` → same `/assess` on proposed interventions. One warnings store, one colored UI.
- **Perf:** show the deterministic floor instantly; the Nemotron-grounded detail fills in async (it's
  read-only, no baseline needed). Cache per (edge-set) so repeated placements don't re-call the model.
- Replaces the hard-refuse path; `check_request`/`advisories` fold into `assess()`.

## Open decisions
1. **Hero**: fully live (drop all rehearsed prose; resolution may stay deterministic) — accept demo-determinism risk? Or keep a *model-narrated* deterministic hero?
2. **Baseline**: build the rehydration loader (recommended) vs lock+warm?
3. **Warn-only even for fire routes?** You said warn-only / no hard blocks — confirming even a fire-route closure becomes a red **warning the user can override** (legally serious IRL, but matches "warn, don't block").
