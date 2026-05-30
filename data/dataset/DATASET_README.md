# `restriction_traffic_dataset` — road-restriction impact training set

One row per **(road restriction × neighbouring count site within 500 m)**. For
each pair it records the traffic measured on that neighbouring street *while the
restriction was active*, by vehicle class and direction, plus a pre-closure
baseline at the same site and the resulting deltas (the training labels).

Built by `build_dataset.py` (RAPIDS cuDF) from:
- `tmc_raw_data_2000-2029.csv` — City of Toronto TMC turning-movement counts (15-min).
- `v3.csv` → `restrictions_clean.csv` — City of Toronto road restrictions.

Regenerate: `python clean_restrictions.py && python build_dataset.py`
(uses the repo `.venv` with `cudf-cu13`).

## How a "site" is defined — read this first
`count_id` in the TMC file is **a single survey day**, not a location. The site
key is therefore **`centreline_id`** (the intersection), which is surveyed on
several different days across 2020-2026. The baseline for a closure is *other
survey days at the same intersection, before the closure started*. Joining on
`count_id` instead silently yields a zero baseline — don't.

## Coverage & honest limits
- 313 pair rows, **111** distinct restrictions (of 2,696). Only restrictions
  that happened to have a TMC survey *during* their window appear — TMC counts
  are sparse manual snapshots, so most closures have none.
- **173** rows carry a before/during baseline (`has_baseline=1`); the rest have
  during-traffic only.
- Direction of effect: **109 down, 64 up.** A closure usually *lowers* volume on
  the closed segment and nearby streets; increases show up on detour routes
  (e.g. Bay/King, Dundas/Victoria). **Use `direction`/`vol_delta` as a signed
  label — do not assume a closure means more traffic.**
- Knobs in `build_dataset.py`: `RADIUS_M` (neighbour cutoff) and the baseline
  matching tier (see `baseline_match`).

## Columns
### Identity / geometry
| column | meaning |
|---|---|
| `ID` | restriction id (from the city feed) |
| `centreline_id` | TMC site (intersection) id — the site key |
| `location_name` | intersection name |
| `site_lat`,`site_lon` | site coordinates |
| `closure_lat`,`closure_lon` | restriction coordinates |
| `dist_m` | metres from closure to site (haversine) |
| `bearing_deg` | compass bearing closure→site (0=N, 90=E) |
| `n_neighbour_sites` | how many sites this restriction has in the set |

### Restriction attributes (features)
| column | meaning |
|---|---|
| `closure_road`,`closure_name` | road + description |
| `District`,`RoadClass` | e.g. EAST YORK; Local/Major Arterial/Expressway |
| `Planned` | 1 = planned work, 0 = unplanned |
| `StartTime`,`EndTime`,`duration_days` | active window |
| `MaxImpact`,`CurrImpact` | Low/Medium/High |
| `Type`,`SubType` | CONSTRUCTION / ROAD_CLOSED / HAZARD … |
| `DirectionsAffected` | ONE_DIRECTION / … |
| `WorkEventType`,`Signing` | permit metadata |

### Traffic *during* the closure (mean per 15-min interval unless noted)
| column | meaning |
|---|---|
| `obs_during` | # of 15-min observations |
| `survey_days_during` | # of distinct survey days during the window |
| `during_vol_mean`,`during_vol_sum` | total motor-vehicle volume |
| `during_cars`,`during_trucks`,`during_buses` | by class |
| `during_peds`,`during_bikes` | pedestrians, cyclists |
| `during_dir_n/s/e/w` | vehicle volume by approach direction |

### Pre-closure baseline (same site, matched time-of-day)
| column | meaning |
|---|---|
| `has_baseline` | 1 if a baseline exists |
| `baseline_match` | `hour_dow` (strict) · `hour` (fallback) · `none` |
| `base_n`,`base_survey_days` | baseline sample size |
| `base_vol_mean`,`base_vol_std` | baseline total volume |
| `base_cars`,`base_trucks`,`base_buses` | by class |

### Labels
| column | meaning |
|---|---|
| `vol_delta` | `during_vol_mean − base_vol_mean` |
| `vol_delta_pct` | delta as % of baseline |
| `vol_sigma` | delta in baseline std-devs |
| `direction` | 1 = more traffic during closure, 0 = less |
| `significant` | 1 if \|`vol_sigma`\| > 1.5 |
