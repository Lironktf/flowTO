/**
 * UI-only configuration (NOT simulation data).
 * All traffic numbers, pressures, metrics, and copilot answers come from the
 * live backend (`/edges`, `/demo/run`, `/scenarios/.../compare`, `/copilot/plan`).
 * This file only holds map framing + static UI labels.
 */
export const MAP_CENTER: [number, number] = [-79.4163, 43.6362];
export const MAP_ZOOM = 13.2;

// BMO Field / Exhibition Place — the event marker (geography, not sim data).
export const STADIUM = {
  name: "Toronto Stadium",
  sub: "BMO Field · Exhibition Place",
  coord: [-79.4185, 43.6332] as [number, number],
};

// Matchday scrubber bounds (minutes since midnight).
export const TIMELINE = {
  startMin: 14 * 60,
  endMin: 20 * 60,
  step: 15,
  kickoff: 15 * 60,
  fulltime: 17 * 60 + 5,
  dow: "FRI · 12 JUN 2026",
};

// Intervention tool palette (labels only; behavior runs through the API).
export const TOOLS = [
  { id: "closure", name: "Full closure", desc: "Close a segment to all traffic" },
  { id: "lane", name: "Lane reduction", desc: "Reduce corridor capacity" },
  { id: "oneway", name: "Temporary one-way", desc: "Set contraflow / directional egress" },
  { id: "signal", name: "Signal retiming", desc: "Adjust cycle splits & offsets" },
  { id: "surge", name: "Demand surge", desc: "Inject an event trip spike" },
];

// Scenario list labels (the active one drives the demo run).
export const SCENARIOS = [
  { id: "sc1", badge: "JUN 12", active: true, name: "FIFA WC26 — Post-match egress", meta: "Canada vs UEFA-A · 45,000 · FT 17:05" },
  { id: "sc2", badge: "PLAN", name: "Gardiner — Jarvis ramp closure", meta: "Capital works · 6 wks" },
  { id: "sc3", badge: "DRAFT", name: "TTC Line 1 — bus bridge", meta: "St George ↔ Bloor-Yonge" },
  { id: "sc4", badge: "STUDY", name: "King St transit-priority ext.", meta: "Bathurst → Dufferin" },
];

// Copilot input suggestions (the *prompts*; answers come from /copilot/plan).
export const COPILOT_CHIPS = [
  "Ease post-match gridlock near BMO Field without breaking bylaws.",
  "Just close Lake Shore both ways.",
  "Protect Parkdale local streets from cut-through.",
];

// Engine summary metric → display label (what the backend actually computes).
export const METRIC_LABELS: Record<string, string> = {
  average_pressure: "Average pressure",
  active_edges: "Loaded edges",
  high_risk_edges: "High-risk edges",
  severe_edges: "Severe edges",
  total_assigned_trips: "Assigned trips",
};
// Order shown in Before/After; lower-is-better drives delta coloring.
export const METRIC_ORDER = [
  "average_pressure",
  "severe_edges",
  "high_risk_edges",
  "active_edges",
] as const;
export const LOWER_IS_BETTER = new Set([
  "average_pressure",
  "severe_edges",
  "high_risk_edges",
]);

export const DEMO_DEVICE = "DGX Spark · GB10";
