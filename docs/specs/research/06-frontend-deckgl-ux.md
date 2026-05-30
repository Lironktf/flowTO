# Research Brief 06 — Frontend: deck.gl + MapLibre planner instrument

> Feeds **P07**. Version anchor: **deck.gl v9.3** (2026-04-13), **maplibre-gl v5**, **react-map-gl v8**.
> NOTE: visual design system (tokens/fonts/HTML) arrives as a **separate Claude design drop** — this brief covers *integration architecture*, not the final visual language.

## 1. deck.gl + MapLibre setup
**Use `MapboxOverlay` (`@deck.gl/mapbox`) in INTERLEAVED mode, mounted via `react-map-gl/maplibre` `useControl`.** Canonical vis.gl pattern.
- **Interleaved** (not overlaid): renders deck layers into MapLibre's WebGL2 context → 3D buildings occlude correctly + `beforeId` slots congestion lines *under* labels (labels stay readable). Needs `maplibre-gl@>3` (we're on 5). Reject overlaid (breaks 3D occlusion) + reverse-controlled (blocks map interaction).
- Use **`react-map-gl/maplibre`** (v8 split endpoints) for declarative `viewState` (fly-to affected corridor) + lifecycle.
```tsx
import {Map, useControl} from 'react-map-gl/maplibre';
import {MapboxOverlay, type MapboxOverlayProps} from '@deck.gl/mapbox';
import 'maplibre-gl/dist/maplibre-gl.css';
function DeckOverlay(props: MapboxOverlayProps){
  const overlay = useControl(() => new MapboxOverlay({...props, interleaved:true}));
  overlay.setProps(props); return null;
}
<Map initialViewState={{longitude:-79.384, latitude:43.653, zoom:12, pitch:45}} mapStyle={STYLE_URL} reuseMaps>
  <DeckOverlay layers={layers} />
</Map>
```
Use `beforeId` per layer for z-order (roads/heatmap below labels, closures above).
**Basemap (no token): Protomaps + PMTiles self-hosted** (single `.pmtiles`, HTTP Range, no tile server; `light`/`grayscale` flavor so the basemap recedes and congestion color carries meaning). Hosted fallback: **CARTO Positron**. Wiring: `maplibregl.addProtocol('pmtiles', protocol.tile)` → `pmtiles://.../toronto.pmtiles`. Only option that survives a disconnected planning-room laptop.

## 2. Layer-by-layer plan
Tick frames over WS are binary `{edge_id, load, speed, pressure, closure_state}`. **Principle: upload road geometry ONCE; every tick mutates only color/width attributes.**
- **A. Roads — colored by pressure:** citywide → **`MVTLayer`** (binary, viewport-culled, LOD; `uniqueIdProperty:'edge_id'`, `highlightedFeatureId`); working set → **`PathLayer`**. Per-tick recolor: `updateTriggers:{getColor: tickSeq}` re-runs *only* the color accessor (geometry untouched). Max throughput → feed a **binary attributes object** (pre-packed `Float32Array` indexed by edge; WS handler writes into it). Optional `transitions:{getColor:250}` to crossfade (avoid strobing).
- **B. Congestion overlay — NOT HeatmapLayer for the primary read** (it's point KDE → blurs link structure, misleads). **Primary congestion = the colored road lines.** Secondary "where's it concentrated" = **`HexagonLayer`** binning edge midpoints by `pressure`, `gpuAggregation:true`. `ScreenGridLayer` only for a coarse density toggle.
- **C. 3D massing:** `GeoJsonLayer` `extruded:true` + `getElevation`; **monochrome/neutral grey** (never green/amber/red — that budget is congestion only). Gate with `visibleMinZoom`.
- **D. Closures + corridor highlight:** second `PathLayer` (affected edges, wider, accent + `PathStyleExtension` dashes, above labels) or MVT `highlightedFeatureId`; `IconLayer` for closure points.
- **E. Transit vehicles:** `TripsLayer` driven by `currentTime` synced to the **scrubber** (not free rAF). Toggle; default off in compare mode.
- **F. Performance:** MVT binary tiles (biggest lever); per-layer `minZoom`/`visibleMinZoom`; **server drops minor roads at low zoom** (class filter); binary attribute updates; keep `layers` array referentially stable except the changed prop.

## 3. Planner UI/UX architecture
This is an **instrument**, not a dashboard. Model on **Remix/Via** (draw-on-map → operational consequence) + **Streetmix** (legible editing) + **mission-control console** restraint.
**Layout (map-dominant):** top bar (scenario · status · before/after toggle · save); **left** = collapsible intervention drawer; **center** = map canvas (always the focus); **right** = before/after metrics + copilot (tabbed); **bottom full-width** = time scrubber (owns `currentTime`, AM/PM snap markers); floating dev-only debug/perf panel.
**Interaction (select → choose → preview → apply, preview mandatory):** (1) click/lasso edges → highlight (Zustand keyed by `edge_id`); (2) contextual popover: closure/lane-reduction/one-way/signal + params; (3) **validate + explain the WHY** — allowed / blocked (e.g. "isolates a hospital route") / warning, every disabled action states its reason inline; (4) **preview** as ghost/diff overlay + provisional metric deltas marked "PREVIEW — not applied" (split/swipe before↔after); (5) apply → REST → server recompute → new tick stream; explicit undo + removable intervention list.
**Visual direction (until the design drop lands):** green→amber→red **reserved strictly for congestion**; UI chrome neutral cool grey + one non-traffic accent (blue/violet) for selection/preview; closures a distinct desaturated purple/charcoal (NOT red); basemap grayscale recedes; tabular-figures for metrics so before/after don't jitter; high density but quiet (hairline dividers, no shadow theatrics); congestion **not hue-alone** (pair with width/texture + numeric readout; check deuteranopia on amber→red); keyboard-driveable, WCAG-AA.
**Components:** **Radix UI + Tailwind (shadcn pattern), not a heavy kit** — a planner needs bespoke scrubber/edge-popover/metric-row/intervention-card; Radix gives accessible unstyled behavior to style to the civic language. Avoid Material/AntD. `@deck.gl/widgets` only for in-canvas map controls.

## 4. Streaming / state (no re-render storms)
**Rule: tick data NEVER enters React state.** Three tiers: (1) **hot tick → outside React**: module-level typed arrays indexed by `edge_id` (`pressure:Float32Array`, `load`, `speed`, `closure:Uint8Array`); WS `onmessage` decodes binary and writes in place (zero React, zero alloc). (2) **drive deck imperatively**: throttled single rAF loop → `overlay.setProps({layers})` or push into the layer's binary `attributes`; bump `tickSeq` in `updateTriggers`. (3) **warm app state → Zustand** (scenario, selected edges, preview, scrubber time, toggles) — human-cadence re-renders; subscribe panels with selectors.
```ts
ws.binaryType='arraybuffer';
ws.onmessage=(ev)=>{ const v=new DataView(ev.data); /* parse records → pressure[idx]=p; */ dirty=true; };  // no setState
function frame(){ if(dirty){ rebuildColorBuffer(); overlay.setProps({layers:makeLayers(tickSeq++)}); dirty=false; } requestAnimationFrame(frame); }
```
Coalesce bursts (render ≤ once/rAF); keep last snapshot on disconnect (map static not blank); scrubbing historical → pause live writer, read from snapshot ring buffer.

### Top calls
(1) interleaved `MapboxOverlay` via `react-map-gl/maplibre`; (2) Protomaps/PMTiles grayscale basemap (offline); (3) congestion on road lines (PathLayer/MVT + `updateTriggers`/binary attrs), HexagonLayer as the only aggregation, **HeatmapLayer rejected**; (4) tick data never touches React; (5) Radix/shadcn headless, green→amber→red = congestion only.

### Links
using-with-maplibre: https://deck.gl/docs/developer-guide/base-maps/using-with-maplibre · MapboxOverlay: https://deck.gl/docs/api-reference/mapbox/mapbox-overlay · what's new: https://deck.gl/docs/whats-new · react-map-gl upgrade: https://visgl.github.io/react-map-gl/docs/upgrade-guide · MVTLayer: https://deck.gl/docs/api-reference/geo-layers/mvt-layer · performance: https://deck.gl/docs/developer-guide/performance · Protomaps: https://github.com/protomaps/basemaps · PMTiles+MapLibre: https://docs.protomaps.com/pmtiles/maplibre · Remix: https://ridewithvia.com/solutions/remix/streets · Streetmix: https://streetmix.net/
