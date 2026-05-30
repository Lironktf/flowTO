# 05 — Demo Script (target: 90 seconds)

> **P12 update (road-centric fix):** the *measured* mitigation is now **road-side**
> — eastbound contraflow on Lake Shore Blvd W, signal retiming at Dufferin &
> Strachan, and a pedestrian corridor on Princes' Blvd, recomputed via
> blast-radius. The **509 / 511** streetcars appear as a transit **visual**
> ("+frequency / priority hold"), not a measured rider model (transit is
> visual-only per the scope decision). The canonical, click-by-click
> run-of-show now lives in **`demo/RUNBOOK.md`**; this file is the original
> narrative draft.

The demo IS the product. Optimize everything for this narrative. Pre-load the scenario;
never debug live.

## Beat-by-beat
1. **Open (10s):** "This is Toronto — every road, every TTC line, GO, and UP Express, all
   running locally on this one NVIDIA Spark. No cloud." Spin the 3D map, toggle the 3 layers.
2. **Set the clock (10s):** Scrub to a weekday 5pm. Heatmap shows normal rush hour. "This is
   today's commute, schedule-accurate."
3. **The stakes (10s):** "Now — World Cup final at BMO Field. 45,000 fans." Apply the match-day
   surge. Heatmap around Exhibition + Gardiner goes **deep red**. Streetcars overload.
4. **Talk to it (20s):** Type to the copilot: *"Ease the post-match gridlock around BMO Field
   without breaking any bylaws."* Nemotron (local) parses it, proposes edits, runs the sim.
5. **The fix (20s):** Watch it apply — contraflow on Lakeshore, +50% on the 509, a pedestrian
   corridor on Bremner, signal retiming. Heatmap melts **red → green**.
6. **The number (10s):** Big metric card: **"Average egress time −32%. $0 capital cost.
   Computed in 4s on-device."**
7. **Close (10s):** "A planner could test a year of scenarios before a single cone goes down —
   entirely on their own hardware." Name-drop: Nemotron (copilot), Verifiers (optimizer),
   GB10/Arm (all local).

## What MUST work on stage
- [ ] The 3-layer toggle + smooth 3D
- [ ] The surge → red heatmap (the "oh no" moment)
- [ ] One copilot query that lands (rehearsed exact wording)
- [ ] The red → green transition (the "wow" moment)
- [ ] One headline metric, clearly displayed

## Fallbacks
- Pre-recorded screen capture of the full run if the live box hiccups.
- "Canned" optimizer result cached so step 5 never waits on convergence.
- Copilot: if intent parsing flakes, a button that fires the same scenario JSON.

## Judge-facing talking points (map to rubric)
- **Impact:** real planning tool, real Toronto data, timely (WC2026).
- **Technical:** mesoscopic GPU sim citywide + micro zoom; local LLM; RL optimizer-in-the-loop.
- **Local/Spark:** sim + Nemotron + optimizer all on one GB10, 121 GiB unified, no cloud.
- **Bounties:** explicitly say "Nemotron drives this, Verifiers scores our plans, all on Arm."
