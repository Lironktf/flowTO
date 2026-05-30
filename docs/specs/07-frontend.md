# P07 — Frontend: deck.gl + MapLibre planner instrument

| | |
|---|---|
| **Priority** | Core |
| **Depends on** | P06 |
| **Owner hint** | Frontend owner |
| **Status** | not started |
| **Note** | **The Claude design drop has LANDED at `design/`** (high-fidelity HTML/CSS/JS prototype + tokens + full layout/state spec in `design/README.md`). This spec covers *integration architecture*; recreate `design/` faithfully in React+Vite+TS. **Do NOT port the prototype's 2-D canvas corridor renderer — use deck.gl** (the prototype says so explicitly). |

## Goal
A React + Vite + TypeScript app that renders 3-D Toronto with congestion on the road network, lets a planner pick
a time slice, **select edges → choose intervention → preview → apply**, and see before/after metrics — driven by
P06's REST + binary WS tick stream, with tick data kept **out of React** for 60fps.

**Why / rubric tie-in:** Usability + Insight quality. Decision clarity over spectacle: the planner sees *which*
corridor is affected and *why* an action is/isn't allowed.

## Current state
- None (empty `frontend/` placeholder from P00). The committed `docs/explainer.html` is a concept piece, not the app.

## Target state
- Vite+TS app: interleaved `MapboxOverlay` on MapLibre (Protomaps/PMTiles grayscale basemap), the layer set from `research/06`, the panel layout (map-dominant; left intervention drawer; right metrics+copilot; bottom time scrubber), Zustand for human-cadence app state, typed-array tick store driven imperatively. **Design tokens + UI components come from the Claude design drop**; this phase builds the data/interaction plumbing and the component *contracts*.

### In scope
Map + layers, WS/REST client, tick→layer plumbing, scrubber, edge selection, intervention create/preview/apply flow, before/after panel wiring, copilot/optimizer panel shells. Slots for the design drop.
### Out of scope
Final visual styling/tokens (design drop). Transit vehicle animation lands with P08 (TripsLayer). Backend logic (P06).

## Design / implementation plan
**Visual source of truth = `design/`** (read `design/README.md` first). It is high-fidelity and intentional:
recreate it pixel-faithfully within the component system. It provides: **tokens** (light "drafting paper" +
dark "ops" — `--paper/--surface/--ink/--cobalt/--hair`…), the **congestion ramp** (exact stops + intensity/dark
remap), **typography** (Fraunces / Public Sans / IBM Plex Mono with role + size rules), spacing/radius/shadow +
the blueprint-grid panel treatment, the full **floating-panel layout** (top bar, left interventions, right
metrics, bottom-right copilot, centered scrubber, perf strip, legend, recompute overlay, first-run, tweaks), the
**6-state machine** (first-run → baseline → recomputing(HERO) → surge → mitigated → constraint-blocked) with exact
visual treatments, and inline SVG icons. `design/flowto.html` runs every state live; `design/js/{data,ui,map,app}.js`
hold the content + behavior. **Use deck.gl, not the prototype's 2-D canvas corridor renderer** (the README says so).
Map specifics + per-tick update technique still come from **`research/06-frontend-deckgl-ux.md`**.

1. **Scaffold** — Vite + React + TS; `@deck.gl/{core,layers,geo-layers,mapbox,aggregation-layers}`, `maplibre-gl@5`, `react-map-gl/maplibre`, `pmtiles`, `zustand`, Radix + Tailwind (the design drop owns the theme).
2. **Map shell** (`components/MapCanvas.tsx`) — `<Map mapLib={maplibregl}>` + interleaved `MapboxOverlay` via `useControl`; PMTiles protocol; `beforeId` z-order (roads/heatmap below labels, closures above).
3. **Layers** (`layers/`) — `roads` (MVTLayer citywide / PathLayer working-set, per-tick `updateTriggers:{getColor:tickSeq}` or binary attributes), `massing` (extruded GeoJsonLayer, neutral grey), `closures` (PathLayer corridor + IconLayer), `hexPressure` (HexagonLayer aggregation toggle), `transit` (TripsLayer — wired in P08).
4. **Tick store** (`state/tickStore.ts`) — module-level typed arrays (`pressure/load/speed: Float32Array`, `closure: Uint8Array`) keyed by edge index; WS `onmessage` decodes binary → writes in place (no `setState`); single throttled rAF → `overlay.setProps`/binary attribute upload; bump `tickSeq`.
5. **App state** (`state/appStore.ts`, Zustand) — scenario, selected `edge_id` set, active intervention, preview state, scrubber time, layer toggles, before/after mode. Panels subscribe via selectors.
6. **Interaction flow** — select (click/lasso) → contextual popover (action + params) → `POST /preview` → ghost/diff overlay + provisional deltas marked "PREVIEW" → `POST apply` → new WS stream; undo + intervention list.
7. **Panels** (component contracts; design drop styles them): `TimeScrubber` (owns `currentTime` for roads snapshot + transit), `InterventionDrawer`, `BeforeAfterPanel` (paired numbers + signed deltas, tabular figures), `CopilotPanel`, `DebugPanel` (FPS/tick-lag, dev-only).
8. **API client** (`api/client.ts`) — typed REST (scenario CRUD/run/compare/preview) + WS connect/decode; reconnect keeps last snapshot.

## Data / models / sources
`research/06` (interleaved MapboxOverlay, PMTiles, layer-by-layer props, tick-data-out-of-React pattern, Radix/shadcn). P06 schemas (generate TS types from the OpenAPI). **`design/`** is the visual source of truth — `design/README.md` (tokens, layout, 6 states, exact metrics), `design/flowto.html` (live reference), `design/js/data.js` (corridors, scenarios, copilot scripts + bylaw citations, before/after metrics, blast-radius corridor lists — shared with P12/P09).

## Files to create / modify
**Create:** `frontend/` (Vite app) — `src/components/{MapCanvas,TimeScrubber,InterventionDrawer,BeforeAfterPanel,CopilotPanel,DebugPanel}.tsx`, `src/layers/*.ts`, `src/state/{tickStore,appStore}.ts`, `src/api/client.ts`, `src/styles/tokens.css` (design-drop target), `vite.config.ts`, `package.json`; `frontend/tests/*` (Vitest); `scripts/run_frontend.sh`.
**Modify:** none in backend (consumes P06).

## Test-driven design
- **Unit (Vitest):** binary frame decoder → typed arrays (round-trip a packed buffer); `pressureRamp(v)` color mapping green→amber→red boundaries; `tickStore` write doesn't trigger React renders (spy).
- **Interaction:** selecting edges updates `appStore.selectedEdges`; preview sets preview state without committing; apply calls the right endpoint (mock client).
- **Smoke/E2E (Playwright, optional):** load app → map renders → scrub time → roads recolor → create closure → before/after panel shows deltas.

## Verification
**Local:** `scripts/run_frontend.sh` (Vite dev) against a local P06 API → map loads with PMTiles basemap, roads colored by pressure, scrubber recolors, closure flow previews + applies, before/after updates; FPS stays smooth while streaming (DebugPanel).
**On Spark:** point the frontend at the API running on the Spark (Tailscale tunnel); confirm the full on-device loop renders.

## Tasks
- [ ] T07.1 Vite+TS scaffold + deps + MapCanvas (interleaved overlay + PMTiles) — *1d*
- [ ] T07.2 Road + massing + closure + hex layers — *1d*
- [ ] T07.3 `tickStore` typed-array WS plumbing + imperative deck updates — *1d*
- [ ] T07.4 `appStore` + selection + intervention create/preview/apply flow — *1.5d*
- [ ] T07.5 Scrubber + BeforeAfter + Copilot/Debug panel shells (design-drop slots) — *1d*
- [ ] T07.6 API client (typed REST + WS) + tests — *0.5d*
- [ ] T07.7 Recreate `design/` faithfully: tokens (light+dark) → `styles/tokens.css`; Fraunces/Public Sans/IBM Plex Mono; the floating-panel layout + all 6 states from `design/README.md` + `design/flowto.html` — *1.5d*

## Risks / fallbacks
- **Design drop is in `design/`** (no longer a risk) → recreate it faithfully; if time-pressed, prioritize tokens + the panel layout + the recompute(HERO) + before/after states (the demo beats) over the tweaks panel/first-run polish.
- **Citywide road density jank** → MVT binary tiles + server-side LOD (P06) + density caps; demo on the downtown extent.
- **Re-render storms** → enforced typed-array/imperative pattern; DebugPanel surfaces regressions.
- **3D massing too heavy** → tile/generalize by zoom, `visibleMinZoom`; edge pressure is the priority, buildings are context.
