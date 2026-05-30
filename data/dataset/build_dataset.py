"""
Step 2 — Build the road-restriction training dataset with RAPIDS cuDF.

One row per (road restriction  ×  neighbouring count SITE within RADIUS_M),
where a "site" is a physical intersection (centreline_id) — NOT a count_id.
count_id is a single survey day; a site is surveyed on several different days
across 2020-2026, which is what lets us build a before/during baseline.

For each (restriction, site) pair we summarise the traffic recorded on that
neighbouring street *while the restriction was active*, by vehicle class
(cars / trucks / buses / pedestrians / cyclists) and approach direction, and
compare it to a pre-closure baseline at the same site, matched on hour-of-day
and day-of-week so we compare like with like.

Run:    ../../.venv/bin/python build_dataset.py
Prereq: clean_restrictions.py  (writes restrictions_clean.csv)
"""
import cudf
import cupy as cp

TMC_CSV  = "tmc_raw_data_2000-2029.csv"
RES_CSV  = "restrictions_clean.csv"
RADIUS_M = 500           # "neighbouring street" cutoff
BOX_DEG  = 0.006         # ~600 m bounding-box prefilter (cheap, before haversine)
OUT_PARQ = "restriction_traffic_dataset.parquet"
OUT_CSV  = "restriction_traffic_dataset.csv"

CARS  = [f"{d}_appr_cars_{m}"  for d in "nsew" for m in "rtl"]
TRUCK = [f"{d}_appr_truck_{m}" for d in "nsew" for m in "rtl"]
BUS   = [f"{d}_appr_bus_{m}"   for d in "nsew" for m in "rtl"]
PEDS  = [f"{d}_appr_peds"      for d in "nsew"]
BIKE  = [f"{d}_appr_bike"      for d in "nsew"]
VEH   = CARS + TRUCK + BUS

def haversine_m(lat1, lon1, lat2, lon2):
    la1, lo1, la2, lo2 = (cp.radians(cp.asarray(z, dtype=cp.float64))
                          for z in (lat1, lon1, lat2, lon2))
    a = cp.sin((la2-la1)/2)**2 + cp.cos(la1)*cp.cos(la2)*cp.sin((lo2-lo1)/2)**2
    return 6_371_000 * 2 * cp.arcsin(cp.sqrt(a))

def bearing_deg(lat1, lon1, lat2, lon2):
    la1, lo1, la2, lo2 = (cp.radians(cp.asarray(z, dtype=cp.float64))
                          for z in (lat1, lon1, lat2, lon2))
    dlo = lo2 - lo1
    y = cp.sin(dlo) * cp.cos(la2)
    x = cp.cos(la1)*cp.sin(la2) - cp.sin(la1)*cp.cos(la2)*cp.cos(dlo)
    return (cp.degrees(cp.arctan2(y, x)) + 360) % 360

# ── 1. TMC: load, parse time, per-class & directional totals ────────────────────
print("loading TMC …")
tmc = cudf.read_csv(TMC_CSV)
tmc["dt"]   = cudf.to_datetime(tmc["start_time"], format="%Y-%m-%dT%H:%M:%S")
tmc["hour"] = tmc["dt"].dt.hour.astype("int16")
tmc["dow"]  = tmc["dt"].dt.dayofweek.astype("int16")

allnum = CARS + TRUCK + BUS + PEDS + BIKE
tmc[allnum] = tmc[allnum].fillna(0).astype("int32")
tmc["cars"]   = tmc[CARS].sum(axis=1)
tmc["trucks"] = tmc[TRUCK].sum(axis=1)
tmc["buses"]  = tmc[BUS].sum(axis=1)
tmc["peds"]   = tmc[PEDS].sum(axis=1)
tmc["bikes"]  = tmc[BIKE].sum(axis=1)
tmc["vol"]    = tmc[VEH].sum(axis=1)
for d in "nsew":
    tmc[f"dir_{d}"] = tmc[[c for c in VEH if c.startswith(f"{d}_appr")]].sum(axis=1)
tmc["latitude"]  = tmc["latitude"].astype("float64")
tmc["longitude"] = tmc["longitude"].astype("float64")

obs = tmc[["centreline_id", "count_id", "dt", "hour", "dow", "vol",
           "cars", "trucks", "buses", "peds", "bikes",
           "dir_n", "dir_s", "dir_e", "dir_w"]]

# physical sites (centreline_id is 1:1 with location_name)
sites = (tmc.groupby("centreline_id")
            .agg(site_lat=("latitude", "mean"), site_lon=("longitude", "mean"))
            .reset_index())
names = tmc[["centreline_id", "location_name"]].drop_duplicates()
sites = sites.merge(names, on="centreline_id")
print(f"  {len(tmc):,} observations across {len(sites):,} physical sites")

# ── 2. Restrictions: epoch-ms → datetime, duration ──────────────────────────────
print("loading restrictions …")
res = cudf.read_csv(RES_CSV)
res["StartTime"] = cudf.to_datetime(res["StartTime"].astype("int64"), unit="ms")
res["EndTime"]   = cudf.to_datetime(res["EndTime"].astype("int64"),   unit="ms")
res["Latitude"]  = res["Latitude"].astype("float64")
res["Longitude"] = res["Longitude"].astype("float64")
res["duration_days"] = (res["EndTime"] - res["StartTime"]).dt.total_seconds() / 86400
print(f"  {len(res):,} restrictions")

# ── 3. Spatial join: neighbouring sites within RADIUS_M ─────────────────────────
sites["_k"] = 1
res["_k"]   = 1
pairs = sites.merge(res, on="_k").drop(columns="_k")
print(f"  cross join: {len(pairs):,}")
pairs = pairs[
    ((pairs["site_lat"] - pairs["Latitude"]).abs()  <= BOX_DEG) &
    ((pairs["site_lon"] - pairs["Longitude"]).abs() <= BOX_DEG)
].reset_index(drop=True)
pairs["dist_m"] = cudf.Series(haversine_m(
    pairs["Latitude"].values, pairs["Longitude"].values,
    pairs["site_lat"].values, pairs["site_lon"].values))
pairs["bearing_deg"] = cudf.Series(bearing_deg(
    pairs["Latitude"].values, pairs["Longitude"].values,
    pairs["site_lat"].values, pairs["site_lon"].values))
pairs = pairs[pairs["dist_m"] <= RADIUS_M].reset_index(drop=True)
print(f"  restriction × neighbour-site pairs ≤ {RADIUS_M} m: {len(pairs):,}")

# ── 4. Attach every survey at those sites; split during / pre-closure ───────────
cand = pairs[["ID", "centreline_id", "StartTime", "EndTime"]].merge(
    obs, on="centreline_id", how="inner")
during = cand[(cand["dt"] >= cand["StartTime"]) & (cand["dt"] < cand["EndTime"])]
pre    = cand[cand["dt"] < cand["StartTime"]]
print(f"  observations during a closure: {len(during):,}")

during_agg = during.groupby(["ID", "centreline_id"]).agg(
    obs_during=("vol", "count"), survey_days_during=("count_id", "nunique"),
    during_vol_mean=("vol", "mean"), during_vol_sum=("vol", "sum"),
    during_cars=("cars", "mean"), during_trucks=("trucks", "mean"),
    during_buses=("buses", "mean"), during_peds=("peds", "mean"),
    during_bikes=("bikes", "mean"),
    during_dir_n=("dir_n", "mean"), during_dir_s=("dir_s", "mean"),
    during_dir_e=("dir_e", "mean"), during_dir_w=("dir_w", "mean"),
).reset_index()

# ── 5. Baseline: pre-closure, same site ─────────────────────────────────────────
# Tier 1 — match on (hour, dow): the most like-for-like comparison.
# Tier 2 — fall back to (hour) only for pairs Tier 1 can't cover (sparse surveys
#          often miss the exact weekday). `baseline_match` records which was used.
def base_from(matched):
    return matched.groupby(["ID", "centreline_id"]).agg(
        base_n=("vol", "count"), base_survey_days=("count_id", "nunique"),
        base_vol_mean=("vol", "mean"), base_vol_std=("vol", "std"),
        base_cars=("cars", "mean"), base_trucks=("trucks", "mean"),
        base_buses=("buses", "mean"),
    ).reset_index()

slots_hd = during[["ID", "centreline_id", "hour", "dow"]].drop_duplicates()
base_hd = base_from(pre.merge(slots_hd, on=["ID", "centreline_id", "hour", "dow"], how="inner"))
base_hd["baseline_match"] = "hour_dow"

slots_h = during[["ID", "centreline_id", "hour"]].drop_duplicates()
base_h = base_from(pre.merge(slots_h, on=["ID", "centreline_id", "hour"], how="inner"))
base_h["baseline_match"] = "hour"

# prefer the (hour,dow) baseline; use the (hour) baseline only where it's missing
have_hd = base_hd[["ID", "centreline_id"]].copy()
have_hd["_hd"] = 1
base_h = base_h.merge(have_hd, on=["ID", "centreline_id"], how="left")
base_h = base_h[base_h["_hd"].isnull()].drop(columns="_hd")
base_agg = cudf.concat([base_hd, base_h], ignore_index=True)

# ── 6. Assemble + deltas ────────────────────────────────────────────────────────
meta = pairs[["ID", "centreline_id", "location_name", "site_lat", "site_lon",
              "dist_m", "bearing_deg", "Road", "Name", "District", "RoadClass",
              "Planned", "Latitude", "Longitude", "StartTime", "EndTime",
              "duration_days", "MaxImpact", "CurrImpact", "Type", "SubType",
              "DirectionsAffected", "WorkEventType", "Signing"]]
ds = (meta.merge(during_agg, on=["ID", "centreline_id"], how="inner")
          .merge(base_agg,    on=["ID", "centreline_id"], how="left"))

ds["n_neighbour_sites"] = ds.groupby("ID")["centreline_id"].transform("count")
ds["has_baseline"]  = ds["base_n"].notnull().astype("int8")
ds["baseline_match"] = ds["baseline_match"].fillna("none")
ds["vol_delta"]     = ds["during_vol_mean"] - ds["base_vol_mean"]
ds["vol_delta_pct"] = ds["vol_delta"] / ds["base_vol_mean"].where(ds["base_vol_mean"] != 0) * 100
ds["vol_sigma"]     = ds["vol_delta"] / ds["base_vol_std"].where(ds["base_vol_std"] > 0)
ds["direction"]     = (ds["vol_delta"] >= 0).astype("int8")     # 1 = more traffic, 0 = less
ds["significant"]   = (ds["vol_sigma"].abs() > 1.5).astype("int8")

ds = ds.rename(columns={"Latitude": "closure_lat", "Longitude": "closure_lon",
                        "Road": "closure_road", "Name": "closure_name"})

# ── 7. Save ─────────────────────────────────────────────────────────────────────
ds = ds.sort_values(["ID", "dist_m"]).reset_index(drop=True)
ds.to_parquet(OUT_PARQ, index=False)
ds.to_csv(OUT_CSV, index=False)

bl = ds[ds["has_baseline"] == 1]
print("\n=== dataset built ===")
print(f"rows (restriction × neighbour-site):  {len(ds):,}")
print(f"restrictions represented:             {ds['ID'].nunique():,}")
print(f"rows WITH a before/during baseline:   {len(bl):,}")
print(f"  of those, traffic ↑ during closure: {int((bl['direction']==1).sum()):,}")
print(f"  of those, traffic ↓ during closure: {int((bl['direction']==0).sum()):,}")
print(f"  statistically significant (|σ|>1.5):{int(bl['significant'].sum()):,}")
print(f"saved → {OUT_PARQ} / {OUT_CSV}")
cols = ["closure_road", "location_name", "dist_m", "MaxImpact",
        "during_vol_mean", "base_vol_mean", "vol_delta_pct",
        "during_cars", "during_buses"]
print("\nexample rows WITH baseline:")
print(bl[cols].head(12).to_pandas().to_string())
