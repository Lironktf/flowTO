# GOAL — TorontoSim MVP build (autonomous `/goal` handoff)

> **Read this top-to-bottom before doing anything.** You are an autonomous build agent. Your job is to
> implement the TorontoSim MVP by executing the phase specs in `docs/specs/` **in dependency order,
> test-first**, until the FIFA World Cup demo (P12) runs deterministically — while keeping Liron's existing
> prototype green at every step. Work in small, verified increments. When blocked, record it and move on; never
> fake progress.

---

## 0. Mission (one paragraph)
Build TorontoSim: a local-first 3-D Toronto traffic digital twin on the NVIDIA DGX Spark. Liron already built a
working CPU pipeline (graph → ML demand → gravity OD → assignment → congestion → scenarios, with tests). You will
**keep that as the demo-safe baseline** and layer the spec's features on top **behind flags** — BPR + Frank-Wolfe
equilibrium, blast-radius recompute, Centreline graph, IPF-calibrated demand, transit overlay, Nemotron copilot,
cuOpt optimizer, profiling. **CPU-first**; GPU/LLM paths are validated on the Spark over SSH and are never allowed
to block the build. Done = the demo (P12) runs deterministically end-to-end.

## 1. Required reading (in this order, before coding a phase)
1. `docs/specs/ROADMAP.md` — strategy, the locked decisions, dependency graph, repo layout, conventions.
2. The **phase spec** you're about to execute (`00-*.md` … `12-*.md`) — it is your contract.
3. The **research brief(s)** it references in `docs/specs/research/` — real dataset IDs, APIs, versions, gotchas.
4. For the existing code: `README_MODEL_SIMULATION.md` + `src/graph/README.md` (after the merge in §3).
**Do not start a phase before reading its spec + research brief.** If a spec underspecifies something, use a
research agent / context7 / WebFetch to fill the gap — don't guess.

## 2. Non-negotiable ground rules
- **Baseline stays green.** Liron's tests (`tests/test_graph_mutation.py`, `tests/test_simulation.py`) must pass
  after **every** phase. New behavior lands **behind flags** (`engine=`, `backend=`, `congestion_model=`,
  `calibration=`, `graph_source=`, `recompute=`). **Never delete the baseline path.**
- **TDD.** Write the failing test **first** (each spec lists them under "Test-driven design"), then implement to
  green. The **AequilibraE/TNTP oracle** (P04) is the correctness anchor for the simulation.
- **CPU-first.** Everything must run + unit-test on this CPU dev box. GPU/LLM (RAPIDS/cuGraph, Nemotron, cuOpt)
  sits behind a flag and is gated by a **Spark smoke test**. **If the smoke test fails, CPU is the path — keep
  going.** GPU is never a build blocker.
- **Determinism.** Fixed iteration caps + rgap targets, `edge_id`/`node_id` tie-breaks, `float64`, seeded RNG, no
  wall-clock stops. Same input → identical output.
- **Git.** Work in the build worktree (§3). Commit **per task or per phase**, message prefixed with the id
  (`P04 T04.3: …`). **No `Co-Authored-By` / AI-attribution trailers.** Don't push unless told.
- **Attribution.** Ship `Contains information licensed under the Open Government Licence – Toronto` (City data) /
  OGL-Ontario (Metrolinx) where data is used.
- **Scope discipline.** Build the spec's *in-scope*, skip *out-of-scope*. Stretch specs (`stretch/S1…S6`) only
  after the core demo is stable.
- **Honesty.** Never fake a passing test, stub a verification to look done, or claim GPU/LLM works without the
  Spark check. A deferred/blocked item recorded honestly is correct; a fake green is a failure.

## 3. Environment setup (do once, first — this IS phase P00 task T00.1)
```bash
# isolated build worktree off the planning branch (which has the specs)
cd ~/flowTO
git worktree add ~/flowTO-build -b build/mvp bentobranch
cd ~/flowTO-build

# bring in Liron's working prototype (graph/model/simulation + data + tests)
git merge --no-edit origin/liron/model      # resolve README.md/.gitignore conflicts → keep BOTH doc sets

# python env
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt             # until P00 creates pyproject.toml, then: pip install -e .[dev,sim]

# establish the GREEN BASELINE — these must pass before you change anything
pytest -q
```
**Spark harness** (after P00 creates `scripts/spark/`): set `SPARK_HOST=asus@gx10-4f5f` (Tailscale `100.124.76.16`,
key auth, remote venv `~/flowto-venv`). Run `scripts/spark/smoke_rapids.py` and `smoke_ollama.py` **once**, record
`RAPIDS_OK`/`RAPIDS_FALLBACK_CPU` and Ollama status in `infra/README-spark.md`. **These verdicts gate every
GPU/LLM phase.** If the Spark is unreachable, record "Spark unreachable — CPU only" and proceed CPU-only.

## 4. Execution protocol

### 4a. Per-task loop (the core loop — TDD until green)
For each task `T0x.y` in the active phase spec:
1. Read the task and its matching test in the spec's "Test-driven design" section.
2. **Write the failing test first** in `tests/`. Run it; confirm it fails *for the right reason*.
3. Implement the **minimum** to pass — touching only the files in the spec's "Files to create/modify".
4. **Loop:** run the test → read the failure → fix → repeat **until green**. Cap at ~6 focused attempts; if still
   failing, go to §6 (escalate, don't thrash).
5. Run the phase's other tests **+ the baseline tests** — no regressions allowed.
6. `ruff check` / `black` clean. **Commit:** `P0x T0x.y: <what changed>`.
7. Tick the task's checkbox in the spec file; append a status line to `docs/specs/BUILD_STATUS.md`.

### 4b. Per-phase loop
1. Complete all tasks via 4a.
2. Run the spec's **Verification → Local** block. It must pass.
3. If the spec has **Verification → On Spark** AND the relevant smoke test passed: `scripts/spark/push.sh` →
   run the verification over SSH (`scripts/spark/run.sh "…"`) → `pull.sh` artifacts. If Spark unreachable or smoke
   failed: record **"GPU deferred — CPU verified"** and continue (do **not** block).
4. Mark the phase ✅ in `BUILD_STATUS.md` and the ROADMAP status column. Commit.
5. Move to the next phase whose `Depends on` is satisfied (§5).

### 4c. Which tools to use
- **Bash** — pytest, scripts, git, the Spark SSH harness, `ruff`/`black`.
- **Write/Edit** — code + tests (only the spec's listed files).
- **Agent / Explore** — when a spec underspecifies an API or you hit an unknown, spawn a research agent
  (web/context7) instead of guessing. Prefer the `research/` briefs first.
- **context7 / WebFetch** — current library docs (deck.gl, AequilibraE, RAPIDS, Ollama, cuOpt) when an API drifted.
- **Spark scripts** — all GPU/LLM verification (`scripts/spark/*`).

## 5. Phase order & gating
**Critical path to a running demo:** `P00 → P01 → P02 → P03 → P04 → P06 → P07 → P12`.
**Interleave when deps are met:** `P05` (after P04), `P08` (after P01+P07), `P09` (after P06), `P10` (after
P04+P06), `P11` (land its timing harness *during* P04, use throughout).
- **Never start a phase whose `Depends on` is incomplete.**
- **If a phase blocks,** apply its Risks/fallbacks (every spec has an always-available fallback — e.g.
  `recompute=full`, `backend=cpu`, OSMnx graph, heuristic optimizer, mocked LLM), record the deferral, and move to
  the next independent phase. The demo survives without any single non-critical phase.

## 6. Failure handling / when to stop and ask
- **A test won't pass after ~6 focused attempts, or a spec assumption is provably wrong** → STOP that task; write
  the blocker + your diagnosis to `BUILD_STATUS.md` under **BLOCKED**; move to the next independent task/phase;
  surface all blockers in the final handoff.
- **RAPIDS smoke fails on the Spark** → set `backend=cpu` everywhere, note it, continue. (Expected, contained.)
- **Ollama / cuOpt unavailable** → use the spec's fallback (mock the model in tests locally; canned demo results);
  note it.
- **A destructive, irreversible, or out-of-scope decision** → do **not** take it; leave a note for the human.
- **Never** fabricate a green test or skip a verification to appear done.

## 7. Definition of done
- **Task done:** its test(s) green, no regressions, linted, committed, checkbox ticked, BUILD_STATUS line added.
- **Phase done:** all tasks done; Local verification passes; Spark verification **passes or is deferred with a
  recorded reason**; status updated; committed.
- **GOAL done (MVP):**
  - [ ] `P00–P07` + `P12` complete (P05/P08/P09/P10/P11 complete **or** explicitly deferred with fallback noted).
  - [ ] `pytest -q` fully green on the CPU dev box.
  - [ ] The three demo scenarios (`baseline`, `wc_surge`, `wc_fix`) run **deterministically** and the headline
        metric improves `baseline → wc_surge → wc_fix` (P12 test).
  - [ ] The API serves (P06) and the frontend renders the scrub → surge → fix → before/after loop (P07).
  - [ ] `docs/specs/BUILD_STATUS.md` shows every core phase ✅ (or deferred-with-reason).
  - [ ] A final `docs/specs/HANDOFF.md` summarizes: what's done, what's deferred (especially GPU/LLM and why),
        known issues, and **exact commands to run the demo**.
  - [ ] Everything committed on `build/mvp`. (Do not push or open a PR unless the human asked.)

## 8. Progress tracking artifact (keep this current — it's the human's overnight dashboard)
Maintain `docs/specs/BUILD_STATUS.md`: a table of phases → tasks with status
(`todo`/`doing`/`done`/`blocked`/`deferred`), a timestamp, and a one-line note. Update it after every task and
phase. This file is how the human sees overnight progress without reading the diff.

---

### Quick reference — the flags that keep the baseline safe
| Flag | Baseline (safe) | New (spec) |
|---|---|---|
| `engine` | `kpath` (Liron) | `equilibrium` (BPR + Frank-Wolfe) |
| `congestion_model` | `legacy` (lookup) | `bpr` |
| `backend` | `cpu` (NetworkX) | `gpu` (cuGraph — Spark only, smoke-gated) |
| `graph_source` | `osmnx` (Liron) | `centreline` |
| `calibration` | `none` | `ipf` / `ipf_counts` |
| `recompute` | `full` (Liron) | `blast` (blast-radius) |

When in doubt, prefer the **safe** column so the demo always runs; the **new** column is the upgrade you verify.
