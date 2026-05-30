# 00 — Hackathon Brief (Spark Hack Series, NVIDIA)

> Source: event listings for "The Spark Hack Series" (Luma / CompeteHub). The official
> Notion page is JS-rendered; details below pieced together from event copy. **Verify
> the exact track names, time window, and submission format with organizers on-site.**

## Theme
**"Your Code. Your Hardware. Your Edge."** — build high-performance solutions that run
**entirely on-device** on next-gen NVIDIA compute. **No cloud.** Fully local AI.

## Hardware provided
- **Dell Pro Max w/ GB10** = ARM-based NVIDIA **DGX Spark** compute (one per team).
- Ours: `asus@gx10-4f5f`. See `01-spark-inventory.md`.

## Tracks (align to ONE)
1. **Human Impact** — health, safety, economic well-being, social services, equity.
2. **Environmental Impact** — sustainability, resource mgmt, energy, waste, **urban mobility**. ← **OURS**
3. **Cultural Impact** — arts, recreation, community identity, accessibility.

> SF event used SF open datasets. For a Toronto event, expect Toronto open data
> (City of Toronto Open Data, TTC/Metrolinx GTFS). CONFIRM on-site.

## Bounties (we target all 3)
| Bounty | What they want | Our hook |
|---|---|---|
| **Best use of NVIDIA Nemotron** | Nemotron integrated into a local solution | NL planner copilot (parse intent, explain results, cite bylaws) |
| **Arm Architecture Innovation** | Innovative use/optimization on ARM (GB10) | Whole stack built + tuned on GB10 ARM cores; note any SIMD/threading work |
| **Prime Intellect — Verifiers** | Best use of Verifiers env framework (RL, agent evals, RL data) | Auto-optimizer = RL agent; reward = −commute time w/ bylaw+budget constraints |

## Rules / logistics (verify on-site)
- Team size **3–5**. Max ~30 teams.
- Must build **locally** (no cloud dependency).
- Must use **open datasets**.
- Nemotron available locally (Ollama on our box) / demo via OpenRouter as fallback.

## Open questions to confirm with organizers
- [ ] Exact time window (24h / 36h / weekend)?
- [ ] Submission format (demo video? live pitch? repo?)
- [ ] Are Toronto datasets pre-provided or BYO?
- [ ] Is internet allowed for data download (vs. truly air-gapped runtime)?
- [ ] Judging rubric weights (impact vs. technical vs. demo)?
