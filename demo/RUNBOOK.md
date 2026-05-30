# FlowTO — FIFA WC26 demo run-of-show (P12)

> **90 seconds. Pre-baked. Deterministic. Never debugged live.** Rehearsal ==
> performance — the three scenarios produce identical numbers every run.

## Setup (before the room)
1. **Backend** on the Spark (or dev box): `scripts/run_api.sh` → API on `:8000`.
   (Over Tailscale for the on-device story: run on `asus@gx10-4f5f`, tunnel the port.)
2. **Frontend**: `scripts/run_frontend.sh` → `http://localhost:5173`.
3. **Pre-bake** the three scenarios so numbers are warm:
   `python -m torontosim.demo.wc_surge --scenario all` (prints baseline/surge/fix).
4. Have the **fallback capture** (`demo/fallback/`) open in a second tab.

## The 90 seconds (click sequence)
| t | Beat | Action | What they see |
|---|---|---|---|
| 0:00 | **Cold open** | First-run splash → **"Load the twin"** | "A live digital twin of **Toronto**." 18,190 edges, on-device. |
| 0:10 | **Baseline** | Scrubber at 17:00 | Calm network (green/amber); Exhibition Place quiet; status "Baseline · nominal". |
| 0:20 | **Surge** | Scrub across **full-time 17:05** (or Demand-surge tool) | Auto-recompute (HERO overlay, 5 steps); SW/Gardiner/Lake Shore melt **deep red**; cobalt blast-radius halo; status red "Post-match surge · gridlock"; Before/After jumps to event (delay 1,240→4,180 veh·h, infiltration 6→34%). |
| 0:40 | **Copilot fix** | Type / chip: *"Ease the post-match gridlock around BMO Field without breaking bylaws."* | Nemotron replies with a **3-step plan + 4 bylaw citations** (§ Ch. 950, King St Transit Priority, Ch. 880 fire route, AODA 2005); reveals the preview card. |
| 0:55 | **Apply** | **Apply & recompute** | Blast-radius recompute (~84 ms, 1,284 affected edges); corridors **red→green/amber**; 5 numbered action markers drop; status green "Mitigated · plan applied". |
| 1:10 | **Metric card** | Point at Before/After | Event→mitigated: delay −38%, local infiltration −71%, **$0 capital**, computed **on-device (DGX Spark · GB10)**. |
| 1:20 | **Bylaw guardrail** | Chip: *"Just close Lake Shore both ways."* | Copilot **refuses** — cites Ch. 880 (fire route) + TTC replacement-bus lane; network **unchanged**; status amber "Action blocked". |

## The measured story (engine-computed, not hand-waved)
`python -m torontosim.demo.wc_surge --scenario all` reports the egress-area
congestion near BMO Field melting **baseline → surge → fix** (the test
`tests/test_demo_scenarios.py` pins this monotone + deterministic). The
authored Before/After card numbers (`design/js/data.js`) frame it for the room;
the live engine evidence is the Exhibition-area pressure drop + blast-radius
recompute time.

## Framing (honest, per docs/04 mesoscopic stance)
- "All of Toronto" = **coverage + transit visuals citywide**; **traffic dynamics where you zoom** (downtown extent).
- The **fix is road-side** (contraflow + signal retiming + pedestrian corridor + blast-radius). The **509/511** appears as a transit **visual** ("+frequency hold"), not a measured rider model.
- The surge is a **labeled scenario multiplier** (~45k egress) — hypothetical, not a claim of measured matchday counts.

## Fallbacks (if the live box hiccups)
- **NL flakes** → the **same scenario JSON** fires via the Demand-surge tool / Apply button (identical result).
- **Box hiccups** → play the **pre-recorded full run** (`demo/fallback/`).
- Determinism guarantees the recording matches the live run exactly.

## Rubric / bounty close (one line each)
- **Impact** — real Toronto open data, timely WC2026, planner-grade decision tool.
- **Technical** — BPR + Frank-Wolfe equilibrium (oracle-validated vs SiouxFalls), blast-radius recompute, on-device Nemotron copilot, optimizer.
- **Spark** — 100% local on GB10: cuGraph SSSP, Nemotron via Ollama, no cloud.
