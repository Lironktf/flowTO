# P12 — FIFA WC demo: match-day surge, before/after, demo script, fallbacks

| | |
|---|---|
| **Priority** | Core (the demo IS the product) |
| **Depends on** | all core (P00–P11) |
| **Owner hint** | PM/demo owner (floats to bottlenecks) |
| **Status** | not started |

## Goal
Assemble the **90-second winning demo**: a normal weekday rush, the **FIFA World Cup 2026 surge at BMO Field**,
a planner/copilot fix, and the heatmap melting red→green with a headline metric — all **pre-loaded, deterministic,
and never debugged live**, on the Spark. A general closure-planning engine, dressed as the World Cup story.

**Why / rubric tie-in:** Everything. Impact (real Toronto data, timely WC2026), Technical (sim+blast-radius+local
LLM+optimizer), Spark (all on-device), and the bounties name-dropped at the close.

## Current state
- Demo narrative drafted in `docs/05-demo-script.md` (assumed a transit fix). With transit now visual-only, the *fix* shifts to **road interventions + blast-radius + optional "+509 frequency" as a visual** (per the transit-scope decision).

## Target state
- A scripted, pre-baked scenario set + a rehearsed run: (1) 3-layer city + scrub to weekday 5pm; (2) apply match-day surge → southwest/Gardiner goes deep red; (3) copilot NL fix → preview → apply; (4) blast-radius recompute → red→green; (5) headline metric card ("egress −X%, $0 capital, computed in Ys on-device"). Pre-recorded fallback + canned optimizer/copilot results.

### In scope
Match-day demand profile, the scripted scenario JSONs, the before/after metric framing, the rehearsed copilot prompts, the recorded fallback, the talking points mapped to the rubric/bounties.
### Out of scope
New engine features (this composes P00–P11). Anything not on the 90-second path.

## Design / implementation plan
(Builds on `docs/05-demo-script.md`, updated for road-centric fix.)
1. **Match-day demand** (`demo/wc_surge.py`) — BMO Field (Exhibition Place) special-generator injection (~45k egress) into the OD at the relevant evening slice; pre-/post-match profile; label clearly as a scenario multiplier (per the spec's "hypothetical, labeled" stance).
2. **Scenario JSONs** (`demo/scenarios/`) — baseline (weekday 5pm), `wc_surge`, `wc_fix` (the rehearsed intervention set: contraflow on Lakeshore, signal retiming, a pedestrian corridor on Bremner, +509 frequency as a visual). All deterministic, pre-baked.
3. **Rehearsed copilot prompt** — exact wording: *"Ease the post-match gridlock around BMO Field without breaking any bylaws."* → validated tool call → preview → apply (P09). A **button that fires the same scenario JSON** if NL flakes.
4. **Metric card** — egress time −X%, $0 capital cost, blast-radius recompute time (P11 number).
5. **Pre-recorded fallback** — full-run screen capture; canned optimizer + copilot results cached so no live wait.
6. **Run-of-show** (`demo/RUNBOOK.md`) — exact click sequence, timings, who says what, the failure fallbacks.

## Data / models / sources
`docs/05-demo-script.md` (beat-by-beat), `docs/04-scope-and-mvp.md` (must-haves), `research/03` (match-day demand framing), all engine phases. **`design/js/data.js`** is the canonical demo content: exact before/after metrics (base/surge/mitigated: total delay 1,240→4,180→2,590 veh·h, mean TT 11.4→28.7→17.9 min, 95th 19.2→62.5→34.1, congested edges 14→41→22, local-road infiltration 6→34→10%), the **recommended 3-step plan** (contraflow on Lake Shore Blvd W, signal retiming Dufferin & Strachan, close Princes' Blvd + hold 509/511 priority), blast-radius corridor lists, and the timeline (kickoff 15:00, full-time 17:05, Fri 12 Jun 2026). `design/README.md` describes the 6-state demo flow. BMO Field / Exhibition / Gardiner / 509 geography.

## Files to create / modify
**Create:** `src/torontosim/demo/{wc_surge.py}`, `demo/scenarios/{baseline,wc_surge,wc_fix}.json`, `demo/RUNBOOK.md`, `demo/fallback/` (recording + canned results); `tests/test_demo_scenarios.py`.
**Modify:** `docs/05-demo-script.md` (update the fix to road-centric + transit-visual).

## Test-driven design
- `test_demo_scenarios.py` (first): each demo scenario JSON loads + runs deterministically; `wc_surge` produces visibly higher pressure than baseline near Exhibition; `wc_fix` reduces the headline metric vs `wc_surge`; re-running gives identical numbers (the on-stage guarantee).
- The rehearsed copilot prompt → a valid tool call matching the canned fix (Spark-only, `@pytest.mark.spark`).

## Verification
**Local:** run the three scenarios end-to-end → metric improves baseline→surge→fix as scripted; numbers identical on re-run.
**On Spark (the actual demo environment):** full run on the Spark over Tailscale: scrub → surge → copilot fix → blast-radius red→green → metric card; capture the **recorded fallback** from this run; confirm crash-free repeated runs. Rehearse the 90 seconds.

## Tasks
- [ ] T12.1 `wc_surge.py` match-day demand + scenario JSONs (baseline/surge/fix) — *1d*
- [ ] T12.2 Wire the copilot rehearsed prompt + same-JSON fallback button — *0.5d*
- [ ] T12.3 Metric card framing + blast-radius timing number — *0.5d*
- [ ] T12.4 `RUNBOOK.md` run-of-show + record the fallback capture + canned results — *0.5d*
- [ ] T12.5 `test_demo_scenarios.py` + rehearse on Spark (crash-free, deterministic) — *0.5d*
- [ ] T12.6 Update `docs/05-demo-script.md` to road-centric fix + transit-visual — *0.25d*

## Risks / fallbacks
- **Live box hiccups** → pre-recorded full-run capture; canned optimizer/copilot results; deterministic scenarios mean rehearsal == performance.
- **Copilot NL flakes on stage** → button firing the identical scenario JSON.
- **"All of Toronto" overpromise** → use the honest mesoscopic framing (`docs/04`): coverage + transit visuals citywide, traffic dynamics where you zoom.
- **Transit fix expectation** → the streetcar appears as a visual "+509"; the *measured* fix is road-side (contraflow/signals/blast-radius) — set that framing in the runbook.
