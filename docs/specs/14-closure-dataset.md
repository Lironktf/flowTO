# P14 — Intervention Impact Dataset: real closure/opening → observed-traffic training labels

| | |
|---|---|
| **Priority** | High (feeds P13) |
| **Depends on** | P01 (datapipeline), P02 (graph), real TMC + ECCC weather on disk |
| **Owner hint** | Data owner (consumed by P13 GNN training) |
| **Status** | v1 prototype exists on branch `dataset-creation`; this spec hardens + extends it |

## Goal
Produce the **real ground-truth labels** the feedback loop (P13) fine-tunes and gates on: for each
real Toronto road **intervention** — a closure/restriction **or** a reopening/added-capacity event
— the **observed change in traffic** on affected and neighbouring streets, as a signed,
confounder-controlled delta, joinable to the road graph. Build it in **phases, each with its own
test-driven design and verification**, so every step is independently correct before the next
depends on it.

**Why / rubric tie-in:** this is the "reality" half of "AI that learns from reality." Without
honest, leak-free labels the activation gate (P13.D) is meaningless. Data honesty is a hard
constraint: thin is fine, fabricated is not.

## Current state
- **v1 prototype (branch `dataset-creation`, `data/dataset/`):**
  - `clean_restrictions.py` — stdlib-CSV clean of `v3.csv` (a **snapshot of the live CART
    road-restrictions feed**) → `restrictions_clean.csv` (**2,696 restrictions**; drops ~22
    malformed rows; leaves `StartTime`/`EndTime` as epoch-ms).
  - `build_dataset.py` (RAPIDS cuDF) — the **canonical** builder: spatial join restriction × TMC
    **site** (`centreline_id`, **not** `count_id`) within `RADIUS_M=500`, temporal split
    during/pre, baseline matched on `(hour,dow)` then `(hour)`, signed deltas →
    `restriction_traffic_dataset.{csv,parquet}` (**313 rows / 111 closures / 173 with baseline**).
  - `dataset-creation.py` — an **earlier, superseded** exploration that baselines on `count_id`
    (a single survey day) → silently-zero baselines. **Documented as the wrong way; do not revive.**
  - `DATASET_README.md` — column dictionary + honest-limits note (109 down / 64 up; signed label).
- **P01 module** `src/torontosim/datapipeline/restrictions.py` (the proper fetch/clean home for
  the CART feed) + `weather.py` (ECCC normalization). TMC ingest/snap in
  `model/ingest_real_data.py` (`build_dataset`, KD-tree snap, `max_snap_m=300`).
- **Gap:** the v1 build is loose scripts in `data/dataset/`, GPU-only, closures-only, no
  confounder control, no openings, no leak-free split, no automated tests. P14 productionizes it.

## Target state
A tested, importable module `src/torontosim/feedback/groundtruth/` + CLI that emits one canonical
artifact `data/dataset/intervention_impact.parquet` (+ a CSV view) with: closures **and**
openings, signed observed deltas, confounder columns + a matched-control flag, an optional
sim-counterfactual residual, a grouped train/test split with **no `centreline_id` leakage**, and a
machine-readable coverage/honesty manifest. Each phase below ships behind passing tests.

### In scope
Source capture/clean (+ forward-logging cron), spatial join, temporal during/baseline, signed
labels, **openings**, confounder enrichment + matched controls, sim-counterfactual residual,
packaging + leak-free splits + coverage manifest. CPU-first (pandas) for testability, cuDF parity
on Spark.

### Out of scope
The GNN/training (P13). External-signal *cataloguing* (`research/07-feedback-datasets.md` — this
spec consumes it). Deep historical reconstruction beyond the snapshot + public sources (flagged as
future depth).

### Feature channels emitted (consumed by P13 §C)
The artifact must carry the columns the GNN's channels need, so P13 reads them directly (a missing
channel → the model's zero/learned default). Mapping channel → producing phase:
| P13 §C channel | Columns the dataset emits | Phase |
|---|---|---|
| **Edge intervention** | `intervention_mask`, `capacity_mult`, `intervention_sign` (closure/opening) | Ph 1–4 |
| **Edge sim-base** (residual learning) | `sim_open_load`, `sim_open_pressure`; targets `r_obs`, `r_sim` | Ph 6 |
| **Context — enriched weather** | continuous `temp_c`, `precip_mm`, `snow`, `visibility_km`, `wind_kmh` (+ categorical flags) | Ph 5 |
| **Context — attribution flags** | `event_nearby`, `incident_nearby`, `ttc_disruption_nearby`, `holiday`, `school` + `confounder_dominated` | Ph 5 |
| **Multimodal layers (future)** | `ped_volume`, `bike_volume` (TMC `*_appr_peds/bike` already aggregated in Ph 2); `transit_load` (P08, future) | Ph 2 / future |

Static road + node features (the **lean** set per `research/08` — keep coords as a learned PE; drop
`degree`, `distance_to_downtown`, `road_class_rank`, `from/to_node_degree`, `pagerank`) come from
the graph, not this dataset; P13's `feedback/dataset.py` joins them by `edge_id`/`centreline_id`.

## Design — phased build (each phase: inputs → outputs, then **TDD** + **Verification**)

Module layout (replaces the loose `data/dataset/*.py` prototypes; CPU pandas path + optional cuDF):
`src/torontosim/feedback/groundtruth/{__init__,clean,spatial,temporal,labels,openings,confounders,
counterfactual,package,cli}.py`. Determinism: stable sorts, fixed seeds, no `random`; cuDF and
pandas paths must agree within tolerance.

---

### Phase 0 — Source capture & clean → `clean.py`
**In:** `v3.csv` (CART snapshot) and/or live CART fetch via `datapipeline/restrictions.py`.
**Out:** `restrictions_clean` frame: `ID, Road, Name, District, RoadClass, Planned, Latitude,
Longitude, StartTime, EndTime, MaxImpact, CurrImpact, Type, SubType, DirectionsAffected,
WorkEventType, Signing`; epoch-ms → UTC datetime; `duration_days`.
**Design:** port `clean_restrictions.py` into the module; consolidate on
`datapipeline/restrictions.py` for fetching (browser UA, epoch-ms, `[lng,lat]` geoPolyline). Add
`scripts/feedback/log_road_restrictions.py` (cron) that appends daily snapshots so the real set
**grows forward** (de-dup on `ID`+`StartTime`; keep version history).
**TDD — `test_clean.py`:** title-banner row skipped; the ~22 malformed/embedded-JSON rows dropped
(not misaligned); valid epoch-ms parse to expected UTC; non-numeric lat/lon/time rows dropped;
row-count matches a fixture; idempotent re-clean.
**Verification:** `clean` on the real `v3.csv` reproduces 2,696 rows; cron appends a new snapshot
without duplicating existing `ID`+`StartTime`.

---

### Phase 1 — Spatial join (intervention × TMC site) → `spatial.py`
**In:** cleaned restrictions + TMC sites (`centreline_id` → mean lat/lon + `location_name`).
**Out:** `(ID × centreline_id)` pairs within `RADIUS_M` with `dist_m` (haversine) + `bearing_deg`.
**Design:** bounding-box prefilter (`BOX_DEG≈0.006`) then haversine; cutoff `RADIUS_M=500`
(configurable). **Site = `centreline_id`** (an intersection surveyed on many days), **never
`count_id`** (one survey day) — the documented correctness invariant.
**TDD — `test_spatial.py`:** haversine vs a known geodesic pair (±0.5%); bounding-box prefilter
never drops a pair the full haversine would keep within radius (superset property); bearing
quadrants correct (N=0, E=90); a pair beyond `RADIUS_M` excluded; **regression guard:** the join
key is `centreline_id`, asserted by a test that a `count_id` join would change row counts.
**Verification:** on real data, pair count + `n_neighbour_sites` distribution matches v1 within
tolerance; spot-check 3 closures' neighbour sites on a map are plausibly within 500 m.

---

### Phase 2 — Temporal split & "during" aggregation → `temporal.py`
**In:** pairs + all TMC surveys at those sites; per-class (cars/trucks/buses/peds/bikes) and
per-approach (`dir_{n,s,e,w}`) volumes (sum the `{d}_appr_{class}_{move}` columns; fill-NA→0).
**Out:** `during_agg` per `(ID, centreline_id)`: `obs_during`, `survey_days_during`,
`during_vol_mean/sum`, per-class means, directional means.
**Design:** `during = StartTime ≤ dt < EndTime` (half-open, documented). Aggregate the mean per
15-min interval so sparse surveys are comparable.
**TDD — `test_temporal.py`:** boundary rows (exactly `StartTime`, exactly `EndTime`) fall on the
correct side; a site with no in-window survey produces **no** during row (not a zero row —
honesty); class/direction sums equal the sum of their component movement columns; NA volumes → 0.
**Verification:** total during-observation count matches v1 (`len(during)`); per-class totals are
non-negative and cars ≫ buses on arterials (sanity).

---

### Phase 3 — Pre-intervention baseline & signed labels → `labels.py`
**In:** `during_agg` + pre-intervention surveys (`dt < StartTime`) at the same site.
**Out:** baseline stats + labels: `base_vol_mean/std`, `baseline_match`, `has_baseline`,
`vol_delta = during_vol_mean − base_vol_mean`, `vol_delta_pct`, `vol_sigma`,
`direction ∈ {0,1}`, `significant = |vol_sigma|>1.5`.
**Design:** Tier-1 match on `(hour,dow)` (like-for-like); Tier-2 fall back to `(hour)` only where
Tier-1 is empty; record which in `baseline_match` (`hour_dow`/`hour`/`none`). **Signed label** —
a closure usually *lowers* volume on the segment and *raises* it on detours; never assume "closure
⇒ more traffic."
**TDD — `test_labels.py`:** Tier-2 used **only** when Tier-1 missing (no double counting); a
synthetic site with known during/before yields the exact `vol_delta`/`vol_sigma`; `has_baseline=0`
when no pre-survey exists (and delta columns are null, not 0); `direction` sign matches a
fabricated drop and a fabricated rise; `significant` threshold at exactly 1.5.
**Verification:** reproduces **173** baseline rows / **109 down, 64 up** on real data; the
`baseline_match` mix matches `DATASET_README`.

---

### Phase 4 — Openings (reopening / added capacity) → `openings.py`
**In:** cleaned restrictions with an `EndTime` in the TMC-covered range + post-`EndTime` surveys.
**Out:** opening rows with the **same schema**, an `intervention_sign ∈ {closure, opening}` flag,
and `vol_delta` defined as **after-reopening − during** (the symmetric recovery signal) plus, when
available, **after − pre** (full cycle).
**Design:** treat a restriction's `EndTime` as a reopening event; the "after" window is
`[EndTime, EndTime+W]` (W configurable, default the closure's own duration capped at e.g. 90 d).
Also emit network-level openings from Centreline additions over time (new `CENTRELINE_ID`s) as a
future hook — flagged, not required for v1. Honest: openings need a survey *after* reopening at the
same site → **expect markedly fewer rows than closures**; report the count, don't pad it.
**TDD — `test_openings.py`:** an `EndTime` outside TMC coverage yields no opening row; a fabricated
recovery (during low → after high) gives `intervention_sign=opening`, positive `vol_delta`, correct
sign; closures and openings never collide on the same `(ID, centreline_id, window)`.
**Verification:** report the realized opening-row count + how many have an after-survey; sanity:
reopening deltas skew positive on the previously-closed segment.

---

### Phase 5 — Confounder enrichment & matched controls → `confounders.py`
**In:** label rows + external signals from `research/07-feedback-datasets.md`.
**Out:** per-row confounder columns + `control_site_ids` + `confounder_dominated` flag.
**Design:** join by time-window × location: **weather** (ECCC hourly — temp, precip mm, snow,
visibility, wind via `datapipeline/weather.py`); **incidents** (KSI lat/lon+date — flag a collision
on/near the link in-window); **events** (Festivals/FIFA/venue dates near the site); **TTC delays**
(route/stop near the site in-window); **holiday/school** flags (date-indexed). **Matched controls:**
for each affected link, select neighbour sites surveyed in the same period with **no** active
intervention nearby, same road-class/time context → a difference-in-differences anchor. Set
`confounder_dominated=1` (and exclude from the clean training subset) when a confounder plausibly
explains the delta (e.g. a KSI collision on the link during the window).
**TDD — `test_confounders.py`:** weather/KSI/event joins land on the correct row by time+space; a
row with an in-window KSI on-link is flagged dominated; matched controls exclude any site with an
active nearby intervention; deterministic control selection (seeded).
**Verification:** report how many rows survive as "clean" (confounder-adjusted) vs flagged; confirm
controls are genuinely intervention-free in their windows.

---

### Phase 6 — Sim-counterfactual residual (fills missing baselines) → `counterfactual.py`
**In:** label rows (esp. `has_baseline=0`) + the P04 sim + ODME-grounded OD.
**Out:** `sim_open`, `sim_int`, `r_obs = observed − sim_open`, `r_sim = sim_int − sim_open` per
affected/nearby link — the residual targets P13 trains/gates on.
**Design:** for each intervention, run `simulate_traffic(engine="equilibrium", backend="scipy",
auto_calibrate=False)` open and intervened on the same OD; the sim's **open** run is the
counterfactual "before" so a real pre-survey is **not required**. Snap observed counts to links as
in `ingest_real_data`. (This is the bridge to P13; P14 produces the residual columns, P13 consumes
them.)
**TDD — `test_counterfactual.py`:** residual is defined when `has_baseline=0` (sim provides the
before); `r_sim` for a known bottleneck has the expected sign; deterministic across runs
(seeded sim); a row with no observed in-window count yields **no** residual (no fabrication).
**Verification:** on a handful of real closures, `r_obs` and `r_sim` are finite and same-order;
report coverage (how many rows gain a residual via the sim that lacked an observed baseline).

---

### Phase 7 — Packaging, leak-free split & coverage manifest → `package.py` + `cli.py`
**In:** all enriched rows. **Out:** `data/dataset/intervention_impact.parquet` (+ CSV view) +
`data/dataset/intervention_impact.manifest.json`.
**Design:** **grouped split by `centreline_id`** (a site never appears in both train and test —
prevents spatial leakage into P13's gate), seed 42, configurable test fraction; write a manifest
with row/closure/opening counts, baseline coverage, confounder-clean counts, direction balance, and
every honesty caveat (so downstream can't mistake thin for complete). `cli.py` runs Phases 0→7 end
to end (`python -m torontosim.feedback.groundtruth.cli`), CPU by default, `--gpu` for cuDF.
**TDD — `test_package.py`:** no `centreline_id` appears in both splits; manifest counts equal the
frame's; schema matches the documented dictionary; re-run is byte-identical (determinism); CSV view
round-trips.
**Verification:** end-to-end CLI on real data reproduces the documented headline numbers (313+
closure rows, 173 baselined, plus the realized opening rows) and writes a manifest whose caveats
match `DATASET_README`; **`--gpu` cuDF output matches the CPU output** within tolerance.

---

## Data / models / sources
- **Restrictions:** CART snapshot `v3.csv` + live feed via `datapipeline/restrictions.py`
  (catalogue + deeper sources — BDIT RoDARS, utility-cut permits, building permits, Wayback — in
  `research/07-feedback-datasets.md`).
- **TMC:** `data/raw/tmc_raw_data_*.csv` (schema/gotchas in `research/01-toronto-datasets.md`),
  snap via `model/ingest_real_data.py`.
- **Confounders:** ECCC weather (on disk), KSI, events/FIFA, TTC delays, holidays — all in
  `research/07-feedback-datasets.md`.
- **Sim/OD:** P04, P03 (`model/odme_calibrate.py`).

## Files to create / modify
**Create:** `src/torontosim/feedback/groundtruth/{__init__,clean,spatial,temporal,labels,openings,
confounders,counterfactual,package,cli}.py`; `scripts/feedback/log_road_restrictions.py` (cron);
`tests/test_clean.py`, `test_spatial.py`, `test_temporal.py`, `test_labels.py`, `test_openings.py`,
`test_confounders.py`, `test_counterfactual.py`, `test_package.py`; tiny CSV fixtures under
`tests/fixtures/groundtruth/`.
**Modify:** consolidate fetch into `datapipeline/restrictions.py`; retire the loose
`data/dataset/{clean_restrictions,build_dataset,dataset-creation,test}.py` prototypes (their logic
moves into the module — keep `DATASET_README.md` as the column dictionary, updated for openings +
confounders). Keep the v1 `restriction_traffic_dataset.csv` as a reference snapshot.

## Test-driven design
Every phase ships behind its own `tests/test_<phase>.py` (above), each driven by a **small CPU
fixture** (a handful of restrictions + synthetic TMC rows with known answers) so the suite runs
without a GPU. One **Spark-marked** parity test (`@pytest.mark.spark`) asserts the cuDF path equals
the pandas path on the real data within tolerance. The cross-cutting invariants — **site =
`centreline_id` not `count_id`**, **signed labels**, **no fabricated rows for missing data**, **no
`centreline_id` leakage across splits** — each have a dedicated regression test.

## Verification
**Local (CPU):** `python -m torontosim.feedback.groundtruth.cli --cpu` runs Phases 0→7 on the real
`v3.csv` + TMC and reproduces the documented headline counts (313+ closure rows / 173 baselined /
109↓ 64↑), writes the parquet + manifest, and the full `pytest tests/test_*groundtruth*` /
per-phase suite is green. **On Spark:** `--gpu` cuDF run matches the CPU artifact within tolerance
(parity test green); time the end-to-end build (feeds P11). The manifest's honesty caveats are
present and match reality.

## Tasks
- [ ] T14.1 Phase 0 clean + module skeleton + `log_road_restrictions.py` cron + `test_clean.py` — *0.5d*
- [ ] T14.2 Phase 1 spatial join (`spatial.py`) + `test_spatial.py` (haversine/bbox/key guard) — *0.5d*
- [ ] T14.3 Phase 2 temporal/during (`temporal.py`) + `test_temporal.py` (boundaries/no-fab) — *0.5d*
- [ ] T14.4 Phase 3 baseline + signed labels (`labels.py`) + `test_labels.py` — *1d*
- [ ] T14.5 Phase 4 openings (`openings.py`) + `test_openings.py` — *1d*
- [ ] T14.6 Phase 5 confounders + matched controls (`confounders.py`) + `test_confounders.py` — *1.5d*
- [ ] T14.7 Phase 6 sim-counterfactual residual (`counterfactual.py`) + `test_counterfactual.py` — *1d*
- [ ] T14.8 Phase 7 packaging + leak-free split + manifest (`package.py`,`cli.py`) + `test_package.py` — *0.5d*
- [ ] T14.9 cuDF↔pandas parity test (`@pytest.mark.spark`) + end-to-end Spark run — *0.5d*

## Risks / fallbacks
- **TMC-during-window coverage is sparse** (most closures have no in-window survey) → that's why
  only ~111/2,696 closures yield rows; Phase 6's sim-counterfactual recovers residuals for sites
  lacking an observed baseline; forward-logging (Phase 0 cron) grows the set over time. Report the
  realized counts; never pad.
- **Opening yield near zero** → keep openings honest (report the count), lean on sim-generated
  opening pairs in P13 Stage-1; real openings remain "calibration-ready."
- **Confounders not separable** → flag `confounder_dominated` and exclude from the clean subset;
  the matched-control DiD anchor is the mitigation, reported with surviving-row counts.
- **cuDF unavailable / version skew on the box** → the pandas CPU path is the source of truth and
  fully tested; cuDF is an accelerator with a parity gate, never the only path.
- **Snapshot staleness / feed drift** (CART schema or UA changes) → `datapipeline/restrictions.py`
  owns the fetch contract; Phase 0 tests pin the expected schema and fail loudly on drift.
