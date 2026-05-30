# P11 — Profiling & performance: Nsight on Spark, latency counters, perf panel

| | |
|---|---|
| **Priority** | High |
| **Depends on** | P04, P05 (lands early, used throughout) |
| **Owner hint** | Glue/PM owner |
| **Status** | not started |

## Goal
Turn performance claims into **measured evidence**: in-app latency counters from the first prototype, a small
benchmark table, and Nsight traces on the Spark. The headline number is **full-city recompute vs blast-radius
recompute** latency.

**Why / rubric tie-in:** Performance (10) + Spark story (15). Judges reward *measured* speed; Nsight turns "fast on
GB10" into proof. "Don't leave this until the end."

## Current state
- None. Liron's sim has no instrumentation; no Nsight; no perf surface.

## Target state
- A `perf/` timing harness (decorators/context managers) emitting structured timings (ingest, graph build, TMC aggregation, full-city solve, blast-radius solve, affected-subgraph size, LLM first-token, frame rate); a `bench` CLI producing a benchmark table; Nsight Systems/Compute capture scripts for the Spark; a frontend DebugPanel showing live counters.

### In scope
Timing instrumentation, benchmark CLI + table, Nsight capture scripts, CPU-vs-GPU and full-vs-blast comparisons, the perf metrics in the spec's acceptance table.
### Out of scope
The features themselves (this measures them). Optimizing — first *measure*, then targeted fixes.

## Design / implementation plan
1. **Timing harness** (`perf/timing.py`) — `@timed("graph_build")` decorator + `with timer("solve"):`; collect into a structured run record; near-zero overhead; deterministic labels.
2. **Counters** (the spec's acceptance metrics): raw-ingest success %, graph build time, TMC aggregation (cuDF vs pandas where feasible), full-city recompute latency, **blast-radius recompute latency** (target sub-100ms local closure; <250ms acceptable w/ progress), affected-subgraph size (% of graph), frontend frame rate, LLM first-token latency, crash-free demo path.
3. **Benchmark CLI** (`perf/bench.py`) — run a fixed scenario set, emit `data/bench/results.json` + a Markdown table; same machine for all rows.
4. **Nsight on Spark** (`scripts/spark/nsight_*.sh`) — `nsys profile` around a sim run + an LLM call; pull the report back; capture cuDF/cuGraph/Ollama timelines as the GPU evidence.
5. **Frontend DebugPanel** (P07) — live FPS, tick lag, last solve time, affected-subgraph size, LLM latency.
6. **CPU/GPU + full/blast comparisons** — record both backends (where GPU available) and both recompute modes side-by-side; these two tables ARE the perf story.

## Data / models / sources
Spec §14 acceptance metrics. `research/04` (cuGraph timings, RAPIDS-on-Spark caveat — if GPU unavailable, CPU latencies still make a valid story at downtown scale). `research/05` (LLM latency, Nsight as evidence).

## Files to create / modify
**Create:** `src/torontosim/perf/{__init__,timing,bench}.py`; `scripts/spark/{nsight_sim.sh,nsight_llm.sh}`; `data/bench/README.md`; `tests/test_timing.py`.
**Modify:** P04/P05 hot paths (add `@timed`), P06 (emit timings in run results), P07 DebugPanel.

## Test-driven design
- `test_timing.py` (first): `@timed` records a label + duration; nested timers compose; overhead under a small bound; labels deterministic.
- `bench.py` on a fixed scenario emits a stable table schema (counters present), reproducible run-to-run (determinism from P04).

## Verification
**Local (CPU):** `python -m torontosim.perf.bench` → benchmark table with full-city vs blast-radius latency + subgraph size; DebugPanel shows live counters.
**On Spark:** `scripts/spark/nsight_sim.sh` + `nsight_llm.sh` over SSH → pull `.nsys-rep`; record cuDF/cuGraph/Ollama timelines + CPU-vs-GPU sim latency. **This is the demo's "computed in Xs on-device" evidence.**

## Tasks
- [x] T11.1 `timing.py` harness + decorators; instrument P04/P05 hot paths — *0.5d*
- [x] T11.2 `bench.py` CLI + Markdown table + fixed scenario set — *0.5d*
- [x] T11.3 Full-city vs blast-radius + CPU vs GPU comparison rows — *0.5d*
- [x] T11.4 Nsight capture scripts (sim + LLM) + pull-back — *0.5d*
- [x] T11.5 Frontend DebugPanel counters — *0.5d*

## Risks / fallbacks
- **GPU unavailable (sm_121)** → report CPU latencies (downtown scale is fast); the full-vs-blast comparison stands on CPU alone; Nsight still profiles cuDF/Ollama where they run.
- **Nsight friction on aarch64** → fall back to in-app counters + `time`/`nvidia-smi` snapshots as evidence.
- **Profiling slips to the end** → land the timing harness in the first prototype (this phase is early on purpose).
