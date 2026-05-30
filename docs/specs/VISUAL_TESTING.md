# VISUAL TESTING — click-through QA for the FlowTO web app

How to verify the frontend **by eye in the browser**, screen by screen. Each
step lists what to do, what you should see, and the ✅ pass criteria. The 6
states below were confirmed in-browser on 2026-05-30.

## Launch (the API is REQUIRED — the app renders real engine data)
```bash
# terminal 1 — backend (loads the real 18,190-edge graph; first start ~30–60s)
cd ~/flowTO-build && scripts/run_api.sh           # http://localhost:8000  (warms the demo cache)
# terminal 2 — frontend dev server (proxies /api → :8000)
cd ~/flowTO-build/frontend && npm run dev          # http://localhost:5173
```
Open **:5173** in a desktop browser (designed at **1440×900** — use a wide window).
> The frontend talks to the live backend: real graph (`/edges`), real engine
> pressures (`/demo/run`), real before/after, real copilot (`/copilot/plan`).
> `npm run preview` (static, no proxy) shows "Could not reach the API" on **Load
> the twin** — use `npm run dev` with the API up, or set `VITE_API_BASE`.
>
> **First surge run is slow (~tens of seconds)** — a full-graph solve. The server
> **warms the cache at startup**, so after ~a minute the surge/fix clicks are
> fast. The Recompute perf cell shows the real measured latency.

> **Note on the map:** the basemap is a flat "drafting-paper" background by
> design (offline-safe — no street tiles needed). The colored **road corridors**
> drawn on top are the map content. That's expected, not a broken tile layer.

---

## State 1 — First-run splash
**Do:** load the page.
**See:** full-screen paper background with a faint blueprint grid; small mono
eyebrow "SPARK HACK · NVIDIA · LOCAL-FIRST"; large serif headline **"A live
digital twin of Toronto."** (the word *Toronto* in cobalt blue); a lede
paragraph; three stats (**18,190** road edges · **~45,000** egress · **<100ms**
blast-radius); a cobalt **"Load the twin"** button; typed boot lines underneath.
**✅ Pass:** headline + 3 stats + button render; fonts are serif (headline) /
mono (stats labels), not default Times/Arial.

## State 2 — Baseline / nominal
**Do:** click **Load the twin**.
**See:** the map canvas with road corridors in mostly **green/amber**; floating panels:
- **Top bar**: `Flow` + cobalt `TO`, "DIGITAL TWIN · TORONTO", a "FIFA WC26" tag,
  a **green** status chip **"Baseline · nominal"**, and `Transit` / `Dark` / `Reset` buttons.
- **Left** "Interventions": a 2-col grid of 5 tools (Full closure, Lane reduction,
  Temporary one-way, Signal retiming, Demand surge) + a Scenarios list.
- **Right** "Before / After": the hint *"Network nominal — apply an intervention…"*.
- **Bottom-right** "Copilot · Nemotron · on-device" with an intro line, 3 chips, input.
- **Centered bottom** time scrubber (clock `14:00`, `FRI · 12 JUN 2026`, a heat rail).
- **Bottom-left** perf strip (Recompute / Affected subgraph / LLM / fps / `DGX Spark · GB10`).
- **Legend** "Edge pressure" green→red ramp.
**✅ Pass:** all panels visible and non-overlapping; status chip dot is green.

## State 3 — Recomputing (the HERO moment)
**Do:** scrub the time slider past **17:05**, OR click any intervention tool, OR
send the hero copilot chip.
**See:** a centered **recompute overlay** above the scrubber — eyebrow
"RECOMPUTING NETWORK", a step name (Demand model → Trip assignment → Edge
pressure → Bylaw check → Render), a progress bar, and **5 step pips** filling
cobalt; the top status chip turns cobalt **"Recomputing…"**; perf strip numbers
animate up. Lasts ~1.7s.
**✅ Pass:** overlay appears, pips fill left→right, then it disappears.

## State 4 — Surge (gridlock)
**Do:** (after State 3 fires from the surge trigger.)
**See:** corridors turn **deep red**, a translucent **cobalt blast-radius halo**
underlays the affected corridors; status chip **red "Post-match surge ·
gridlock"**; Before/After flips to **"Baseline → Event"** with worsening numbers
(**Total network delay 4,180 veh·h**, etc.) and a **red** warning row
*"34% local-road infiltration…"*.
**✅ Pass:** red corridors + cobalt halo + red status + 4,180 veh·h shown.

## State 5 — Mitigated (the fix)
**Do:** click an intervention tool to reveal the **Recommended plan** card (3
steps), then click **"Apply & recompute"**.
**See:** another recompute, then corridors recolor **red→green/amber**; **5
numbered cobalt markers** drop on the map; status chip **green "Mitigated · plan
applied"**; Before/After shows **"Event → Mitigated"** with improving (green ↓)
deltas (**delay 2,590 veh·h**) and a **green** row *"Plan valid. No
hard-constraint conflicts."*.
**✅ Pass:** status green "Mitigated", numbers move 4,180 → 2,590, green "Plan valid" row.

## State 6 — Constraint-blocked (the guardrail)
**Do:** in the copilot, click the chip **"Just close Lake Shore both ways."**
**See:** the copilot **refuses** — a bot message listing the two hard-constraint
breaches with citations **"§ Toronto Municipal Code Ch. 880 — designated fire
route…"** and **"§ TTC service bylaw — streetcar-replacement bus lane…"**, plus
the contraflow-alternative offer; status chip turns **amber "Action blocked ·
bylaw conflict"**; **the network does not change** (no recompute, corridors stay
as they were).
**✅ Pass:** amber status, two § citations, network unchanged.

---

## Cross-cutting checks
- **Copilot hero** (chip *"Ease post-match gridlock…"*): bot replies with a
  3-step plan + **4** citations (Ch. 950, King St, Ch. 880, AODA 2005) and reveals
  the preview card. ✅ if all 4 § lines show.
- **Transit toggle** (top bar **Transit**, on by default): faint dashed
  streetcar routes (509/511); move the scrubber and vehicle dots animate along
  them. Toggle off → they disappear. ✅ if toggling shows/hides them.
- **Theme** (top bar **Dark**): the whole UI + basemap flip to the dark "ops"
  palette; congestion colors brighten. ✅ if light↔dark with no unreadable text.
- **Scrubber**: dragging changes the clock and (with Transit on) moves vehicles;
  crossing 17:05 from baseline auto-triggers the surge.
- **Reset** (top bar): returns to a calm baseline.
- **Performance**: while streaming/animating, the dev DebugPanel (top-left, dev
  build only) should hold ~60 fps. ✅ if it doesn't crater.

## If something looks wrong
- **Blank white page** → open devtools console; a red error usually means the
  build didn't run (`npm run build`) or a dep is missing (`npm install`).
- **No panels, only map** → you're likely on the first-run screen; click "Load the twin".
- **404 favicon.ico** in the console → harmless, ignore.
- **Map is just a flat color** → expected (no street tiles by design); confirm the
  colored corridors render on top.
- **Live mode shows nothing** → the API isn't running; start `scripts/run_api.sh`
  or use `npm run preview` (deterministic demo, no API needed).
