# FlowTO — A Live Digital Twin of Toronto for City Planners

> *Working name. Spark Hack Series (NVIDIA) submission. 100% local on a DGX Spark / GB10.*

A 3D, layered, time-aware digital twin of Toronto that lets city planners **simulate
how traffic and transit flow** — then toggle closures, reroutes, construction, and
demand surges (e.g. the **FIFA World Cup 2026** at BMO Field) and watch the impact in
real time. An on-device **Nemotron** copilot drives it in plain English, and an
**RL auto-optimizer** proposes the best reroutes/schedules under bylaw + budget constraints.

## Why it wins
- **Track:** Environmental Impact → urban mobility.
- **Hits all three bounties:** Nemotron (NL copilot), Arm (built/tuned on GB10), Prime Intellect/Verifiers (RL optimizer).
- **Timely:** World Cup 2026 is ~2 weeks out; Toronto is a host city.
- **Fully local:** sim + LLM + optimizer all run on the Spark. No cloud.

## Layers (v1)
1. **Cars** — road network with directionality (one-way / bidirectional)
2. **Public transit** — TTC (subway/streetcar/bus) + GO Transit + UP Express, schedule-driven
3. **Pedestrians** — walk network + crowd density

## Repo map
- `docs/` — living planning docs (read these first)
  - `00-hackathon-brief.md` — criteria, tracks, bounties, rules
  - `01-spark-inventory.md` — what's on the box + setup gaps
  - `02-architecture.md` — the 3-layer AI stack + data flow
  - `03-data-sources.md` — Toronto open data, GTFS, OSM
  - `04-scope-and-mvp.md` — scope decisions + cut lines
  - `05-demo-script.md` — the 90-second winning demo
- (code dirs added as we build)

## Compute
NVIDIA **GB10** (Blackwell), CUDA 13.0, **121 GiB unified memory**, 20 ARM cores.
Reached at `asus@gx10-4f5f` (Tailscale `100.124.76.16`).
