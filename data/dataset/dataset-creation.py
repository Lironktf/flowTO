import cudf
import cupy as cp

# ── 1. Load TMC ────────────────────────────────────────────────────────────────
tmc = cudf.read_csv("tmc_raw_data_2000-2029.csv",
                    dtype={"count_date": "str",
                           "start_time": "str",
                           "end_time": "str"})

# start_time is already a full ISO datetime — parse it directly, no concatenation needed
tmc["count_datetime"] = cudf.to_datetime(tmc["start_time"], format="%Y-%m-%dT%H:%M:%S")
tmc["hour"]     = tmc["count_datetime"].dt.hour
tmc["dow"]      = tmc["count_datetime"].dt.dayofweek
tmc["date_str"] = tmc["count_datetime"].dt.strftime("%Y-%m-%d")

print(f"TMC rows loaded: {len(tmc):,}")
print(tmc[["location_name", "count_datetime", "latitude", "longitude"]].head())

# ── 2. Load Road Restrictions ──────────────────────────────────────────────────
# It's a CSV, not XML — read directly
restrictions = cudf.read_csv("v3.csv")

# Inspect timestamp format before parsing
print("Raw StartTime sample:", restrictions["StartTime"].head())

restrictions["StartTime"]  = cudf.to_datetime(restrictions["StartTime"],
                                               format="%Y-%m-%dT%H:%M:%S")
restrictions["EndTime"]    = cudf.to_datetime(restrictions["EndTime"],
                                               format="%Y-%m-%dT%H:%M:%S")
restrictions["start_hour"] = restrictions["StartTime"].dt.hour
restrictions["start_dow"]  = restrictions["StartTime"].dt.dayofweek
restrictions["Latitude"]   = restrictions["Latitude"].astype("float32")
restrictions["Longitude"]  = restrictions["Longitude"].astype("float32")

print(f"Restriction events loaded: {len(restrictions):,}")
print(restrictions[["Name", "Road", "StartTime", "EndTime", "MaxImpact"]].head())

# ── 3. Compute total volume per TMC row ────────────────────────────────────────
car_cols   = [c for c in tmc.columns if "cars"  in c]
truck_cols = [c for c in tmc.columns if "truck" in c]
bus_cols   = [c for c in tmc.columns if "_bus_" in c]
all_vehicle_cols = car_cols + truck_cols + bus_cols

tmc[all_vehicle_cols] = tmc[all_vehicle_cols].fillna(0).astype("int32")
tmc["total_volume"] = tmc[all_vehicle_cols].sum(axis=1)

for direction in ["n", "s", "e", "w"]:
    dir_cols = [c for c in all_vehicle_cols if c.startswith(f"{direction}_appr")]
    tmc[f"{direction}_total"] = tmc[dir_cols].sum(axis=1)

print(tmc[["location_name", "count_datetime", "total_volume",
           "n_total", "s_total", "e_total", "w_total"]].head(10))

# ── 4. Spatial join with bounding box pre-filter ───────────────────────────────
tmc_locations = tmc[["count_id", "location_name",
                      "latitude", "longitude"]].drop_duplicates()
tmc_locations["latitude"]  = tmc_locations["latitude"].astype("float32")
tmc_locations["longitude"] = tmc_locations["longitude"].astype("float32")

restrictions_small = restrictions[["ID", "Name", "Road", "StartTime", "EndTime",
                                   "Latitude", "Longitude", "MaxImpact",
                                   "Type", "SubType"]]

DEGREE_RADIUS = 0.003  # ~300 m at Toronto's latitude

tmc_locations["_key"]      = 1
restrictions_small = restrictions_small.copy()
restrictions_small["_key"] = 1

crossed = tmc_locations.merge(restrictions_small, on="_key").drop(columns=["_key"])
print(f"Raw cross-join size: {len(crossed):,}")

# Bounding box filter first (cheap) — then haversine on reduced set
crossed = crossed[
    ((crossed["latitude"]  - crossed["Latitude"]).abs()  <= DEGREE_RADIUS) &
    ((crossed["longitude"] - crossed["Longitude"]).abs() <= DEGREE_RADIUS)
].reset_index(drop=True)
print(f"After bounding box filter: {len(crossed):,}")

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000
    lat1 = cp.radians(cp.asarray(lat1))
    lon1 = cp.radians(cp.asarray(lon1))
    lat2 = cp.radians(cp.asarray(lat2))
    lon2 = cp.radians(cp.asarray(lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = cp.sin(dlat/2)**2 + cp.cos(lat1) * cp.cos(lat2) * cp.sin(dlon/2)**2
    return R * 2 * cp.arcsin(cp.sqrt(a))

dist_m = haversine_m(crossed["latitude"].values,  crossed["longitude"].values,
                     crossed["Latitude"].values,   crossed["Longitude"].values)
crossed["dist_m"] = cudf.Series(dist_m)

RADIUS_M = 300
nearby = crossed[crossed["dist_m"] <= RADIUS_M].reset_index(drop=True)
print(f"Restriction–TMC pairs within {RADIUS_M}m: {len(nearby):,}")

# ── 5. Temporal join — TMC counts during each event ───────────────────────────
tmc_with_key = tmc[["count_id", "count_datetime", "hour", "dow",
                     "total_volume", "n_total", "s_total",
                     "e_total", "w_total"]]

event_tmc = nearby.merge(tmc_with_key, on="count_id", how="inner")

during_event = event_tmc[
    (event_tmc["count_datetime"] >= event_tmc["StartTime"]) &
    (event_tmc["count_datetime"] <  event_tmc["EndTime"])
]
print(f"TMC observations during events: {len(during_event):,}")

# ── 6. Build baseline ──────────────────────────────────────────────────────────
during_keys = during_event[["count_id", "count_datetime"]].drop_duplicates()
during_keys["_is_event"] = cudf.Series(cp.ones(len(during_keys), dtype=bool))  # fixed

tmc_tagged = tmc_with_key.merge(during_keys, on=["count_id", "count_datetime"],
                                 how="left")
tmc_tagged["_is_event"] = tmc_tagged["_is_event"].fillna(False).astype(bool)  # fixed

tmc_baseline = tmc_tagged[~tmc_tagged["_is_event"]]

baseline_stats = (
    tmc_baseline
    .groupby(["count_id", "hour", "dow"])
    .agg(
        baseline_mean   = ("total_volume", "mean"),
        baseline_std    = ("total_volume", "std"),
        baseline_median = ("total_volume", "median"),
        baseline_n      = ("total_volume", "count"),
    )
    .reset_index()
)
print("Baseline stats sample:")
print(baseline_stats.head(10))

# ── 7. Aggregate event volumes and compute deltas ─────────────────────────────
during_agg = (
    during_event
    .groupby(["ID", "count_id", "Name", "Road", "location_name",
              "StartTime", "EndTime", "MaxImpact", "Type", "SubType",
              "dist_m", "hour", "dow"])
    .agg(
        event_mean_volume  = ("total_volume", "mean"),
        event_total_volume = ("total_volume", "sum"),
        event_observations = ("total_volume", "count"),
        event_n_flow       = ("n_total", "mean"),
        event_s_flow       = ("s_total", "mean"),
        event_e_flow       = ("e_total", "mean"),
        event_w_flow       = ("w_total", "mean"),
    )
    .reset_index()
)

dataset = during_agg.merge(baseline_stats, on=["count_id", "hour", "dow"], how="left")

dataset["volume_delta"] = dataset["event_mean_volume"] - dataset["baseline_mean"]

# fixed: use .where() instead of .replace() for cuDF
safe_baseline = dataset["baseline_mean"].where(dataset["baseline_mean"] != 0,
                                                other=float("nan"))
dataset["volume_delta_pct"] = (dataset["volume_delta"] / safe_baseline) * 100

# fixed: fill NaN std before dividing
safe_std = dataset["baseline_std"].fillna(
    dataset["baseline_mean"] * 0.2
).where(dataset["baseline_std"] != 0, other=float("nan"))
dataset["sigma_deviation"]    = dataset["volume_delta"] / safe_std
dataset["significant_impact"] = dataset["sigma_deviation"].abs() > 1.5

print("\n=== SAMPLE OUTPUT ===")
print(dataset[["Name", "Road", "StartTime", "location_name", "dist_m",
               "baseline_mean", "event_mean_volume",
               "volume_delta", "volume_delta_pct",
               "sigma_deviation", "significant_impact"]].head(15).to_string())

# ── 8. Save ────────────────────────────────────────────────────────────────────
dataset.to_parquet("closure_impact_labeled.parquet", index=False)

high_confidence = dataset[
    (dataset["baseline_n"]        >= 10) &
    (dataset["event_observations"] >= 2) &
    (dataset["baseline_mean"]      >  50)
]
high_confidence.to_parquet("closure_impact_highconf.parquet", index=False)

print(f"Total labeled pairs:    {len(dataset):,}")
print(f"High-confidence pairs:  {len(high_confidence):,}")
print(f"Significant impacts:    {dataset['significant_impact'].sum():,}")
