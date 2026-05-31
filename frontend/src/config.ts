/**
 * UI-only configuration (NOT simulation data).
 * All traffic numbers, pressures, metrics, and copilot answers come from the
 * live backend (`/edges`, `/demo/run`, `/scenarios/...`, `/copilot/plan`).
 * This file only holds map framing + static UI labels.
 */
export const MAP_CENTER: [number, number] = [-79.4163, 43.6362];
export const MAP_ZOOM = 13.2;

// BMO Field / Exhibition Place — an event marker (geography, not sim data).
export const STADIUM = {
  name: "Toronto Stadium",
  sub: "BMO Field · Exhibition Place",
  coord: [-79.4185, 43.6332] as [number, number],
};

// Full-day timeline (minutes since midnight). The scrubber drives both the
// Mapbox Standard light preset and the congestion-over-time chart.
export const TIMELINE = {
  startMin: 0,
  endMin: 24 * 60,
  step: 15,
  defaultMin: 8 * 60,
};

// Default day-of-year for the season control. Wed 10 Jun 2026 = day 161 — chosen
// because TMC counts are gathered on Tue/Wed/Thu, so a Wednesday gives the richest,
// near-24h measured baseline (Mon/Fri have little-to-no survey data).
export const DEFAULT_DAY_OF_YEAR = 161;

// Edit-mode tools — exactly two, per the spec.
//   closure: pick TWO intersections → seal the corridor between them
//   surge:   pick ONE intersection → inject event trips
export const TOOLS = [
  { id: "closure", name: "Full closure", desc: "Seal the corridor between two intersections", vertices: 2 },
  { id: "surge", name: "Demand change", desc: "Add or remove trips along a chosen street and direction", vertices: 1 },
] as const;

// Copilot input suggestions (the *prompts*; answers come from /copilot/plan).
export const COPILOT_CHIPS = [
  "Where is congestion worst right now?",
  "Ease gridlock near BMO Field without breaking bylaws.",
  "What happens if I close Lake Shore both ways?",
];

// Engine summary metric → display label (what the backend actually computes).
export const METRIC_LABELS: Record<string, string> = {
  average_pressure: "Average pressure",
  active_edges: "Loaded edges",
  high_risk_edges: "High-risk edges",
  severe_edges: "Severe edges",
  total_assigned_trips: "Assigned trips",
};
export const METRIC_ORDER = [
  "average_pressure",
  "severe_edges",
  "high_risk_edges",
  "active_edges",
] as const;
export const LOWER_IS_BETTER = new Set(["average_pressure", "severe_edges", "high_risk_edges"]);

export const DEMO_DEVICE = "DGX Spark · GB10";

// Recompute overlay stepper labels.
export const RECOMPUTE_STEPS_LABEL = ["Demand", "Assign", "Pressure", "Bylaw", "Render"];
