# Handoff — Spec the Closure Feedback-Loop Training System

> **Task type:** RESEARCH + SPEC only. Do **not** implement models or pipelines —
> produce a decision-complete spec document and a dataset research report. Work in
> plan mode; ask clarifying questions before finalizing.

**Worktree:** Work in `/home/anonabento/flowTO-gnn` (branch `feat/gnn-feedback-loop`,
off `main`). This is isolated from the copilot work — a separate agent owns PR #21
on `feat/flo-7-copilot-nemotron`. Do not touch that branch.

---

## Read these first (in order), then summarize back what's already built

1. `docs/07-training-feedback-loop.md` — the existing high-level plan. Your spec
   **extends** this into a full, build-ready spec.
2. `models/gnn/README_GNN.md` + `models/gnn/{model.py, build_gnn_dataset.py,
   train_gnn.py, predict_gnn_baseline.py, gnn_to_sim_adapter.py, utils.py}` — the
   **already-built baseline GNN** (GraphSAGE edge predictor; predicts
   `pressure = observed_count / capacity`; **open-road baseline ONLY**; trained by
   Liron, merged to main). Know exactly what exists so you don't re-spec it.
3. `docs/gnn-explainer.md` — conceptual framing (Option A surrogate vs Option B
   demand-GNN; §8b feature engineering).
4. `src/torontosim/model/{ingest_real_data.py, odme.py, validate_past.py}` — real
   TMC ingest, count calibration, and the predicted-vs-observed comparison core.
5. `src/torontosim/simulation/*` — the Frank-Wolfe/BPR sim (the "physics" + the
   scenario-generator source of truth) and graph mutations (`close`/`reopen`/
   `add`/`change_capacity`).
6. `docs/specs/research/01-toronto-datasets.md` — verified Toronto open-data IDs,
   the LIVE road-restrictions feed caveat, TMC schema/gotchas.
7. `docs/06-spark-setup-verified.md` — the verified training stack (torch cu130,
   pure-Python PyG, Warp, XGBoost) on the GB10/Spark.

**Data on disk** (gitignored): `data/raw/tmc_raw_data_2020_2029.csv` (28MB),
`data/raw/262469c2-*.csv` (80MB raw TMC dump), `data/raw/weather/*.csv`,
`data/model/{training,validation}_dataset.csv`. TMC columns include `_id`,
`count_id`, `count_date`, `centreline_id`, `px`, `start_time`, `end_time`,
`{n,s,e,w}_appr_{cars,truck,bus}_{r,t,l}`, peds, bike.

---

## Deliverable 1 — Full feedback-loop spec → `docs/specs/13-feedback-loop.md`

The "feedback loop" = learn open-road flow → predict closure impact → compare to
what **actually** happened → train on the delta. The baseline GNN exists; spec the
**closed loop**. Cover, with concrete decisions (not options):

### A. Ground truth — the historical closure join (the hard blocker)
- How to obtain historical closure/construction windows for Toronto. Note: the
  Road Restrictions CART feed is **live, not a historical archive** — research
  alternatives (road-occupancy / construction permits, lane-closure permits,
  archived feeds, news/311). State honestly what is actually queryable.
- The join: closure window + location (`CENTRELINE_ID`/`px`) → TMC counts at
  affected + nearby intersections, before vs after → observed link deltas.
- Controls/confounders: how to isolate the closure effect from weather, events,
  seasonality, day-of-week (this is **why** the extra datasets matter).
- Scope the **yield**: estimate how many usable before/after closure cases exist
  in the TMC dump. If thin, define the fallback (lean on sim-generated pairs).

### B. Scenario generator (sim pre-train data)
- How to script the Frank-Wolfe sim to emit `(random closure → equilibrium flow)`
  pairs at scale; sampling strategy; label definition (flow, or residual over the
  deterministic baseline); GPU parallelization (Warp/cuGraph).

### C. Model & training
- Target: per-edge flow/pressure under a closure, **or** the residual delta on top
  of the physics sim — pick one and justify.
- How closure enters the GNN inputs (edge mask/feature, **not** retraining per
  scenario). Two-stage: Stage-1 sim pre-train → Stage-2 real-closure fine-tune.
- Reuse vs extend the existing GraphSAGE model/dataset builder — be specific about
  what code changes.

### D. Validation & the activation gate
- Held-out real closures as test set; metrics (MAE/RMSE on deltas, %err via
  `validate_past.py`). The gate: **only ship the GNN if it beats the deterministic
  sim's delta** on held-out closures.
- Optional: wrap "Δ-vs-observed < ε" as a Prime Intellect Verifiers reward.

### E. Integration
- How the fine-tuned model feeds the optimizer (P10) as a fast pre-screen, with the
  sim verifying top-K (keep sim as source of truth).

### F. Risks/fallbacks + an ordered task list with rough effort.

---

## Deliverable 2 — Dataset research → `docs/specs/research/07-feedback-datasets.md`

Beyond the closure join, research external signals that improve training. For
**each** candidate, report: source + license, availability (**historical depth!**),
temporal/spatial resolution, **join key + time alignment** to TMC/graph, and
**role** — is it a model FEATURE, a ground-truth LABEL, a CONFOUNDER to control, or
a SCENARIO TRIGGER? Rank by impact-vs-effort.

Seed candidates to investigate (verify, don't assume):
- **Weather** (HAVE — ECCC): enrich beyond the 0–3 bucket — continuous temp, precip
  amount, snow depth, visibility, wind. *(Confounder + feature.)*
- **Construction / road-occupancy / lane-closure permits** (closure windows =
  ground-truth driver).
- **Special events**: BMO Field / stadium schedules, festivals, FIFA WC 2026
  (demand-surge triggers; ties to the demo).
- **Collisions / KSI dataset** (incident-driven congestion).
- **TTC service alerts / GTFS-RT disruptions** (mode-shift demand).
- **Holiday + school calendars** (baseline-shift confounders).
- **Centreline network changes over time** (for the future "road opening" factor).
- **Time-of-day / seasonality** (HAVE) — note what's already covered.

Use WebSearch/WebFetch + context7 for current dataset availability and the Toronto
Open Data (CKAN) catalog. Cross-check against `research/01`.

---

## Constraints & conventions
- **Data honesty:** never overclaim. If real closure labels are thin, say so and
  present sim-generated as "calibration-ready," per the spec's honesty note.
- Determinism; CPU-first / GPU-validated-on-Spark; **sim stays source of truth**.
- GNN is **Liron's area** — flag anything that overlaps/duplicates his work; the
  spec should build on `models/gnn/`, not replace it.
- Follow the existing spec template (Goal → Current state → Target → Design →
  Data/sources → Files touched → Test-driven design → Verification → Tasks → Risks),
  matching the other `docs/specs/NN-*.md` files.
- No AI-attribution trailers in commits/PRs.

**Start by:** reading the files above, then post a short *"here's what exists /
here's what I'll spec / open questions for you"* summary **before** writing the spec.
