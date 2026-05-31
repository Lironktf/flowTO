# Research Brief 07 — Feedback-Loop Datasets (closure/opening ground truth + training signals)

> Verified live against the City of Toronto CKAN API, the Toronto Police portal, and primary
> sources on **2026-05-31**. Feeds **P13** (feedback loop) + **P14** (intervention dataset).
> Cross-references `research/01-toronto-datasets.md` for CKAN/TMC/centreline ingest mechanics —
> this brief covers the *new* signals the feedback loop needs and does **not** repeat #01's
> ingest patterns.
>
> **API base:** `https://ckan0.cf.opendata.inter.prod-toronto.ca` · portal `https://open.toronto.ca`.
> **License:** Toronto datasets = Open Government Licence – Toronto v1.0 (attribution:
> `Contains information licensed under the Open Government Licence – Toronto`).

For **each** candidate: source + license, availability (**historical depth** — the make-or-break
axis), temporal/spatial resolution, **join key + time alignment** to TMC/graph, and **role** —
FEATURE, LABEL, CONFOUNDER, or SCENARIO TRIGGER. Ranked impact-vs-effort first.

## Ranking (impact vs effort)

| Rank | Signal | Best source / ID | Historical depth | Geo join | Role | Verdict |
|---|---|---|---|---|---|---|
| 1 | **Road restrictions (closures)** | CART snapshot `v3.csv` (live `road-restrictions` `2265bfca-…`) | snapshot-forward (already captured 2,696) | lat/lon + from/to road → centreline | **LABEL driver** | **Have it.** Live-only feed, but snapshotted; grow via cron. |
| 2 | **TMC counts** (the observation) | `traffic-volumes-at-intersections-for-all-modes` (`811c4c10-…`), `tmc_raw_data_2020_2029` (`262469c2-…`) | 2020→present (+older decade buckets) | `centreline_id` / `px` | **LABEL source** | Sparse/ad-hoc — the binding yield constraint. See #01. |
| 3 | **Weather** (ECCC hourly) | on disk `data/raw/weather/` (Pearson 51459) | 2020→ (extendable via ECCC) | time → all sites | CONFOUNDER + FEATURE | **Have it.** Enrich beyond the 0–3 bucket. Low effort. |
| 4 | **KSI collisions** | `motor-vehicle-collisions-involving-killed-or-seriously-injured-persons` (`73a8e475-…`) | **2006–2026**, daily | **lat/lon** + neighbourhood | CONFOUNDER + LABEL | High impact, low effort. |
| 5 | **Holidays** | Canada Holidays API (`ON`) | 2011–2038 / computable to 2006 | date-only | CONFOUNDER + FEATURE | Very low effort, high value. |
| 6 | **TTC delays** (archive) | `ttc-{bus,streetcar,subway,lrt}-delay-data` | **2014–2025**, monthly | route/stop text → geocode | FEATURE + CONFOUNDER | Low effort; the realtime alerts have **no** archive. |
| 7 | **Venue schedules** | league APIs + Ticketmaster Discovery; FIFA WC fixed dates | sports deep; WC fixed | fixed venue points | SCENARIO TRIGGER | Sharp recurring surges; medium effort. |
| 8 | **Utility-cut permits** | `utility-cut-permits` (`43cbc364-…`, ~87,880) | bulk 2023→ | `DISPLAY_DESC` cross-streets → geocode | LABEL driver (proxy) | Best **public** closure-window proxy; clean dirty dates. |
| 9 | **BDIT RoDARS archive** | `congestion_events.rodars_locations` (City internal) | legacy decades + 2024-03→ | **`centreline_id` direct** | LABEL driver | Ideal GT — **internal, request from BDIT; unverified.** |
| 10 | **Building permits** | active `108c2bd1-…` + cleared `9e42a85b-…` | ~2000→ | address → geocode | LABEL driver (weak proxy) | High false-positive; filter to curb work. |
| 11 | **Festivals & Events** | `festivals-events` (`9201059e-…`) | 2014–16 archive + live; **2017+ gap** | coarse `Area`, **no lat/lon** | SCENARIO TRIGGER | Medium-high effort; geocode venues. |
| 12 | **School calendars** | TDSB/TCDSB per-year PDFs | per-year PDFs | date-only | CONFOUNDER | Medium effort (PDF parse); high value (PA days, breaks). |
| 13 | **Centreline changes** (openings) | `toronto-centreline-tcl` (`1d079757-…`) daily | daily snapshots forward | `CENTRELINE_ID` | SCENARIO TRIGGER | Future "road opening" factor; snapshot diffs. |
| — | **Time-of-day / seasonality** | HAVE — 14-dim context vector | n/a | n/a | FEATURE | Already covered (`utils.CONTEXT_FEATURE_NAMES`). |
| — | **TTC realtime alerts** | `ttc-gtfs-realtime-gtfs-rt` | **NONE — realtime only** | stop_id | TRIGGER (live) | Flagged: no recoverable history. |

---

## A. Closure/opening ground-truth drivers

### A1. Road Restrictions — CART feed (the realized source)
- **Package:** `road-restrictions` (`2265bfca-e845-4613-b341-70ee2ac73fbe`). **Live CART endpoint**
  `https://secure.toronto.ca/opendata/cart/road_restrictions/v3?format=json` (also csv/xml).
- **Live-only / retired** — all resources `datastore_active:false`; the open-data page reads
  "Retired"; there is **no City-published historical archive**.
- **But it was snapshotted:** `data/dataset/v3.csv` (a CART pull) → `restrictions_clean.csv`
  (**2,696 restrictions**). Schema: `ID, Road, Name, District, RoadClass, Planned, Latitude,
  Longitude, StartTime/EndTime (epoch ms), MaxImpact, CurrImpact, Type (CONSTRUCTION/ROAD_CLOSED/…),
  SubType, DirectionsAffected, WorkEventType, Signing`, `geoPolyline` (`[lng,lat]`).
- **Gotchas:** needs a **browser `User-Agent`** (else 403/404); times are **epoch ms**;
  `geoPolyline` is not GeoJSON. Owned by `datapipeline/restrictions.py`.
- **Depth:** snapshot-forward — a pull captures currently-active + planned closures (some
  `StartTime` in the recent past, `EndTime` far future). **Grow it with a daily cron** (P14
  Phase 0) so the real set deepens over time.
- **Join:** `Latitude/Longitude` (+ from/to road) → snap to centreline; time via `StartTime`/
  `EndTime`. **Role:** the **closure-window driver** for the P14 labels.

### A2. BDIT RoDARS archive (ideal, internal — request)
- **`congestion_events.rodars_locations`** — City Big Data Innovation Team Postgres view
  (`rodars_issues` ⋈ `rodars_issue_locations`); time-windows `starttimestamp`/`endtimestamp`/
  proposed, **`centreline_id`** (direct graph join!), `centreline_geom`, `location_description`,
  `lanesaffectedpattern`. Documented in `github.com/CityofToronto/bdit_data-sources`
  (`events/road_permits`). Legacy RODARS ~366k records (back decades) + New RoDARS 2024-03→ ~28k.
- **Status flag:** appears to be an **internal warehouse**, not a public download — could not verify
  public availability. Keeps only the latest version per issue (no edit history). **Action:**
  direct data request to BDIT; if granted, this is the best ground truth (real, centreline-keyed,
  dated, multi-year). **Role:** premium closure-window driver.

### A3. Utility-Cut Permits (best public proxy)
- **`utility-cut-permits`** (`43cbc364-b673-49ca-b98b-8b99c5d5f6eb`, datastore
  `ebdec599-4522-4473-b276-fa07d8638248`, ~**87,880 rows**). Fields: `PERMIT_NUMBER`,
  **`PROPOSED_FROM_DATE`/`PROPOSED_TO_DATE`** (true dig window), `DISPLAY_DESC` (addressed segment
  with cross-streets, e.g. "154 ROBINA AVE (Between GLENHURST AVE AND EARLSDALE AVE)"),
  `INSTALLATION_TYPE_DESC`, `CITY_WARD`, `GEO_ID`, `PERMIT_STATUS`.
- **Depth:** bulk 2023→present. **Caveat:** dirty dates at the extremes (`9960-01-11`, `7003-07-07`
  observed) — clean before use; addresses are City-flagged *approximate*.
- **Join:** geocode `DISPLAY_DESC` → centreline. **Role:** real road/curb-occupation windows; the
  highest-precision **public** closure proxy (utility cuts are literal digs).

### A4. Building permits (weak proxy)
- **`building-permits-active-permits`** (`108c2bd1-6945-46f6-af92-02f5658ee7f7`, ~228,573 rows) +
  **`building-permits-cleared-permits`** (`9e42a85b-180f-4dc5-b0d7-d46661a6c0ec`, cleared-since-2017
  resource ~401,265 rows; a file-only 2000–2016 resource extends back further).
- Fields: `APPLICATION_DATE`, `ISSUED_DATE`, `COMPLETED_DATE`, `PERMIT_TYPE`, `STRUCTURE_TYPE`,
  `WORK`, address (`STREET_NUM/NAME/TYPE/DIRECTION`), `GEO_ID` (**parcel/address point, NOT
  centreline**).
- **Depth:** ~2000→present (application dates back to 1979). **Join:** geocode address → centreline.
- **Role:** weak/moderate proxy for construction *intensity* near roads — most permits cause no
  road impact and the issued→completed window is far looser than a closure. Filter to
  new-build/demolition near the curb; expect high false-positive. Use only to enrich, not as a
  primary label.

### A5. Archived CART snapshots (sparse validation)
- **Internet Archive Wayback** has real full-payload captures of
  `secure.toronto.ca/opendata/cart/road_restrictions` — notably **2021-10** (v1/v2 JSON+XML) and
  **2025-10** (v3 csv/json/xml, ~267–315 KB). Thin/redirect captures in 2023-12, 2024-07 are
  empty. No third-party longitudinal dump exists (Kaggle/data.world/GitHub checked).
- **Role:** a handful of dated native-schema closure cross-sections — useful to **validate** the
  snapshot/proxy pipeline, not to train.

---

## B. Confounders & features (isolate the intervention effect)

### B1. Weather — ECCC hourly (HAVE; enrich)
- **On disk:** `data/raw/weather/weather_YYYY_MM.csv` (Pearson station 51459), hourly. Fields:
  `Temp (°C)`, `Dew Point`, `Rel Hum (%)`, **`Precip. Amount (mm)`**, `Wind Dir/Spd`,
  **`Visibility (km)`**, `Stn Press`, `Weather` text. Normalized by `datapipeline/weather.py`
  (categories clear/rain/snow/fog/storm).
- **Today the GNN uses a coarse 0–3 bucket + clear/rain/snow flags + temp/precip
  (`utils.CONTEXT_FEATURE_NAMES`).** **Enrich** to continuous temp, precip mm, snow depth proxy,
  visibility, wind — these change capacity and demand and are a prime **confounder** for closure
  windows. **Depth:** 2020→ on disk; ECCC station-data API extends it. **Join:** hour → all sites
  (single station; add more ECCC stations for spatial weather if needed). **Role:** CONFOUNDER +
  FEATURE.

### B2. KSI collisions (incident confounder)
- **`motor-vehicle-collisions-involving-killed-or-seriously-injured-persons`** (City package,
  resource `73a8e475-…`), daily refresh, **20,519 rows, 2006–2026**. Fields: `accdate`,
  street names, `acclass`, `impactype`, `visible` (weather), `light`, **`rdsfcond`** (road surface),
  `road_class`, **`longitude`/`latitude`**, `neighbourhood`, plus flags (`pedestrian`, `cyclist`,
  `heavy_truck`, …). (Broader non-KSI "all collisions" lives on `data.tps.ca` but is
  intersection-offset/aggregated — coarser geo; use only if non-injury volume is needed.)
- **Join:** point lat/lon → snap to centreline; date → window. **Role:** CONFOUNDER (a collision
  causes the congestion you'd otherwise attribute to the closure — flag/exclude in P14 Phase 5) and
  a potential safety **LABEL**.

### B3. Holidays & school calendars (baseline-shift confounders)
- **Holidays:** **not** on CKAN. Use the **Canada Holidays API** (`canada-holidays.ca/api`,
  open-source `pcraig3/hols`), province `ON`, 2011–2038; Ontario stat holidays are also computable
  to 2006. **Role:** CONFOUNDER + FEATURE (date flag).
- **School calendars:** **not** machine-readable on CKAN (only school *locations*:
  `school-locations-all-types`, `tcdsb-schools`, `toronto-district-school-board-locations`).
  Authoritative = **TDSB/TCDSB per-year PDFs** (first/last day, PA days, March/winter break) —
  parse per year. **Role:** CONFOUNDER (PA days + breaks are major repeatable demand breaks);
  becomes spatial if combined with school-location datasets to flag school-zone roads.

### B4. TTC disruptions (mode-shift)
- **Realtime alerts:** `ttc-gtfs-realtime-gtfs-rt` (feed `gtfsrt.ttc.ca`) — **realtime only, NO
  archive** (overwritten each poll). **Flag:** history is unrecoverable unless self-captured.
- **Historical substitute:** **delay** datasets `ttc-bus-delay-data`, `ttc-streetcar-delay-data`,
  `ttc-subway-delay-data`, `ttc-lrt-delay-data` — monthly, resources span **2014–2025**; per-incident
  (date, time, route/line, location text, delay minutes, cause). **Join:** route + location text →
  geocode → nearest centreline. **Role:** FEATURE/CONFOUNDER (disruptions divert riders to cars and
  alter surface-transit road interference). For online inference the realtime feed is a **TRIGGER**.

---

## C. Scenario triggers (demand surges)

### C1. FIFA World Cup 2026 (the demo trigger)
- **6 matches at BMO Field**, exact dates/times: **Jun 12** (Canada, 15:00), **Jun 17** (19:00),
  **Jun 20** (16:00), **Jun 23** (19:00), **Jun 26** (15:00), **Jul 2** (R32, 19:00). Venue is a
  fixed point (BMO Field) → snap once to centreline; events join by date+time. **Role:** SCENARIO
  TRIGGER (localized demand surge) + the P12 demo tie-in. Ties directly to the "fix" (opening/
  capacity-add) scenarios the optimizer proposes.

### C2. Venue schedules (recurring surges)
- No government feed. **Sports** (free, deep): league schedule APIs — MLB Stats API (Blue Jays /
  Rogers Centre), MLSE schedules (Leafs/Raptors/TFC/Argos at Scotiabank Arena / BMO). **Concerts:**
  Ticketmaster Discovery API (venue-keyed, lat/lon) or PredictHQ (paid, purpose-built demand
  signal). Venues are **fixed points** → only the event *dates* are needed. **Role:** SCENARIO
  TRIGGER (sharp, recurring, spatially concentrated surges).

### C3. Festivals & Events (city festivals)
- **`festivals-events`** (`9201059e-43ed-4369-885e-0b867652feac`), real-time file-only JSON feed
  (behind an auth-gated `secure.toronto.ca` origin — fetch the whole blob, not queryable). A static
  **2014–2016** XML archive (resource `74c4c0b7-…`, 38,481 entries) exists; **2017–present is a
  gap** unless self-scraped. Historical schema: `EventName`, **`Area`** (coarse district, **no
  lat/lon**), `DateBeginShow`/`DateEndShow`, times, category. **Join:** geocode venue/Area → nearest
  centreline (weak). **Role:** SCENARIO TRIGGER (coarse).

### C4. Centreline network changes — the "road opening" factor
- **`toronto-centreline-tcl`** (`1d079757-377b-4564-82df-eb5638583bfb`) refreshes **daily**.
  Diffing daily/periodic snapshots surfaces **new `CENTRELINE_ID`s** (genuine road openings) and
  `CENTRELINE_STATUS` changes. No historical archive of diffs is published → start snapshotting now.
  **Role:** SCENARIO TRIGGER for the genuine-opening case (P14 Phase 4 future hook); complements the
  reopening-from-restriction-`EndTime` signal.

---

## D. Already covered (don't re-add)
- **Time-of-day / seasonality** — the baseline GNN's 14-dim context vector already encodes hour,
  day-of-week, month, weekend, rush-hour, season one-hot (`utils.CONTEXT_FEATURE_NAMES`). Reuse as
  is; no new dataset.
- **TMC schema, centreline join, CKAN mechanics, the live-feed UA caveat** — see
  `research/01-toronto-datasets.md`. This brief does not repeat them.

## Could-not-verify / flags
- **BDIT RoDARS** public availability (appears internal — request to confirm).
- **Festivals live feed** current field list (auth-gated origin refused a direct pull; only the
  2014–16 archive schema is byte-confirmed).
- **Utility-cut** date columns are dirty at the extremes (confirmed) — clean required.
- **TTC realtime alerts** and **Centreline diffs** have **no published history** — capture forward.
- The on-disk TMC file is a ~120k-row subset (2020–2022) of the full 346k-row CKAN dump (+ older
  decade buckets) — the full corpus is larger but structurally as sparse.
