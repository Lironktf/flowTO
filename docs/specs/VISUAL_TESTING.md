# VISUAL TESTING — click-through QA for the FlowTO web app (v2 two-view IDE)

How to verify the frontend **by eye in the browser**. The app is now a
two-mode IDE (Blender/Unity-style flush docks): **Simulate** (3-D + NLE
timeline) and **Edit** (top-down + tool rail + click-to-place). All traffic
numbers are **real engine output** from the live backend.

## Launch (the API is REQUIRED)
```bash
# terminal 1 — backend (loads the real 18,190-edge graph; warms the demo cache)
cd ~/flowTO-build && scripts/run_api.sh           # http://localhost:8000
# terminal 2 — frontend dev server (proxies /api → :8000)
cd ~/flowTO-build/frontend && npm run dev          # http://localhost:5173
```
Open **:5173** in a wide desktop window (designed at 1440×900). `npm run preview`
(no proxy) will show "Could not reach the API" — use `npm run dev` with the API
up. Give the server ~a minute after boot so the demo cache warms (first surge is
otherwise a ~tens-of-seconds full-graph solve).

> Basemap is a flat paper/near-black ground by design (offline-safe). The
> colored lines on top are the **real road graph** recolored by engine pressure.

## First-run → load
**Do:** open the page → click **Load the twin**.
**See:** paper splash (eyebrow, "A live digital twin of **Toronto**.", three
stats, boot log) fades out; the IDE shell appears with the real road network
drawn on the map.
**✅** top bar shows `FlowTO`, a **Simulate / Edit** segmented switch, scenario
tag, green **"Baseline · nominal"** status; status bar shows the real edge count
+ `DGX Spark · GB10`.

## Simulate view (default)
1. **Baseline** — left dock = *Scenarios*; right dock = *Before / After*
   ("Network nominal"); bottom = **NLE timeline** (transport, clock `14:00`,
   ruler, **kickoff** + **full-time** diamonds, Congest/Demand/Plan tracks with
   `MATCH 90'` + red `EGRESS 45k` clips); Copilot region below the metrics.
2. **Scrub / play** — drag the playhead or hit **play**; crossing **17:05**
   (full-time) auto-fires the surge. Speed selector 0.5–4×.
3. **Surge** — recompute overlay (5 stepper dots) → corridors recolor toward
   **red**, status red **"Post-match surge · gridlock"**, Before/After flips to
   **"Baseline → Event"** with real ↑ deltas (avg pressure / severe / high-risk
   / loaded edges) + a red "cut-through risk" row; a **plan bar** appears
   bottom-center of the map.
4. **A·B toggle** — the *Before / After* header toggle repaints the map between
   the two real snapshots.
5. **Apply & recompute** (plan bar) → recompute → corridors ease back, status
   green **"Mitigated · plan applied"**, Before/After = **"Event → Mitigated"**,
   Plan track gets a **CONTRAFLOW + 509/511** clip, "Plan valid" row.

## Edit view (click the **Edit** segment)
**See:** camera flattens to **top-down**; the **tool rail** appears (left edge:
Select + 5 interventions, keys **1–5**, **Esc**); left dock = *Interventions* +
*Scene*; right dock = *Inspector*; the timeline hides.
1. **Place** — click a rail tool (or press 1–5), cursor becomes a crosshair,
   click the map → a numbered **pin** drops, the **Scene** outliner gains a row,
   the **Inspector** fills (it snaps to the nearest real road — e.g. "Lake Shore
   Boulevard West" — and shows lat/lng + edge id), and a short **blast-radius**
   recompute repaints the network. Status → "Edited · recomputed".
2. **Select / delete** — click a pin or Scene row to select (Inspector updates);
   Delete removes it. Eye icon toggles visibility.

## Copilot (both views)
- **Hero**: chip *"Ease post-match gridlock…"* → real `/copilot/plan` reply with
  the 3-step plan + **bylaw citations** (§ Ch. 950, King St, Ch. 880, AODA);
  stages the plan bar (models the surge first if needed).
- **Blocked**: chip *"Just close Lake Shore both ways."* → refusal citing Ch. 880
  + TTC; status briefly amber **"Action blocked"**; network unchanged.

## Cross-cutting
- **Theme** (moon icon): light "paper" ↔ dark "ops" — whole shell + ramp flip.
- **Dock toggles** (top-right cluster): collapse left/bottom/right docks (grid
  animates closed).
- **Recenter / Tilt** (map top-right): fly back to downtown / toggle 3-D pitch.
- **Reset** (top bar): back to baseline, scene cleared.

## ✅ Green looks like
- Real road network renders; surge recolors it; A·B repaints; Edit placement
  drops pins on real roads and recomputes; copilot cites real bylaws.
- Backend `pytest -q` green; `npm run build` + `npm run test` (12) green.

## If something's off
- **"Could not reach the API"** → API not running, or you used `preview`. Start
  `scripts/run_api.sh` and use `npm run dev`.
- **404 on `/scenarios/.../records`** → a stale API server (predates the
  endpoint) is still bound to :8000 — kill it and restart `run_api.sh`.
- **First surge slow** → cache still warming; wait ~a minute after boot.
- **Blank page** → check the devtools console; usually a missing `npm install`.
