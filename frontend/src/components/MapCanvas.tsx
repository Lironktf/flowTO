/**
 * Viewport: Mapbox Standard basemap + interleaved deck.gl, rendering the REAL
 * graph recolored by live engine pressures (tick store). Standard gives us
 * dynamic time-of-day lighting (driven by the scrubber) and opaque 3D buildings;
 * the congestion PathLayer is drawn over it. Camera eases 3-D (Simulate) ↔
 * top-down (Edit). In Edit, clicks snap to the nearest intersection (vertex):
 * two for a corridor closure, one for a demand surge. In Simulate, clicking a
 * road selects it (drives the bottom congestion chart).
 */
import { MapboxOverlay } from "@deck.gl/mapbox";
import { PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import "mapbox-gl/dist/mapbox-gl.css";
import { useEffect, useMemo, useRef, useState } from "react";
import { Map, useControl, type MapRef } from "react-map-gl/mapbox";
import { api } from "../api/client";
import { MAP_CENTER, MAP_ZOOM, RECOMPUTE_STEPS_LABEL, STADIUM } from "../config";
import { buildTransitLayers, type RouteGeom } from "../layers/transit";
import {
  addEarlyBuildings,
  applyLightPreset,
  CONGESTION_SLOT,
  HAS_MAPBOX_TOKEN,
  lightPresetForMinute,
  MAPBOX_TOKEN,
  setEarlyBuildingsColor,
  setShow3dObjects,
  setStandardConfig,
  STANDARD_STYLE,
} from "../lib/mapbox";
import { pressureRamp } from "../lib/pressureRamp";
import { nearestNode, streetsByDirection } from "../api/graph";
import { RECOMPUTE_STEPS, useAppStore } from "../state/appStore";
import { getArrays } from "../state/tickStore";
import { Icon } from "./Icons";

function DeckOverlay(props: { layers: unknown[]; onClick?: (info: { layer?: { id?: string } | null }) => void }) {
  const overlay = useControl(() => new MapboxOverlay({ interleaved: true, layers: [] }));
  // @ts-expect-error deck layer typing is loose here
  overlay.setProps({ layers: props.layers, onClick: props.onClick });
  return null;
}

const WIDTH_BY_CLASS: Record<string, number> = {
  motorway: 16, trunk: 13, primary: 11, secondary: 8, tertiary: 6, residential: 4, service: 3,
};
const PIN_COLOR: Record<string, [number, number, number]> = {
  closure: [210, 58, 50], surge: [224, 112, 27],
};
const SURGE_COLOR: [number, number, number] = [224, 112, 27];
const RELIEF_COLOR: [number, number, number] = [245, 184, 122];

/** deck.gl TextLayer angle (degrees, CCW from east) for travel from a→b ([lng,lat]). */
function travelAngle(a: [number, number], b: [number, number]): number {
  return (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI;
}

/** A few flow-arrow markers placed along a [lng,lat] polyline, angled with travel. */
function arrowMarkers(path: [number, number][]): { position: [number, number]; angle: number }[] {
  const n = path.length;
  if (n < 2) return [];
  const fracs = n <= 2 ? [0.5] : [0.35, 0.6, 0.85];
  return fracs.map((f) => {
    const i = Math.min(n - 2, Math.max(0, Math.floor(f * (n - 1))));
    const a = path[i];
    const b = path[i + 1];
    return { position: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] as [number, number], angle: travelAngle(a, b) };
  });
}

interface EdgePath { edge_id: string; idx: number; road_class: string; path: [number, number][]; }

export function MapCanvas() {
  const mapRef = useRef<MapRef | null>(null);
  const theme = useAppStore((s) => s.theme);
  const intensity = useAppStore((s) => s.intensity);
  const view = useAppStore((s) => s.view);
  const edges = useAppStore((s) => s.edges);
  const graph = useAppStore((s) => s.graph);
  const pressureSeq = useAppStore((s) => s.pressureSeq);
  const objects = useAppStore((s) => s.objects);
  const selectedId = useAppStore((s) => s.selectedId);
  const selectedRoadId = useAppStore((s) => s.selectedRoadId);
  const selectRoad = useAppStore((s) => s.selectRoad);
  const pendingVertices = useAppStore((s) => s.pendingVertices);
  const activeTool = useAppStore((s) => s.activeTool);
  const planStaged = useAppStore((s) => s.planStaged);
  const recomputing = useAppStore((s) => s.recomputing);
  const recomputeStep = useAppStore((s) => s.recomputeStep);
  const recomputeTitle = useAppStore((s) => s.recomputeTitle);
  const recenterNonce = useAppStore((s) => s.recenterNonce);
  const flyNonce = useAppStore((s) => s.flyNonce);
  const fitNonce = useAppStore((s) => s.fitNonce);
  const flyPin = useAppStore((s) => s.flyPin);
  const tiltOn = useAppStore((s) => s.tiltOn);
  const scrubMin = useAppStore((s) => s.scrubberMinute);
  const dayOfYear = useAppStore((s) => s.dayOfYear);
  const placeAt = useAppStore((s) => s.placeAt);
  const selectObject = useAppStore((s) => s.selectObject);
  const applyPlan = useAppStore((s) => s.applyPlan);
  const discardPlan = useAppStore((s) => s.discardPlan);
  const dark = theme === "dark";
  const placing = view === "edit" && activeTool !== "select";
  // Mirror `placing` into a ref so the deck click handler reads the *pre-click*
  // value (effects commit after click handlers run) — a placement click then
  // can't be misread as a deselect.
  const placingRef = useRef(placing);
  useEffect(() => { placingRef.current = placing; }, [placing]);
  const [hoverStreet, setHoverStreet] = useState(false);
  const [hoverPinId, setHoverPinId] = useState<string | null>(null);
  const [overlays, setOverlays] = useState({ poi: true, transit: false, roadLabels: true, placeLabels: true, buildings3d: true });
  const [layersOpen, setLayersOpen] = useState(false);

  const edgePaths: EdgePath[] = useMemo(() => {
    const out: EdgePath[] = [];
    for (const e of edges) {
      if (!e.geometry || e.geometry.length < 2) continue;
      out.push({
        edge_id: e.edge_id, idx: e.idx, road_class: e.road_class ?? "residential",
        path: e.geometry.map(([lat, lng]) => [lng, lat] as [number, number]),
      });
    }
    return out;
  }, [edges]);

  const [routes, setRoutes] = useState<RouteGeom[]>([]);
  useEffect(() => {
    let alive = true;
    api
      .transitRoutes("ttc")
      .then((r) => {
        if (!alive) return;
        setRoutes(r.routes.map((x) => ({ route_id: x.route_id, mode: x.mode, path: x.path })));
      })
      .catch(() => void 0);
    return () => { alive = false; };
  }, []);

  // Camera: ease pitch/bearing on view + tilt; flyTo on recenter.
  useEffect(() => {
    const m = mapRef.current?.getMap();
    if (!m) return;
    const pitch = tiltOn ? 52 : 0;
    const bearing = tiltOn ? -18 : 0;
    m.easeTo({ pitch, bearing, duration: 700 });
    // The viewport box can change size when switching views (sidebars/panels);
    // resize once the layout has settled so the canvas isn't clipped/stretched.
    const t = setTimeout(() => mapRef.current?.getMap()?.resize(), 320);
    return () => clearTimeout(t);
  }, [view, tiltOn]);

  // Keep the map canvas filling #viewport whenever it changes size — collapsing
  // a side/bottom dock grows the viewport, but the WebGL canvas only resizes
  // when told. A ResizeObserver fires continuously through the CSS transition,
  // so the map expands to fill the freed space instead of leaving a gutter.
  useEffect(() => {
    const el = document.getElementById("viewport");
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => mapRef.current?.getMap()?.resize());
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    const m = mapRef.current?.getMap();
    if (!m || recenterNonce === 0) return;
    m.flyTo({ center: MAP_CENTER, zoom: MAP_ZOOM, duration: 900 });
  }, [recenterNonce]);
  // Search → fly the camera to a point hit (place); zoom defaults to a street-level view.
  useEffect(() => {
    const m = mapRef.current?.getMap();
    const t = useAppStore.getState().flyTarget;
    if (!m || flyNonce === 0 || !t) return;
    m.flyTo({ center: [t.lng, t.lat], zoom: t.zoom ?? 15.5, duration: 1100, essential: true });
  }, [flyNonce]);
  // Search → frame an entire street: fit the camera to the road's full extent.
  useEffect(() => {
    const m = mapRef.current?.getMap();
    const b = useAppStore.getState().fitTarget;
    if (!m || fitNonce === 0 || !b) return;
    m.fitBounds(b, { padding: 96, duration: 1100, maxZoom: 16, essential: true });
  }, [fitNonce]);

  // Time of day → Mapbox Standard light preset (dawn/day/dusk/night), shifted by season.
  useEffect(() => {
    applyLightPreset(mapRef.current?.getMap() as never, lightPresetForMinute(scrubMin, dayOfYear));
  }, [scrubMin, dayOfYear]);

  // Keep early-building extrusion tint in sync with the active theme.
  useEffect(() => {
    setEarlyBuildingsColor(mapRef.current?.getMap() as never, dark);
  }, [dark]);

  // Mapbox Standard label/object overlay toggles.
  useEffect(() => {
    const m = mapRef.current?.getMap() as never;
    setStandardConfig(m, "showPointOfInterestLabels", overlays.poi);
    setStandardConfig(m, "showTransitLabels", overlays.transit);
    setStandardConfig(m, "showRoadLabels", overlays.roadLabels);
    setStandardConfig(m, "showPlaceLabels", overlays.placeLabels);
    setStandardConfig(m, "show3dObjects", overlays.buildings3d);
  }, [overlays]);

  // Selected road → all edges that share its name (the whole street, not one
  // segment). Memoized on selection/graph so the 81k-edge scan never runs per frame.
  const selectedRoadPaths = useMemo(() => {
    if (!selectedRoadId || !graph) return null;
    const seg = graph.byId.get(selectedRoadId);
    if (!seg) return null;
    const name = seg.road_name;
    const segs = name ? graph.edges.filter((e) => e.road_name === name) : [seg];
    return segs.map((s) => ({ path: s.geometry.map(([la, ln]) => [ln, la] as [number, number]) }));
  }, [selectedRoadId, graph]);

  const layers = useMemo(() => {
    const out: unknown[] = [];
    const pressure = getArrays().pressure;
    out.push(
      new PathLayer({
        id: "roads",
        parameters: { depthCompare: "always" },
        slot: CONGESTION_SLOT,
        data: edgePaths,
        pickable: true,
        autoHighlight: true,
        highlightColor: [36, 85, 214, 160],
        getPath: (e: EdgePath) => e.path,
        getColor: (e: EdgePath) => pressureRamp(pressure[e.idx] ?? 0, { intensity, dark }),
        getWidth: (e: EdgePath) => WIDTH_BY_CLASS[e.road_class] ?? 2,
        widthUnits: "meters",
        widthMinPixels: 2,
        widthMaxPixels: 18,
        capRounded: true,
        jointRounded: true,
        updateTriggers: { getColor: [pressureSeq, intensity, dark] },
        onClick: (info: { object?: EdgePath }) => {
          if (useAppStore.getState().view === "sim" && info.object) selectRoad(info.object.edge_id);
        },
        onHover: (info: { object?: EdgePath }) => {
          // In Edit placement, only show the crosshair while over a street (the
          // edge that highlights blue); idempotent sets so React bails when unchanged.
          const st = useAppStore.getState();
          const placingNow = st.view === "edit" && st.activeTool !== "select";
          setHoverStreet(placingNow && !!info.object);
        },
      }),
    );

    // Selected-road highlight (sim) — the full named street.
    if (selectedRoadPaths) {
      out.push(
        new PathLayer({
          id: "road-selected",
          parameters: { depthCompare: "always" },
          slot: CONGESTION_SLOT,
          data: selectedRoadPaths,
          getPath: (d: { path: [number, number][] }) => d.path,
          getColor: [36, 85, 214],
          getWidth: 14,
          widthUnits: "meters",
          widthMinPixels: 4,
          widthMaxPixels: 22,
          capRounded: true,
          jointRounded: true,
        }),
      );
    }

    // Closure corridors (sealed edges) drawn as a thick red overlay.
    if (graph) {
      const closurePaths: { path: [number, number][] }[] = [];
      for (const o of objects) {
        if (o.type !== "closure" || !o.visible) continue;
        for (const id of o.edgeIds ?? []) {
          const s = graph.byId.get(id);
          if (s) closurePaths.push({ path: s.geometry.map(([la, ln]) => [ln, la] as [number, number]) });
        }
      }
      if (closurePaths.length) {
        out.push(
          new PathLayer({
            id: "closure-edges",
            parameters: { depthCompare: "always" },
            slot: CONGESTION_SLOT,
            data: closurePaths,
            getPath: (d: { path: [number, number][] }) => d.path,
            getColor: dark ? [120, 128, 138] : [140, 140, 140],
            getWidth: 12,
            widthUnits: "meters",
            widthMinPixels: 3,
            widthMaxPixels: 18,
            capRounded: true,
            jointRounded: true,
          }),
        );
      }
    }

    if (view === "sim" && routes.length && overlays.transit) {
      out.push(...buildTransitLayers(routes));
    }

    out.push(
      new ScatterplotLayer({
        id: "stadium", data: [STADIUM], getPosition: (d: typeof STADIUM) => d.coord,
        getRadius: 70, radiusUnits: "meters", getFillColor: dark ? [111, 155, 255] : [36, 85, 214],
        stroked: true, getLineColor: [255, 255, 255], lineWidthMinPixels: 2,
      }),
    );

    // Searched place → a marker so a point hit (no road to highlight) is visible.
    if (flyPin) {
      out.push(
        new ScatterplotLayer({
          id: "search-pin",
          parameters: { depthCompare: "always" },
          data: [{ coord: flyPin }],
          getPosition: (d: { coord: [number, number] }) => d.coord,
          getRadius: 9,
          radiusUnits: "pixels",
          getFillColor: dark ? [111, 155, 255] : [36, 85, 214],
          stroked: true,
          getLineColor: [255, 255, 255],
          lineWidthMinPixels: 2.5,
        }),
      );
    }

    // Pending closure vertices (the first picked intersection).
    if (pendingVertices.length) {
      out.push(
        new ScatterplotLayer({
          id: "pending-verts",
          data: pendingVertices,
          getPosition: (v: { lng: number; lat: number }) => [v.lng, v.lat],
          getRadius: 12, radiusUnits: "meters", radiusMinPixels: 4, radiusMaxPixels: 12,
          getFillColor: [36, 85, 214],
          stroked: true, getLineColor: [255, 255, 255], lineWidthMinPixels: 2,
        }),
      );
    }

    const visible = objects.filter((o) => o.visible);

    // Demand flow: highlight the streets each surge affects and draw arrows showing
    // which way (and along which streets) the demand flows — outward from its anchor
    // intersection along the chosen compass directions.
    if (graph) {
      const demandStreets: { path: [number, number][]; relief: boolean }[] = [];
      const demandArrows: { position: [number, number]; angle: number; relief: boolean }[] = [];
      for (const o of visible) {
        if (o.type !== "surge" || !o.surge) continue;
        const anchorKey = o.anchorKey ?? nearestNode(graph, o.coord[0], o.coord[1])?.key;
        if (!anchorKey) continue;
        const byDir = streetsByDirection(graph, anchorKey);
        const relief = o.surge.kind === "relief";
        for (const d of ["n", "e", "s", "w"] as const) {
          if (!o.surge.dirs[d]) continue;
          const st = byDir[d];
          if (!st) continue;
          demandStreets.push({ path: st.path, relief });
          for (const m of arrowMarkers(st.path)) demandArrows.push({ ...m, relief });
        }
      }
      if (demandStreets.length) {
        out.push(
          new PathLayer({
            id: "demand-streets",
            parameters: { depthCompare: "always" },
            slot: CONGESTION_SLOT,
            data: demandStreets,
            getPath: (d: { path: [number, number][] }) => d.path,
            getColor: (d: { relief: boolean }) => (d.relief ? RELIEF_COLOR : SURGE_COLOR),
            getWidth: 7,
            widthUnits: "meters",
            widthMinPixels: 4,
            widthMaxPixels: 12,
            capRounded: true,
            jointRounded: true,
          }),
          new TextLayer({
            id: "demand-flow-arrows",
            data: demandArrows,
            getPosition: (a: { position: [number, number] }) => a.position,
            getText: () => "➤",
            getAngle: (a: { angle: number }) => a.angle,
            getColor: (a: { relief: boolean }) => (a.relief ? RELIEF_COLOR : SURGE_COLOR),
            getSize: 18,
            characterSet: ["➤"],
            fontFamily: "IBM Plex Mono, monospace",
          }),
        );
      }
    }

    if (visible.length) {
      out.push(
        new ScatterplotLayer({
          id: "pins", data: visible, pickable: true,
          getPosition: (o: (typeof visible)[number]) => o.coord,
          getRadius: (o: (typeof visible)[number]) =>
            o.id === selectedId ? 20 : o.id === hoverPinId ? 17 : 14,
          radiusUnits: "meters", radiusMinPixels: 5, radiusMaxPixels: 16,
          getFillColor: (o: (typeof visible)[number]) =>
            o.type === "surge" && o.surge?.kind === "relief"
              ? [245, 184, 122]
              : PIN_COLOR[o.type] ?? [36, 85, 214],
          stroked: true,
          getLineColor: (o: (typeof visible)[number]) =>
            o.id === selectedId || o.id === hoverPinId ? [36, 85, 214] : [255, 255, 255],
          lineWidthMinPixels: 2.5,
          updateTriggers: { getRadius: [selectedId, hoverPinId], getLineColor: [selectedId, hoverPinId] },
          onClick: (info: { object?: (typeof visible)[number] }) => info.object && selectObject(info.object.id),
          onHover: (info: { object?: (typeof visible)[number] }) => setHoverPinId(info.object?.id ?? null),
        }),
        new TextLayer({
          id: "pin-labels", data: visible,
          getPosition: (o: (typeof visible)[number]) => o.coord,
          getText: (o: (typeof visible)[number]) => String(o.n),
          getSize: 12, getColor: [255, 255, 255], fontFamily: "IBM Plex Mono, monospace",
        }),
      );
    }
    return out;
  }, [edgePaths, pressureSeq, intensity, dark, view, routes, objects, selectedId, hoverPinId, selectObject, graph, selectedRoadId, selectedRoadPaths, selectRoad, pendingVertices, overlays, flyPin]);

  if (!HAS_MAPBOX_TOKEN) {
    return (
      <div id="map" style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", background: dark ? "#0a0d11" : "#e6e0d0" }}>
        <div className="recompute-card" style={{ maxWidth: 360, textAlign: "center" }}>
          <div className="rc-t">Mapbox token required</div>
          <div className="rc-sub" style={{ marginTop: 8 }}>
            Set <code>VITE_MAPBOX_TOKEN</code> in <code>frontend/.env</code> to render the Standard basemap. See <code>.env.example</code>.
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      <div id="map" className={placing && hoverStreet ? "on-street" : ""} style={{ position: "absolute", inset: 0 }}>
        <Map
          ref={mapRef}
          mapboxAccessToken={MAPBOX_TOKEN}
          initialViewState={{ longitude: MAP_CENTER[0], latitude: MAP_CENTER[1], zoom: MAP_ZOOM, pitch: 52, bearing: -18 }}
          mapStyle={STANDARD_STYLE}
          // Flat Mercator at every zoom — Mapbox's default 'globe' curves the
          // earth when you zoom out, which looks wrong for a city twin. Mercator
          // keeps the zoomed-out view a proper flat plane like the close-up.
          projection={{ name: "mercator" }}
          reuseMaps
          cursor="grab"
          onLoad={(e) => {
            const m = e.target;
            const st = useAppStore.getState();
            applyLightPreset(m as never, lightPresetForMinute(st.scrubberMinute, st.dayOfYear));
            setShow3dObjects(m as never, true);
            addEarlyBuildings(m as never, st.theme === "dark");
          }}
          onClick={(e) => {
            if (placing) void placeAt([e.lngLat.lng, e.lngLat.lat]);
          }}
          style={{ position: "absolute", inset: 0 }}
        >
          <DeckOverlay
            layers={layers}
            onClick={(info) => {
              // Click-away deselect: any non-pin click while not placing clears the
              // current object selection. Placement clicks are handled by <Map onClick>.
              if (placingRef.current) return;
              if (info.layer?.id === "pins") return;
              const st = useAppStore.getState();
              if (st.selectedId != null) st.selectObject(null);
            }}
          />
        </Map>
      </div>

      <div className="vp-hud tr">
        <button className="iconbtn" onClick={() => useAppStore.getState().recenter()} title="Recenter">
          <Icon.recenter />
        </button>
        <button
          className="iconbtn"
          onClick={() => useAppStore.getState().toggleTilt()}
          title={tiltOn ? "Top-down view" : "3-D view"}
        >
          {tiltOn ? (
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <rect x="2.5" y="2.5" width="11" height="11" rx="1.5" />
              <path d="M2.5 6.5h11M6.5 2.5v11" />
            </svg>
          ) : (
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M8 2.3l5.7 3.1-5.7 3.1-5.7-3.1z" />
              <path d="M2.3 8.4v4.3l5.7 3.1 5.7-3.1V8.4" />
            </svg>
          )}
        </button>
        <div className="layers-wrap">
          <button
            className={`iconbtn ${layersOpen ? "on" : ""}`}
            onClick={() => setLayersOpen((v) => !v)}
            title="Map layers"
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M8 1.8l6.2 3.1L8 8 1.8 4.9z" />
              <path d="M1.8 8l6.2 3.1L14.2 8" />
              <path d="M1.8 11.1l6.2 3.1 6.2-3.1" />
            </svg>
          </button>
          {layersOpen && (
            <div className="layers-menu">
              <div className="lm-title">Map layers</div>
              {(
                [
                  ["poi", "POI labels"],
                  ["transit", "Transit"],
                  ["roadLabels", "Road labels"],
                  ["placeLabels", "Place labels"],
                  ["buildings3d", "3-D buildings"],
                ] as [keyof typeof overlays, string][]
              ).map(([key, label]) => (
                <label key={key} className="lm-row">
                  <input
                    type="checkbox"
                    checked={overlays[key]}
                    onChange={(e) => setOverlays((o) => ({ ...o, [key]: e.target.checked }))}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="vp-hud bl">
        <div className="vp-chip">
          <span className="lt" style={{ marginRight: 4 }}>EDGE PRESSURE</span>
          <span style={{ width: 110, height: 7, borderRadius: 999, display: "inline-block",
            background: "linear-gradient(90deg,var(--c-free),var(--c-light),var(--c-mod),var(--c-heavy),var(--c-sev))" }} />
        </div>
      </div>
      {planStaged && (
        <div className="vp-hud bc">
          <div className="plan-bar">
            <span className="pb-ico"><Icon.check /></span>
            <span className="pb-tx">
              <span className="pb-t">Copilot plan ready</span>
              <span className="pb-s">Apply to recompute the network with the proposed actions</span>
            </span>
            <button className="btn primary btn-sm" onClick={() => void applyPlan()}>Apply &amp; recompute</button>
            <button className="btn ghost btn-sm" onClick={() => discardPlan()}>Discard</button>
          </div>
        </div>
      )}

      <div id="recompute" className={recomputing ? "show" : ""}>
        <div className="recompute-card">
          <div className="rc-hd">
            <span className="rc-spin" />
            <span className="rc-t">{recomputeTitle || "Recomputing…"}</span>
            <span className="rc-sub">{Math.min(100, Math.round((recomputeStep / RECOMPUTE_STEPS.length) * 100))}%</span>
          </div>
          <div className="rc-track">
            <div className="rc-bar" style={{ width: `${Math.min(100, (recomputeStep / RECOMPUTE_STEPS.length) * 100)}%` }} />
          </div>
          <div className="rc-steps">
            {RECOMPUTE_STEPS_LABEL.map((s, i) => (
              <span key={s} className={`rc-step ${i < recomputeStep ? "done" : ""} ${i === recomputeStep ? "active" : ""}`}>
                <span className="sd" />
                {s}
              </span>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
