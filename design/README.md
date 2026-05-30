# Handoff: FlowTO — Live Digital Twin of Toronto

## Overview
FlowTO is a city-scale traffic & transit **digital twin** with two working modes:

- **Simulate** — an animation-player view. The map shows a 3-D camera; a non-linear-editor (NLE) timeline scrubs a matchday like a video (transport, timecode, keyframes, heat/demand/plan tracks). A Before / After A·B toggle flips the network between modelled states. The Copilot is available here.
- **Edit** — a top-down workspace (Unity-editor feel, flattened to a Google-Maps-style plan view). A vertical tool rail lets you drop interventions (closures, lane reductions, one-ways, signal retiming, demand surges) by clicking the map. Placed objects populate an Inspector and a Scene outliner. The Copilot is available here too.

The driving scenario is **FIFA WC26 post-match egress** at Toronto Stadium (BMO Field, Exhibition Place): ~45,000 people released at full-time, the network goes to gridlock, and the Copilot proposes a **bylaw-valid** mitigation plan that recomputes the network. Everything is framed as **100% on-device** compute (DGX Spark · GB10).

## About the Design Files
The files in this bundle are **design references created in HTML/CSS/vanilla-JS** — a working prototype that demonstrates the intended look, layout, motion, and interaction model. They are **not** production code to copy directly.

The task is to **recreate these designs in the target codebase's environment** (React, Vue, Svelte, native, etc.) using its established component patterns, state management, and mapping stack. If no environment exists yet, choose the most appropriate framework. The HTML is organized into clean modules (`data` / `map` / `ui` / `app`) precisely so the structure maps cleanly onto components + a store + a map adapter.

All map data here is **simulated/mocked** (hand-authored corridor geometry and metrics in `js/data.js`). A real implementation would wire the map adapter and metrics panels to live network/assignment services.

## Fidelity
**High-fidelity.** Final colors, typography, spacing, motion, and interaction behavior are all specified. Recreate the UI faithfully using the codebase's existing primitives. The two themes (light "paper" / dark "ops") and the two-view layout are core to the design and should be preserved.

---

## Application Shell

A fixed full-viewport CSS Grid with named areas. Docks are **flush** (edge-to-edge, hairline dividers, no floating cards or drop shadows between panels) — this is deliberate and reads as "a piece of software" (Blender / Unity reference), not a web page.

```
grid-template-areas:
  "topbar topbar topbar topbar"
  "rail   left   view   right"
  "rail   left   bottom right"
  "status status status status";
grid-template-columns: var(--rail-w) var(--left-w) 1fr var(--right-w);
grid-template-rows:    var(--top-h)  1fr           var(--bottom-h) var(--status-h);
```

Dock widths/heights are CSS variables. Toggling a dock sets the corresponding var to `0px` and the grid animates closed (`transition: grid-template-columns/rows .26s cubic-bezier(.4,0,.1,1)`). Toggle classes on `<body>`: `no-left`, `no-right`, `no-bottom`, `no-rail`.

**View scoping** is driven by a single attribute, `body[data-view="sim"|"edit"]`:
- `body[data-view="sim"] .v-edit { display:none }`
- `body[data-view="edit"] .v-sim { display:none }`

So each region in a dock is tagged `.v-sim`, `.v-edit`, or neither (shown in both, e.g. Copilot). Switching views also re-derives which docks are open (see *View switching* below).

### Dock sizing tokens
| Token | Comfortable | Compact |
|---|---|---|
| `--rail-w` | 46px | 46px |
| `--left-w` | 274px | 248px |
| `--right-w` | 346px | 318px |
| `--top-h` | 46px | 46px |
| `--bottom-h` | 184px | 158px |
| `--status-h` | 26px | 26px |

---

## Screens / Views

### 1. Top Bar (always visible)
- **Brand**: "Flow**TO**" — Fraunces 600, 20px, `-0.02em` tracking; "TO" in cobalt. Subtitle in IBM Plex Mono 9.5px uppercase, `0.08em`.
- **View switch** (segmented control, `.viewseg`): two buttons *Simulate* (play glyph) / *Edit* (pencil glyph). Active button gets raised surface + soft shadow + cobalt icon.
- **Scenario tag**: small label/value showing the active scenario name.
- **Status chip** (`.statuschip`): pill with a colored dot + uppercase mono text. States via `data-state`: `nominal` (green dot), `recomputing` (pulsing cobalt dot), `surge` (severe-red dot), `blocked` (orange dot).
- **Dock toggles** (`.dock-toggles`): three icon buttons (left / bottom / right) that show a tiny window-region glyph; `.on` = cobalt wash.
- **Theme toggle** (moon glyph) + **Reset** ghost button.

### 2. Tool Rail (Edit view only — `grid-area: rail`)
Vertical 46px strip. Buttons (`.rail-tool`, 34×34): *Select* on top, a hairline separator, then the five interventions. Active tool: cobalt wash + cobalt-line border + a 2px cobalt indicator bar on the left edge (`::before`). Hover reveals a dark tooltip pill to the right (`.rail-tip`). Number keys **1–5** select tools; **Esc** returns to Select.

### 3. Left Dock (`grid-area: left`)
**Simulate** → *Scenarios* region (`.v-sim`): list of saved scenarios (`.scn-item`) with a mono badge + name + meta; active item gets cobalt border + wash.

**Edit** → two regions (`.v-edit`):
- *Interventions* — full tool list (`.tool-row`): icon tile + name + description + numbered kbd hint.
- *Scene* — the outliner (`.outliner`): one row per placed object (`.out-row`) with a type-colored square, name, mono type tag, and an eye toggle for visibility. Selected row = cobalt wash. Empty state messaging when no objects.

### 4. Viewport (`grid-area: view`) — the map
- MapLibre GL basemap. **No blueprint grid** anywhere — premium "paper" (light) or near-black "ops" (dark) ground. Corridors are drawn as colored lines on a congestion ramp; extruded buildings appear only in the 3-D (Simulate) camera and are flattened to opacity 0 in top-down (Edit).
- **Camera by view**: Simulate eases to `pitch: 52, bearing: -18` (3-D); Edit eases to `pitch: 0, bearing: 0` (top-down). `setView()` in `js/map.js`.
- **HUD overlays** (absolutely positioned, `.vp-hud` corners):
  - top-left: **mode banner** (icon + "Simulation / 3-D camera" or "Editor / Top-down").
  - top-right: recenter + tilt-toggle icon buttons.
  - bottom-left: **legend** — "Edge pressure" with the congestion gradient ramp.
  - bottom-center: **plan action bar** (`.plan-bar`, shared by both views) — appears when the Copilot stages a plan: icon + title + "N bylaw-valid actions · −38% delay" + **Apply & recompute** / **Discard**.
- **Placement** (Edit): cursor becomes a crosshair; a dashed ghost ring (`#place-ghost`) follows the pointer showing the armed tool's icon. Clicking the map drops a pin.
- **Pins** (`.map-pin`): a colored circular nub (numbered) + a label chip. Type colors below. Selected pin gets a cobalt outline.
- **Recompute overlay** (`#recompute`): bottom-center card with a spinner, title, percent, progress bar, and 5 stepper dots (Demand model → Trip assignment → Edge pressure → Bylaw check → Render).

### 5. Bottom Dock (`grid-area: bottom`) — NLE Timeline (Simulate view by default)
A non-linear-editor transport, Blender/Adobe reference:
- **Transport bar**: jump-to-start / step-back / **play** (cobalt) / step-forward / jump-to-end.
- **Clock**: large mono timecode (`17:05`), frame counter (`f 740`), day-of-week (`FRI · 12 JUN 2026`).
- **Right**: current-event hint + speed selector (0.5× / 1× / 2× / 4×).
- **Ruler**: ticks every 15 min, major ticks + labels on the hour.
- **Keyframe row**: diamond markers for *kickoff* (filled cobalt) and *full-time* (red event). Clicking a diamond seeks to it.
- **Tracks** (`.tl-track`, name column 60px + lane):
  - *Congest* — a gradient heat strip sampling network pressure across time.
  - *Demand* — clips: "MATCH 90'" + a red "EGRESS 45k" clip at full-time.
  - *Plan* — empty/"no plan staged" until a plan is applied, then a "CONTRAFLOW" clip + transit sub-bar.
- **Playhead** (`.tl-playhead`): cobalt vertical line with a draggable grip; spans ruler + tracks. Scrubbing seeks (snapped to the 15-min step). Playback advances every `520/speed` ms; reaching full-time auto-triggers the surge recompute if not already fired.

### 6. Right Dock (`grid-area: right`)
**Simulate** → *Before / After* region (`.v-sim`):
- A·B toggle in the region header (`.ba-toggle`).
- Metric cards (`.metric`): a wide hero card for **Total network delay** with a two-bar before/after comparison, then a 2×2 grid (mean TT, p95 TT, congested edges, local infiltration). Each shows value + unit (Fraunces numerals) and a colored delta chip (green = improvement, red = regression). A warning row at the bottom flips between a red "cut-through unmitigated" warning and a green "plan valid" confirmation. Empty state when network is nominal.

**Edit** → *Inspector* region (`.v-edit`): properties of the selected object — icon header (type-colored), location (lat/lng mono), status, and type-specific parameter rows (sliders, segmented controls, read-only values). Actions: **Recompute impact** / **Delete**. Empty/placement-hint states when nothing is selected.

**Both** → *Copilot* region (`#copilot-region`, grows to fill): message log (user bubbles cobalt/right, bot bubbles surface/left with bulleted steps + a citations block referencing real bylaws), suggestion chips, and an input with a send button.

### 7. Status Bar (`grid-area: status`)
Thin telemetry strip, all IBM Plex Mono. Cells: Network (edges·nodes), Recompute (ms), Subgraph (edges), LLM (ms), and right-aligned: FPS + a live sparkline, and a cobalt-wash **Compute · DGX Spark · GB10** cell.

### 8. First-run splash (`#firstrun`)
Full-viewport paper cover: mono eyebrow, large Fraunces headline ("A live digital twin of **Toronto**."), lede explaining Simulate/Edit, three meta stats, and a **Load the twin** primary button. A typewriter boot log runs under it. Fades out (opacity .55s) on load.

---

## Interactions & Behavior

### View switching (`FlowTO.app.setView`)
- Sets `body[data-view]`, eases the map camera, and re-derives docks:
  - **Simulate**: bottom dock (timeline) **open**, rail **closed**.
  - **Edit**: bottom dock **closed**, rail **open**; Inspector/outliner refresh.
- Leaving Edit resets the active tool to *Select* and clears the placement ghost.
- `map.resize()` is called ~280ms after a toggle so MapLibre reflows into the new grid area.

### The core scenario loop
1. **Baseline** — network nominal, metrics empty, status `nominal`.
2. **Surge trigger** — fires when (a) the timeline scrubs to full-time, (b) the user asks the Copilot, or (c) a `surge` tool is placed. Camera flies to the stadium; recompute overlay runs; state → `surge`; blast-radius corridors light up red; metrics show the unmitigated impact; status `surge`.
3. **Plan** — Copilot returns a cited, preview-first plan and the bottom-center plan bar appears.
4. **Apply** — recompute runs (with a bylaw-check step); state → `mit`; corridors ease toward green; action markers drop on the map; the timeline *Plan* track populates; metrics flip to the mitigated deltas (−38% delay); status returns to `nominal` ("plan applied").

### Recompute engine (`runRecompute(title, dur, onDone)`)
Drives the overlay: animates progress 0→100 over `dur` ms, advances the 5 stepper dots, ramps the live telemetry numbers (recompute ms, subgraph edges, LLM ms appears at the bylaw-check step), then resolves and calls `onDone`. Guarded by a `recomputing` flag (no re-entrancy).

### Editor placement (`selectTool` → `placeAt`)
Selecting a tool arms placement (ghost + crosshair + map click handler). Clicking the map unprojects to lng/lat, snaps the name to the nearest corridor if close, adds a scene object + pin, selects it (populating the Inspector), and runs a short targeted "subgraph" recompute.

### Copilot
- The hero request returns a validated mitigation with bylaw citations and stages the plan.
- A deliberately over-reaching request ("close Lake Shore both ways") is **blocked** with two hard-constraint citations and an alternative offer; status briefly goes `blocked`.
- Typing indicator (3 bouncing dots) precedes each bot reply (~1.1–1.5s).

### Animations / motion
- Dock open/close: grid template transition, `.26s cubic-bezier(.4,0,.1,1)`.
- Camera eases: `pitch/bearing` `700ms`; flyTo `900–1100ms`.
- Status dot pulse, typing dots, recompute spinner, bar fills (`.9s cubic-bezier(.4,0,.1,1)`), pin fade-up.
- Congestion line colors transition on state change.

### Keyboard
- **1–5** select interventions (Edit only), **Esc** → Select tool.

---

## State Management

State of record lives in `js/app.js`:
- `view` — `'sim' | 'edit'`.
- `modelled` — `'base' | 'surge' | 'mit'` (the network state being modelled).
- `compare` — `'before' | 'after'` (Simulate A·B toggle; maps to which `modelled` snapshot the map paints).
- `recomputing`, `eventFired`, `loaded` — flow guards.
- `activeTool` — current intervention tool or `'select'`.
- `objects[]`, `selectedId`, `objSeq` — the editor scene graph (placed interventions).
- `theme` — `'light' | 'dark'` (mirrored to `<html data-theme>`), `density` → `<html data-density>`.
- Timeline scrub position lives in `js/ui.js` (`scrubMin`).

In a real app: a single store (Redux/Zustand/Pinia/etc.) holding `{view, modelled, compare, objects, selected, recompute, timeline}`; the map adapter and panels subscribe. Recompute and Copilot become async service calls; the overlay reflects real job progress.

---

## Design Tokens

All tokens are CSS custom properties in `css/flowto.css`, themed by `[data-theme]`.

### Colors — Light ("paper")
| Token | Value | Use |
|---|---|---|
| `--paper` | `#ece6d8` | viewport letterbox / map void |
| `--chrome` | `#f4f0e7` | dock surface |
| `--chrome-2` | `#ebe5d8` | recessed surface (tracks, wells) |
| `--chrome-hi` | `#faf7f0` | raised surface (header, hover) |
| `--ink` | `#1b1a16` | primary text |
| `--ink-2` | `#514c40` | secondary text |
| `--ink-3` | `#847d6d` | tertiary |
| `--ink-4` | `#a59d8b` | quaternary / faint |
| `--hair` | `rgba(27,26,22,.14)` | region dividers |
| `--hair-2` | `rgba(27,26,22,.08)` | inner hairlines |
| `--map-bg` | `#e6e0d0` | map ground |

### Colors — Dark ("ops")
| Token | Value |
|---|---|
| `--paper` | `#0a0d11` |
| `--chrome` | `#14191f` |
| `--chrome-2` | `#0f141a` |
| `--chrome-hi` | `#1b222b` |
| `--ink` | `#e9ecf1` |
| `--ink-2` | `#aab2bf` |
| `--ink-3` | `#6f7a88` |
| `--ink-4` | `#515c69` |
| `--map-bg` | `#0a0d11` |

### Accent — cobalt (the only brand/UI accent)
| Token | Light | Dark |
|---|---|---|
| `--cobalt` | `#2455d6` | `#6f9bff` |
| `--cobalt-ink` | `#1c46b4` | `#9ab8ff` |
| `--cobalt-wash` | `rgba(36,85,214,.12)` | `rgba(111,155,255,.16)` |
| `--cobalt-line` | `rgba(36,85,214,.40)` | `rgba(111,155,255,.5)` |

### Congestion ramp (the only semantic color scale)
free → gridlock: `--c-free #1f9d57` · `--c-light #8aaf1f` · `--c-mod #e0a21a` · `--c-heavy #e0701b` · `--c-sev #d23a32` (dark theme uses slightly brighter variants). Type/pin colors map onto this: closure=heavy, lane=mod, oneway/signal=cobalt, surge=sev, transit=free.

### Typography
- **Display / numerals**: Fraunces (400/500/600). Headlines, large stat values.
- **UI text**: Public Sans (400/450/500/600/700). Default `--fs-body` 12.5px (12px compact).
- **Mono / data**: IBM Plex Mono (400/500/600), `font-variant-numeric: tabular-nums`. Labels (`0.08–0.13em` tracking, uppercase), timecode, telemetry. `--fs-mono` 11px.

### Radius & elevation
- `--r` 7px, `--r-sm` 5px; pins/markers 999px pills.
- `--inset` `inset 0 1px 0 rgba(255,255,255,.5)` (raised-surface top highlight).
- Docks are flush (no shadow). Only floating elements (HUD chips, plan bar, recompute card, tooltips) carry shadows.

### Motion
- Standard ease: `cubic-bezier(.4,0,.1,1)`. Dock `.26s`, camera `.7s`, flyTo `.9–1.1s`, bar fills `.9s`, micro-transitions `.12–.18s`.

---

## Assets
- **No raster/SVG art assets.** All iconography is inline SVG (stroke-based, drawn in `js/ui.js` `ICONS` and in the HTML). Reuse the codebase's icon set when reimplementing.
- **Fonts** via Google Fonts: Fraunces, Public Sans, IBM Plex Mono.
- **Map**: MapLibre GL JS + CSS (`4.7.1`). Basemap style and corridor/building layers are configured in `js/map.js`. All corridor geometry & metrics are mock data in `js/data.js` — replace with live services.
- **Tweaks panel** (`tweaks-panel.jsx` + `js/tweaks.jsx`): an optional React island exposing theme/density/intensity/extrude/tilt controls, bridged via `window.FlowTO`. Not core to the product UI — safe to drop or replace with your own settings surface.

---

## Files (in this bundle)
| File | Role |
|---|---|
| `flowto.html` | App shell: grid layout, all dock regions, HUD, first-run, script order. |
| `css/flowto.css` | Complete design system: tokens (both themes), shell grid, every component. |
| `js/data.js` | Mock domain data: Toronto corridors, actions, scenarios, tools, metrics, timeline, perf, Copilot scripts. **Replace with live services.** |
| `js/map.js` | MapLibre adapter: basemap, corridor lines + extruded buildings, `setView` (3-D ↔ top-down), pins, placement unproject. |
| `js/ui.js` | All rendering & widgets (vanilla): rail, tools, scenarios, NLE timeline, metrics, inspector, outliner, copilot, recompute overlay, status bar. |
| `js/app.js` | Orchestration / state machine: view switching, recompute engine, scenario loop, scene objects, copilot, theme/tweaks. |
| `tweaks-panel.jsx`, `js/tweaks.jsx` | Optional React tweaks island (non-core). |

### Run locally
Serve the folder over HTTP (MapLibre + Babel need it) and open `flowto.html`:
```
npx serve .     # or: python3 -m http.server
```
Click **Load the twin**, then use the **Simulate / Edit** switch in the top bar.
