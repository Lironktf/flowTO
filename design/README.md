# Handoff: FlowTO — Live Digital Twin of Toronto (Planner Workspace)

## Overview
FlowTO is a 3-D, time-aware digital-twin workspace for city planners. It renders Toronto as a
map-first canvas and lets a planner simulate how traffic + transit flow, then apply interventions
(closures, lane reductions, temporary one-ways, signal retiming, demand surges) and watch the
network recompute in real time. An on-device **Nemotron** copilot turns plain-English requests
into validated, **preview-first** actions with cited bylaw constraints; an RL optimizer proposes
bylaw- and budget-valid plans.

The reference scenario is the **FIFA World Cup 2026 post-match egress** at Toronto Stadium
(BMO Field, Exhibition Place): ~45,000 people released over ~25 minutes, full-time ≈ 17:05,
Fri 12 Jun 2026.

## About the Design Files
The files in this bundle are **design references created in HTML/CSS/vanilla JS + a small React
island** — prototypes that show the intended look, copy, states, and behavior. They are **not
production code to copy directly.**

Your task is to **recreate this design in your real app** (you mentioned **React + Vite +
TypeScript**, with the map built on **deck.gl + MapLibre**), using your established patterns,
component library, and the actual road-network graph. Treat the HTML as the source of truth for
**visual language, layout, microcopy, and interaction states**, not for rendering technique.

> ⚠️ One important divergence: in this prototype the corridor network is drawn on a **plain 2-D
> `<canvas>` over MapLibre using `map.project()`**, because the deck.gl `MapboxOverlay` did not
> reliably redraw in the sandbox. **In your real app, use deck.gl** (`PathLayer` / `TripsLayer`
> for edges colored by pressure, `PolygonLayer`/`GeoJsonLayer` extrusions for buildings). The
> canvas approach here is a prototype workaround only — do not port it.

## Fidelity
**High-fidelity.** Final colors, typography, spacing, copy, and interaction states are all
intentional. Recreate the UI pixel-faithfully (within your component system). The map *content*
(building extrusions, road pressure ribbons) should be reproduced with deck.gl bound to your graph;
the *floating UI* (panels, telemetry, copilot, scrubber) should match exactly.

---

## Design Tokens

### Color — Light "drafting paper" (default)
| Token | Hex | Use |
|---|---|---|
| `--paper` | `#efeadd` | app / drafting-board background |
| `--paper-2` | `#e7e1d1` | deeper paper |
| `--surface` | `#faf8f1` | floating panels |
| `--surface-2` | `#f2eee3` | insets, tiles, chips |
| `--ink` | `#1b1a16` | primary near-black text |
| `--ink-2` | `#4f4b40` | secondary text |
| `--ink-3` | `#837d6e` | muted text / labels |
| `--hair` | `rgba(27,26,22,.13)` | hairline borders |
| `--blueprint` | `rgba(36,85,214,.10)` | faint grid lines on chrome |
| `--cobalt` | `#2455d6` | **THE TOOL** — single accent (selection, the planner's actions) |
| `--cobalt-ink` | `#1c46b4` | cobalt text/hover |
| `--cobalt-wash` | `rgba(36,85,214,.10)` | cobalt fill wash |
| `--cobalt-line` | `rgba(36,85,214,.34)` | cobalt borders |
| `--map-bg` | `#e9e3d4` | map fallback before tiles |

### Color — Dark "ops" mode
| Token | Hex |
|---|---|
| `--paper` | `#0d1014` · `--paper-2` `#0a0c10` |
| `--surface` | `#161b22` · `--surface-2` `#1d242d` |
| `--ink` | `#e9ecf1` · `--ink-2` `#aab2bf` · `--ink-3` `#707a88` |
| `--hair` | `rgba(233,236,241,.12)` |
| `--blueprint` | `rgba(120,160,255,.09)` |
| `--cobalt` | `#6f9bff` · `--cobalt-ink` `#9ab8ff` · `--cobalt-wash` `rgba(111,155,255,.14)` · `--cobalt-line` `rgba(111,155,255,.45)` |
| `--map-bg` | `#0b0e13` |
| Basemap | swap MapLibre style light↔dark (we used CARTO positron / dark-matter; use your tiles) |

### Congestion scale — the ONLY place color carries meaning
A green→amber→red ramp reserved exclusively for **edge pressure** (0 = free flow, 1 = gridlock).
Never reuse these hues for anything else. Linear interpolation between stops:

```
0.00 → rgb(31,157,87)    free    (green)
0.35 → rgb(138,175,31)   light
0.55 → rgb(224,162,26)   moderate (amber)
0.75 → rgb(224,112,27)   heavy   (orange)
1.00 → rgb(210,58,50)    severe  (red)
```
- **Intensity tweak**: remap pressure around the midpoint before lookup:
  `p' = clamp((p − 0.5) * intensity + 0.5, 0, 1)`, default `intensity = 1.0` (range 0.7–1.4).
- **Dark mode**: brighten each channel `c = min(255, round(c*1.18 + 18))`.

### Typography
Loaded from Google Fonts. Three families, strict roles:
- **Fraunces** (display serif, opsz, wght 400/500/600) — wordmark, panel titles, big metric numbers, first-run headline.
- **Public Sans** (civic sans, 400/450/500/600/700) — all UI body, labels, buttons.
- **IBM Plex Mono** (400/500/600) — all data: metrics units, telemetry, edge IDs, timestamps, eyebrows, badges. `font-variant-numeric: tabular-nums`.

Key sizes: panel title 16px Fraunces 600; eyebrow 10px mono uppercase tracking .14em; body 13px (compact 12px); metric value 22px Fraunces; big metric 22px; first-run headline 46px Fraunces. **Minimum body 12px.**

### Spacing / radius / shadow
- Radius: `--r: 12px` (panels), `--r-sm: 8px` (controls/tiles).
- Density tweak (`[data-density]`): comfortable → `--pad:16 --pad-sm:12 --row-gap:12 --fs-body:13 --fs-label:11`; compact → `11 / 8 / 8 / 12 / 10`.
- Shadow: `0 1px 2px rgba(27,26,22,.06), 0 8px 26px rgba(27,26,22,.11)`; large: `0 2px 6px …, 0 20px 54px rgba(27,26,22,.18)`.
- **Blueprint grid**: floating panels + the top bar carry a faint grid background — two layered linear-gradients of `--blueprint` at 22px pitch over `--surface`. Subtle, drafting-paper feel; never over the live map.
- Panels are **flat** (1px `--hair` border + soft shadow). No glassmorphism, no gradients.

---

## Layout (single screen — map-first)
Full-bleed map fills the viewport; restrained UI floats over it. Designed at **1440×900**.

| Region | Position | Size | Contents |
|---|---|---|---|
| **Top bar** | top, full width | h 54px | Wordmark `Flow` + cobalt `TO`; sub "DIGITAL TWIN · TORONTO"; active-scenario tag; right: status chip, recenter, theme toggle, Reset |
| **Left panel** | top 66, left 14 | w 318, max-h `100vh−82` | "Interventions": 5-tool palette (2-col grid), recommended-plan preview card, scenarios list |
| **Metrics panel** | top 66, right 14 | w 360, max-h `52vh−28` | "Before / After": hero delay metric + bar pair, 2×2 metric grid, constraint warning row |
| **Copilot panel** | bottom 14, right 14 | w 360, h 372 | "Copilot · Nemotron · on-device": message log, suggestion chips, text input |
| **Time scrubber** | bottom 14, centered | w `min(560, 100vw−760)` | clock (mono), 15-min ticks, congestion heat rail, keyframes (kickoff + full-time), play |
| **Legend** | bottom, centered, −58px above scrubber | auto | "Edge pressure" ramp free→gridlock |
| **Perf strip** | bottom 14, left 14 | auto | mono telemetry cells: Recompute · Affected subgraph · LLM latency · Frame rate (+sparkline) · Compute = "DGX Spark · GB10" |
| **Recompute overlay** | bottom-center, above scrubber | min-w 380 | spinner + title + progress bar + 5 step pips |
| **First-run** | full screen | — | eyebrow, Fraunces headline "A live digital twin of **Toronto**.", lede, 3 meta stats, "Load the twin" button, typed boot loadline |
| **Tweaks panel** | bottom-right (host-toggled) | w 280 | theme, density, building height, camera tilt, pressure intensity |

Markers on the map: **Toronto Stadium** pin (cobalt, always on); **5 numbered intervention markers** (cobalt badge 1–5 + type dot + label) shown only after a plan is applied.

---

## The Map (recreate with deck.gl + MapLibre)
- Camera: center ≈ `[-79.4163, 43.6362]`, zoom ~14.1, **pitch 52°, bearing −18°** (oblique 3-D).
- **Extruded buildings**: fill-extrusion from your building footprints; light `#ddd6c6` @ .72 opacity, dark `#1c2533` @ .82. Height = `render_height × extrudeMult` (tweak), fallback 12 m. Place below label symbols.
- **Corridor edges** = `PathLayer`/`TripsLayer` colored by the congestion ramp from each edge's current pressure; width by class (expressway > arterial > collector > local > transit). Transit lines (509/511) get a dashed overlay.
- **Blast-radius halo**: a wider, semi-transparent **cobalt** underlay beneath the affected edges (only when an event is active).
- Basemap retint to drafting-paper: background → `--paper`/`--map-bg`, water → `#dde6ee` (light) / `#0c1422` (dark).

### Corridor data model (see `js/data.js`)
Each corridor: `{ id, name, cls, lanes, base, surge, mit, path:[[lng,lat]…], transit?, local?, transitPriority? }`
where `base`/`surge`/`mit` are pressures (0–1) for the three network states. `blastRadius` is an array
of corridor ids that light up under the event. In production these come from your assignment model,
not hand-authored constants — the prototype values exist to drive the demo narrative.

---

## States & Behavior (state machine — see `js/app.js`)
Five states, each with explicit visual treatment:

1. **First-run / empty** — full-screen drafting-paper splash; typed boot lines; "Load the twin" initializes the map, then → baseline.
2. **Baseline / nominal** — calm network (mostly green/amber), status chip green "Baseline · nominal", metrics panel shows "Network nominal" empty hint, perf idle (recompute 12 ms, subgraph 0, LLM "—", 60 fps).
3. **Recomputing (HERO)** — triggered by any intervention/copilot action or the scrubber crossing full-time. Shows the recompute overlay: progress 0→100% across **5 steps** ("Demand model → Trip assignment → Edge pressure → Bylaw check → Render"), status chip pulses cobalt, and the **perf strip animates live** (recompute latency counts to ~84 ms, affected subgraph fills to 1,284 edges / 612 nodes, LLM latency ~312 ms appears at the "Bylaw check" step, fps dips to ~57 then recovers to 60). Duration ~1.7–1.85 s.
4. **Scenario applied — surge** — corridors animate to **red**, cobalt blast-radius halo on, status red "Post-match surge · gridlock", before/after = "baseline → event" with worsening (red ↑) deltas, warning row flags 34% local-road infiltration.
5. **Scenario applied — mitigated** — after applying the plan, corridors recolor **red→green/amber**, 5 numbered action markers appear, status green "Mitigated · plan applied", before/after = "event → mitigated" with improving (green ↓) deltas, green warning row "Plan valid. No hard-constraint conflicts…".
6. **Constraint-blocked** — an invalid request (e.g. "close Lake Shore both ways") is **refused**: status amber "Action blocked · bylaw conflict", copilot explains the two hard-constraint breaches with citations, **network is not changed**.

### Before/After metrics (exact reference values)
| Metric | base | surge | mitigated | unit |
|---|---|---|---|---|
| Total network delay | 1,240 | 4,180 | 2,590 | veh·h |
| Mean travel time | 11.4 | 28.7 | 17.9 | min |
| 95th-pct travel time | 19.2 | 62.5 | 34.1 | min |
| Congested edges | 14 | 41 | 22 | edges |
| Local-road infiltration | 6 | 34 | 10 | % |

Delta = % vs. the comparison reference (surge vs base; mitigated vs surge). Lower is better → negative delta is green/"good", positive is red/"bad". Arrows ↑/↓.

### Copilot (Nemotron, on-device) — preview-first, cited
- Plain-English input + 3 suggestion chips. Typing indicator (3 bouncing dots) before each reply.
- **Hero request** "Ease post-match gridlock near BMO Field without breaking bylaws." → models the event, replies with a 3-step plan, **cites constraints**, then reveals the preview card. Citations shown as `§ <code> — <note>`:
  - *Toronto Municipal Code Ch. 950* — temporary traffic regulation under an approved event TMP
  - *King St Transit Priority Corridor* — through-traffic restriction preserved
  - *Toronto Municipal Code Ch. 880* — fire-route / emergency access lanes maintained
  - *AODA 2005* — accessible pedestrian route on Princes' Blvd retained
- **Blocked request** "Just close Lake Shore both ways." → refuses, cites Ch. 880 (fire route) + TTC streetcar-replacement lane, offers the contraflow alternative. (Full scripts in `js/data.js` → `copilotHero`, `copilotBlocked`.)

### Recommended plan (preview card + applied actions)
3 plan steps (contraflow on Lake Shore Blvd W, signal retiming at Dufferin & Strachan, close Princes' Blvd + hold 509/511 priority) with **Apply & recompute** / **Discard**. Applying → recompute → mitigated state + 5 staged markers.

### Time scrubber
14:00–20:00, 15-min steps; day-of-week label "FRI · 12 JUN 2026"; kickoff 15:00 and full-time 17:05 keyframes; congestion heat gradient along the rail. **Play** animates the matchday; crossing full-time auto-triggers the surge recompute.

---

## State Management (what your app needs)
- `theme` ('light'|'dark'), `density` ('comfortable'|'compact'), `intensity` (number), `extrude` (number), `tilt` (deg) — all user-tweakable.
- `networkState` ('base'|'surge'|'mit') + `eventFired`, `recomputing`, `blocked` flags.
- `activeScenario`, `activeTool`, `previewPlan`, `appliedActions[]`.
- `copilotLog[]`, `scrubberMinute`, live `telemetry` object.
- Per-edge pressures keyed by network state (from your assignment model).

## Interactions
- Tool tile click → highlight + reveal validated plan (modeling the event first if needed).
- Apply → recompute animation → mitigated. Discard → hide preview.
- Theme toggle (header + tweaks stay in sync). Recenter flies to the stadium. Reset → baseline.
- Copilot chip/enter → routed to hero or blocked path. All actions are **preview-first** — nothing mutates the network without an explicit recompute.
- Tweaks panel is host-toggled (see `tweaks-panel.jsx` protocol); in your app this becomes a normal settings panel.

## Assets
No raster assets. All icons are inline single-color SVGs (stroke 1.7–1.8). Fonts via Google Fonts. Basemap tiles via your provider (prototype used CARTO positron / dark-matter, no key).

## Files in this bundle
- `flowto.html` — full prototype (CSS inlined in `<style>`); open it to see every state live.
- `js/data.js` — **all domain data**: corridors, blast radius, actions, scenarios, tools, metrics, timeline, telemetry, copilot scripts + citations. Best starting point for content.
- `js/map.js` — map engine: congestion ramp, building extrusion, corridor renderer (prototype canvas — replace with deck.gl), markers, theme swap.
- `js/ui.js` — panel rendering, metrics/deltas, copilot log + typing, scrubber, recompute overlay, perf strip.
- `js/app.js` — the state machine / orchestration (recompute loop, surge, apply, block, tweaks).
- `js/tweaks.jsx` + `tweaks-panel.jsx` — the tweak controls (prototype host-panel; reimplement as a settings UI).

To explore behavior, open `flowto.html` and click **Load the twin**, then a Copilot chip or the **Demand surge** tool, then **Apply & recompute**. Toggle the theme (top-right moon).
