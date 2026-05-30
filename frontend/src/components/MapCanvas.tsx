/**
 * Map canvas: MapLibre basemap + interleaved deck.gl overlay (research/06).
 * Renders the **real Toronto road graph** (`/edges` geometry) colored by live
 * engine pressures from the tick store (written by /demo/run, indexed by edge
 * idx). Recolor is driven imperatively by a bumped `pressureSeq` in
 * updateTriggers — geometry is uploaded once. Transit comes from the API.
 */
import { MapboxOverlay } from "@deck.gl/mapbox";
import { PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useState } from "react";
import { Map, useControl } from "react-map-gl/maplibre";
import { api } from "../api/client";
import { MAP_CENTER, MAP_ZOOM, STADIUM } from "../config";
import { buildTransitLayers, type RouteGeom, type Trajectory } from "../layers/transit";
import { pressureRamp } from "../lib/pressureRamp";
import { getArrays } from "../state/tickStore";
import { useAppStore } from "../state/appStore";

function DeckOverlay(props: { layers: unknown[] }) {
  const overlay = useControl(() => new MapboxOverlay({ interleaved: true, layers: [] }));
  // @ts-expect-error deck typing for layers is loose here
  overlay.setProps({ layers: props.layers });
  return null;
}

const WIDTH_BY_CLASS: Record<string, number> = {
  motorway: 6,
  trunk: 5,
  primary: 4.5,
  secondary: 3.5,
  tertiary: 3,
  residential: 2,
  service: 1.5,
};

interface EdgePath {
  edge_id: string;
  idx: number;
  road_class: string;
  path: [number, number][];
}

function basemapStyle(dark: boolean): maplibregl.StyleSpecification {
  return {
    version: 8,
    sources: {},
    layers: [
      { id: "bg", type: "background", paint: { "background-color": dark ? "#0b0e13" : "#e9e3d4" } },
    ],
  };
}

export function MapCanvas() {
  const theme = useAppStore((s) => s.theme);
  const intensity = useAppStore((s) => s.intensity);
  const tilt = useAppStore((s) => s.tilt);
  const edges = useAppStore((s) => s.edges);
  const pressureSeq = useAppStore((s) => s.pressureSeq);
  const selectedEdges = useAppStore((s) => s.selectedEdges);
  const selectEdge = useAppStore((s) => s.selectEdge);
  const showTransit = useAppStore((s) => s.showTransit);
  const scrubberMinute = useAppStore((s) => s.scrubberMinute);
  const dark = theme === "dark";

  // Real graph geometry → deck paths ([lat,lng] stored → [lng,lat] for deck).
  const edgePaths: EdgePath[] = useMemo(() => {
    const out: EdgePath[] = [];
    for (const e of edges) {
      if (!e.geometry || e.geometry.length < 2) continue;
      out.push({
        edge_id: e.edge_id,
        idx: e.idx,
        road_class: e.road_class ?? "residential",
        path: e.geometry.map(([lat, lng]) => [lng, lat] as [number, number]),
      });
    }
    return out;
  }, [edges]);

  // Transit (routes + trajectories) fetched from the API.
  const [routes, setRoutes] = useState<RouteGeom[]>([]);
  const [trajectories, setTrajectories] = useState<Trajectory[]>([]);
  useEffect(() => {
    let alive = true;
    Promise.all([api.transitRoutes("ttc"), api.transitTrajectories("ttc")])
      .then(([r, t]) => {
        if (!alive) return;
        setRoutes(r.routes.map((x) => ({ route_id: x.route_id, mode: x.mode, path: x.path })));
        setTrajectories(
          t.trajectories.map((x) => ({
            trip_id: x.trip_id,
            route_type: x.route_type,
            path: x.path,
            timestamps: x.timestamps,
          })),
        );
      })
      .catch(() => void 0);
    return () => {
      alive = false;
    };
  }, []);

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
        getWidth: (e: EdgePath) =>
          (WIDTH_BY_CLASS[e.road_class] ?? 2) + (selectedEdges.has(e.edge_id) ? 4 : 0),
        widthUnits: "pixels",
        widthMinPixels: 1,
        capRounded: true,
        jointRounded: true,
        updateTriggers: {
          getColor: [pressureSeq, intensity, dark],
          getWidth: [Array.from(selectedEdges).join(",")],
        },
        onClick: (info: { object?: EdgePath }) => {
          if (info.object) selectEdge(info.object.edge_id, true);
        },
      }),
    );

    // Stadium pin (geography).
    out.push(
      new ScatterplotLayer({
        id: "stadium",
        data: [STADIUM],
        getPosition: (d: typeof STADIUM) => d.coord,
        getRadius: 70,
        radiusUnits: "meters",
        getFillColor: dark ? [111, 155, 255] : [36, 85, 214],
        stroked: true,
        getLineColor: [255, 255, 255],
        lineWidthMinPixels: 2,
      }),
    );

    if (showTransit && routes.length) {
      out.push(...buildTransitLayers(routes, trajectories, scrubberMinute * 60));
    }
    return out;
  }, [
    edgePaths,
    pressureSeq,
    intensity,
    dark,
    selectedEdges,
    selectEdge,
    showTransit,
    routes,
    trajectories,
    scrubberMinute,
  ]);

  return (
    <Map
      mapLib={maplibregl as never}
      initialViewState={{
        longitude: MAP_CENTER[0],
        latitude: MAP_CENTER[1],
        zoom: MAP_ZOOM,
        pitch: tilt,
        bearing: -18,
      }}
      mapStyle={basemapStyle(dark) as never}
      reuseMaps
      style={{ position: "absolute", inset: 0 }}
    >
      <DeckOverlay layers={layers} />
    </Map>
  );
}
