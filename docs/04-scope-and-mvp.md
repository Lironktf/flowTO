# 04 — Scope & MVP

## Scope decision (locked 2026-05-29)
- **Coverage: ALL of Toronto.** We have the data + 121 GiB + GB10. Achieved via **mesoscopic
  city-wide sim** (link-level flows) with **microscopic zoom-in** for the animated detail.
  → Don't attempt car-by-car micro-sim citywide; that's the trap. See `02-architecture.md`.
- **3 layers:** (1) Cars w/ directionality, (2) Public transit (TTC + GO + UP, schedule-driven),
  (3) Pedestrians.
- **Hero scenario:** FIFA World Cup match-day surge at BMO Field.

## Realistic fidelity note
"All of Toronto" applies to **coverage + visualization + transit schedules** (all real, citywide).
Traffic *dynamics* are mesoscopic citywide and micro only where you zoom. This is the honest,
defensible framing — say it that way to judges. It's a strength (scales), not a limitation.

## MVP — must-haves (demo-critical)
- [ ] 3D Toronto map: extruded building outlines + all 3 layers toggleable
- [ ] Time-of-day / date scrubber driving transit + demand
- [ ] Congestion heatmap that visibly responds to changes
- [ ] At least these planner edits: **close a link / road**, **reduce lanes**, **add construction zone**, **scale demand at a zone**
- [ ] Nemotron copilot: NL → scenario edit → run → spoken-language result summary (≥2 real queries)
- [ ] Auto-optimizer: one constrained problem, returns a plan that improves the metric, one-click apply
- [ ] The World Cup before/after: heatmap red → green with a headline metric (e.g. "−32% commute")

## Nice-to-haves (only if ahead)
- [ ] Bike routes as a 4th layer
- [ ] Bylaw citations in copilot answers (retrieval)
- [ ] Cost/budget constraint surfaced in optimizer UI
- [ ] Multiple saved scenarios + side-by-side compare
- [ ] Signal-timing optimization (not just reroutes)

## Explicit CUTS (don't build for the hackathon)
- ❌ Car-by-car micro-sim of the entire city
- ❌ Photorealistic 3D buildings (outlines only)
- ❌ Real-time data feeds / live sensors
- ❌ User accounts, persistence DB, multi-tenant
- ❌ Mobile / responsive polish
- ❌ Perfect calibration to ground-truth counts (believable > perfect)

## Risk register
| Risk | Mitigation |
|---|---|
| GTFS + map-matching eats all the time | Pre-bake before event; one teammate owns the data pipeline end-to-end |
| Sim too slow / unstable live | Mesoscopic + deterministic seeds; pre-compute the demo scenario; have a recorded fallback |
| Nemotron pull/serve issues | Test Ollama early; keep a cached fallback model; structured-output prompt tested offline |
| Optimizer doesn't converge in time | Start with greedy/bandit baseline that always returns *something* better; RL is the upgrade |
| "All of Toronto" overpromise | Use the mesoscopic framing above; demo zoom-in for the wow |
| Frontend ⇆ backend streaming jank | Throttle WS updates; downsample agents sent to browser |

## Suggested team split (3–5)
- **Data/sim owner** — OSMnx graph, GTFS, demand, SUMO/Warp engine
- **Frontend owner** — deck.gl map, layers, controls, WS client
- **AI owner** — Nemotron copilot (intent→config, summaries) + optimizer/Verifiers
- **Glue/PM/demo owner** — FastAPI, scenario state, demo script, pitch (floats to bottlenecks)
