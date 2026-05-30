/**
 * Map canvas: MapLibre basemap + interleaved deck.gl overlay (research/06).
 * Corridors are a PathLayer colored by the congestion ramp for the current
 * network state; a cobalt blast-radius halo underlays affected corridors when
 * the event has fired. Offline-safe: the basemap is a flat paper background
 * (PMTiles can slot in via VITE_PMTILES later).
 */
import { MapboxOverlay } from "@deck.gl/mapbox";
import { PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useMemo } from "react";
import { Map, useControl } from "react-map-gl/maplibre";
import { actions, blastRadius, center, corridors, stadium } from "../data/demo";
import { pressureRamp, type RGB } from "../lib/pressureRamp";
import { useAppStore } from "../state/appStore";

function DeckOverlay(props: { layers: unknown[] }) {
  const overlay = useControl(() => new MapboxOverlay({ interleaved: true, layers: [] }));
  // @ts-expect-error deck typing for layers is loose here
  overlay.setProps({ layers: props.layers });
  return null;
}

const WIDTH_BY_CLASS: Record<string, number> = {
  expressway: 7,
  arterial: 5,
  collector: 3.5,
  local: 2.5,
  transit: 3,
};

function basemapStyle(dark: boolean): maplibregl.StyleSpecification {
  return {
    version: 8,
    sources: {},
    layers: [
      {
        id: "bg",
        type: "background",
        paint: { "background-color": dark ? "#0b0e13" : "#e9e3d4" },
      },
    ],
  };
}

export function MapCanvas() {
  const theme = useAppStore((s) => s.theme);
  const intensity = useAppStore((s) => s.intensity);
  const tilt = useAppStore((s) => s.tilt);
  const networkState = useAppStore((s) => s.networkState);
  const eventFired = useAppStore((s) => s.eventFired);
  const appliedActions = useAppStore((s) => s.appliedActions);
  const selectedEdges = useAppStore((s) => s.selectedEdges);
  const selectEdge = useAppStore((s) => s.selectEdge);
  const dark = theme === "dark";

  const layers = useMemo(() => {
    const out: unknown[] = [];

    // Blast-radius cobalt halo beneath affected corridors (event active only).
    if (eventFired) {
      const cobalt: RGB = dark ? [111, 155, 255] : [36, 85, 214];
      out.push(
        new PathLayer({
          id: "blast-halo",
          data: corridors.filter((c) => blastRadius.includes(c.id)),
          getPath: (c: (typeof corridors)[number]) => c.path,
          getColor: [...cobalt, 70],
          getWidth: (c: (typeof corridors)[number]) => (WIDTH_BY_CLASS[c.cls] ?? 3) + 10,
          widthUnits: "pixels",
          capRounded: true,
          jointRounded: true,
        }),
      );
    }

    // Corridors colored by pressure for the current network state.
    out.push(
      new PathLayer({
        id: "corridors",
        data: corridors,
        pickable: true,
        getPath: (c: (typeof corridors)[number]) => c.path,
        getColor: (c: (typeof corridors)[number]) => {
          const p = c[networkState];
          return pressureRamp(p, { intensity, dark });
        },
        getWidth: (c: (typeof corridors)[number]) =>
          (WIDTH_BY_CLASS[c.cls] ?? 3) + (selectedEdges.has(c.id) ? 4 : 0),
        widthUnits: "pixels",
        capRounded: true,
        jointRounded: true,
        updateTriggers: {
          getColor: [networkState, intensity, dark],
          getWidth: [Array.from(selectedEdges).join(",")],
        },
        onClick: (info: { object?: (typeof corridors)[number] }) => {
          if (info.object) selectEdge(info.object.id, true);
        },
      }),
    );

    // Stadium pin (always on).
    out.push(
      new ScatterplotLayer({
        id: "stadium",
        data: [stadium],
        getPosition: (d: typeof stadium) => d.coord,
        getRadius: 60,
        radiusUnits: "meters",
        getFillColor: dark ? [111, 155, 255] : [36, 85, 214],
        stroked: true,
        getLineColor: [255, 255, 255],
        lineWidthMinPixels: 2,
      }),
    );

    // Intervention markers (after a plan is applied).
    if (appliedActions.length) {
      const placed = actions.filter((a) => appliedActions.includes(a.id));
      out.push(
        new ScatterplotLayer({
          id: "action-dots",
          data: placed,
          getPosition: (a: (typeof actions)[number]) => a.coord,
          getRadius: 40,
          radiusUnits: "meters",
          getFillColor: dark ? [111, 155, 255, 230] : [36, 85, 214, 230],
        }),
      );
      out.push(
        new TextLayer({
          id: "action-labels",
          data: placed,
          getPosition: (a: (typeof actions)[number]) => a.coord,
          getText: (_a: (typeof actions)[number], { index }: { index: number }) =>
            String(index + 1),
          getSize: 13,
          getColor: [255, 255, 255],
          fontFamily: "IBM Plex Mono, monospace",
        }),
      );
    }
    return out;
  }, [networkState, intensity, dark, eventFired, appliedActions, selectedEdges, selectEdge]);

  return (
    <Map
      mapLib={maplibregl as never}
      initialViewState={{
        longitude: center[0],
        latitude: center[1],
        zoom: 14.1,
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
