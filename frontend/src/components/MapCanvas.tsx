/**
 * Viewport: MapLibre basemap + interleaved deck.gl, rendering the REAL graph
 * recolored by live engine pressures (tick store). Camera eases 3-D (Simulate)
 * ↔ top-down (Edit); Edit mode click-to-place drops pins via nearest-edge snap.
 * HUD (mode banner, recenter/tilt, legend, plan bar) + recompute overlay live
 * here as absolutely-positioned overlays inside #viewport.
 */
import { MapboxOverlay } from "@deck.gl/mapbox";
import { PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef, useState } from "react";
import { Map, useControl, type MapRef } from "react-map-gl/maplibre";
import { api } from "../api/client";
import { MAP_CENTER, MAP_ZOOM, RECOMPUTE_STEPS_LABEL, STADIUM } from "../config";
import { buildTransitLayers, type RouteGeom, type Trajectory } from "../layers/transit";
import { pressureRamp } from "../lib/pressureRamp";
import { RECOMPUTE_STEPS, useAppStore } from "../state/appStore";
import { getArrays } from "../state/tickStore";
import { Icon } from "./Icons";

function DeckOverlay(props: { layers: unknown[] }) {
  const overlay = useControl(() => new MapboxOverlay({ interleaved: true, layers: [] }));
  // @ts-expect-error deck layer typing is loose here
  overlay.setProps({ layers: props.layers });
  return null;
}

const WIDTH_BY_CLASS: Record<string, number> = {
  motorway: 6, trunk: 5, primary: 4.5, secondary: 3.5, tertiary: 3, residential: 2, service: 1.5,
};
const PIN_COLOR: Record<string, [number, number, number]> = {
  closure: [224, 112, 27], lane: [224, 162, 26], oneway: [36, 85, 214],
  signal: [36, 85, 214], surge: [210, 58, 50], transit: [31, 157, 87],
};

interface EdgePath { edge_id: string; idx: number; road_class: string; path: [number, number][]; }

function basemapStyle(dark: boolean): maplibregl.StyleSpecification {
  return {
    version: 8,
    sources: {},
    layers: [{ id: "bg", type: "background", paint: { "background-color": dark ? "#0a0d11" : "#e6e0d0" } }],
  };
}

export function MapCanvas() {
  const mapRef = useRef<MapRef | null>(null);
  const theme = useAppStore((s) => s.theme);
  const intensity = useAppStore((s) => s.intensity);
  const view = useAppStore((s) => s.view);
  const edges = useAppStore((s) => s.edges);
  const pressureSeq = useAppStore((s) => s.pressureSeq);
  const objects = useAppStore((s) => s.objects);
  const selectedId = useAppStore((s) => s.selectedId);
  const activeTool = useAppStore((s) => s.activeTool);
  const planStaged = useAppStore((s) => s.planStaged);
  const recomputing = useAppStore((s) => s.recomputing);
  const recomputeStep = useAppStore((s) => s.recomputeStep);
  const recomputeTitle = useAppStore((s) => s.recomputeTitle);
  const recenterNonce = useAppStore((s) => s.recenterNonce);
  const tiltOn = useAppStore((s) => s.tiltOn);
  const scrubMin = useAppStore((s) => s.scrubberMinute);
  const placeAt = useAppStore((s) => s.placeAt);
  const selectObject = useAppStore((s) => s.selectObject);
  const applyPlan = useAppStore((s) => s.applyPlan);
  const discardPlan = useAppStore((s) => s.discardPlan);
  const dark = theme === "dark";
  const placing = view === "edit" && activeTool !== "select";

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
  const [trajectories, setTrajectories] = useState<Trajectory[]>([]);
  useEffect(() => {
    let alive = true;
    Promise.all([api.transitRoutes("ttc"), api.transitTrajectories("ttc")])
      .then(([r, t]) => {
        if (!alive) return;
        setRoutes(r.routes.map((x) => ({ route_id: x.route_id, mode: x.mode, path: x.path })));
        setTrajectories(t.trajectories.map((x) => ({ trip_id: x.trip_id, route_type: x.route_type, path: x.path, timestamps: x.timestamps })));
      })
      .catch(() => void 0);
    return () => { alive = false; };
  }, []);

  // Camera: ease pitch/bearing on view + tilt; flyTo on recenter.
  useEffect(() => {
    const m = mapRef.current?.getMap();
    if (!m) return;
    const pitch = view === "edit" ? 0 : tiltOn ? 52 : 0;
    const bearing = view === "edit" ? 0 : tiltOn ? -18 : 0;
    m.easeTo({ pitch, bearing, duration: 700 });
  }, [view, tiltOn]);
  useEffect(() => {
    const m = mapRef.current?.getMap();
    if (!m || recenterNonce === 0) return;
    m.flyTo({ center: MAP_CENTER, zoom: MAP_ZOOM, duration: 900 });
  }, [recenterNonce]);

  const layers = useMemo(() => {
    const out: unknown[] = [];
    const pressure = getArrays().pressure;
    out.push(
      new PathLayer({
        id: "roads",
        data: edgePaths,
        pickable: true,
        getPath: (e: EdgePath) => e.path,
        getColor: (e: EdgePath) => pressureRamp(pressure[e.idx] ?? 0, { intensity, dark }),
        getWidth: (e: EdgePath) => WIDTH_BY_CLASS[e.road_class] ?? 2,
        widthUnits: "pixels",
        widthMinPixels: 1,
        capRounded: true,
        jointRounded: true,
        updateTriggers: { getColor: [pressureSeq, intensity, dark] },
      }),
    );
    if (view === "sim" && routes.length) {
      out.push(...buildTransitLayers(routes, trajectories, scrubMin * 60));
    }
    out.push(
      new ScatterplotLayer({
        id: "stadium", data: [STADIUM], getPosition: (d: typeof STADIUM) => d.coord,
        getRadius: 70, radiusUnits: "meters", getFillColor: dark ? [111, 155, 255] : [36, 85, 214],
        stroked: true, getLineColor: [255, 255, 255], lineWidthMinPixels: 2,
      }),
    );
    const visible = objects.filter((o) => o.visible);
    if (visible.length) {
      out.push(
        new ScatterplotLayer({
          id: "pins", data: visible, pickable: true,
          getPosition: (o: (typeof visible)[number]) => o.coord,
          getRadius: (o: (typeof visible)[number]) => (o.id === selectedId ? 55 : 42),
          radiusUnits: "meters",
          getFillColor: (o: (typeof visible)[number]) => PIN_COLOR[o.type] ?? [36, 85, 214],
          stroked: true,
          getLineColor: (o: (typeof visible)[number]) => (o.id === selectedId ? [36, 85, 214] : [255, 255, 255]),
          lineWidthMinPixels: 2,
          updateTriggers: { getRadius: [selectedId], getLineColor: [selectedId] },
          onClick: (info: { object?: (typeof visible)[number] }) => info.object && selectObject(info.object.id),
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
  }, [edgePaths, pressureSeq, intensity, dark, view, routes, trajectories, scrubMin, objects, selectedId, selectObject]);

  return (
    <>
      <div id="map" style={{ position: "absolute", inset: 0 }}>
        <Map
          ref={mapRef}
          mapLib={maplibregl as never}
          initialViewState={{ longitude: MAP_CENTER[0], latitude: MAP_CENTER[1], zoom: MAP_ZOOM, pitch: 52, bearing: -18 }}
          mapStyle={basemapStyle(dark) as never}
          reuseMaps
          cursor={placing ? "crosshair" : "grab"}
          onClick={(e) => {
            if (placing) void placeAt([e.lngLat.lng, e.lngLat.lat]);
          }}
          style={{ position: "absolute", inset: 0 }}
        >
          <DeckOverlay layers={layers} />
        </Map>
      </div>

      <div className="vp-hud tl">
        <div className="mode-banner">
          <span className="ico">{view === "edit" ? <Icon.pencil /> : <Icon.play />}</span>
          <span className="tx">
            <span className="a">{view === "edit" ? "Editor" : "Simulation"}</span>
            <span className="b">{view === "edit" ? "Top-down" : "3-D camera"}</span>
          </span>
        </div>
      </div>
      <div className="vp-hud tr">
        <button className="iconbtn" onClick={() => useAppStore.getState().recenter()} title="Recenter">
          <Icon.recenter />
        </button>
        {view === "sim" && (
          <button className="iconbtn" onClick={() => useAppStore.getState().toggleTilt()} title="Tilt">
            <Icon.tilt />
          </button>
        )}
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
              <span className="pb-t">Recommended plan</span>
              <span className="pb-s">3 bylaw-valid actions · contraflow + retiming</span>
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
