"""
Turn real Toronto open data into a training dataset for the demand model.

Inputs (place under data/raw/ — see scripts/fetch_data.sh):
  * TMC counts:  data/raw/tmc_raw_data_*.csv
        City of Toronto "Traffic Volumes - Multimodal Intersection Turning
        Movement Counts". One row = one 15-min interval at one intersection.
        Real columns (verified from the open-data dump):
          _id, count_id, count_date, location_name, longitude, latitude,
          centreline_type, centreline_id, px, start_time, end_time,
          {n,s,e,w}_appr_{cars,truck,bus}_{r,t,l}, ..._peds, ..._bike
  * Weather:     data/raw/weather/*.csv
        Environment & Climate Change Canada hourly observations (e.g. Toronto
        Pearson, stationID 51459). Columns include Year, Month, Day,
        Time (LST), Temp (°C), Precip. Amount (mm), and Weather (text).

Output:
  * data/model/training_dataset.csv    (FEATURE_ORDER + vehicle_count)
  * data/model/validation_dataset.csv  (held-out, grouped by intersection so
                                         none appears in both train and val)

Pipeline:
  1. Sum the car/truck/bus movement columns -> vehicles per 15-min bin.
  2. Aggregate the four 15-min bins -> hourly vehicle_count per (intersection,
     date, hour).
  3. Snap each intersection (lat/lon) to its nearest graph node and attach that
     node's static features. Counts farther than --max-snap-m from any node are
     dropped (outside the current graph's coverage).
  4. Join hourly weather by timestamp (LST) -> weather_code.
  5. Write a grouped train/val split.

Run:
    python -m src.model.ingest_real_data
    python -m src.model.ingest_real_data --max-snap-m 300 --val-frac 0.2
"""

from __future__ import annotations

import argparse
import glob
import math
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .features import (
    DOWNTOWN_LATLON,
    compute_static_node_features,
    weather_code,
)
from .train_demand_model import GRAPH_JSON, TRAINING_CSV

_THIS = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS, "..", "..", ".."))
RAW_DIR = os.path.join(_REPO_ROOT, "data", "raw")
WEATHER_DIR = os.path.join(RAW_DIR, "weather")
VALIDATION_CSV = os.path.join(_REPO_ROOT, "data", "model", "validation_dataset.csv")

# TMC vehicle movement columns: approach × {cars,truck,bus} × turn.
_APPR = ["n", "s", "e", "w"]
_VEH = ["cars", "truck", "bus"]
_TURNS = ["r", "t", "l"]
VEHICLE_COLS = [f"{a}_appr_{v}_{t}" for a in _APPR for v in _VEH for t in _TURNS]

# Map ECCC free-text "Weather" to our categories (substring match, lowercased).
_WX_KEYWORDS = [
    ("snow", "snow"), ("ice", "snow"), ("blowing snow", "snow"),
    ("rain", "rain"), ("drizzle", "rain"), ("shower", "rain"), ("thunder", "rain"),
    ("fog", "fog"), ("mist", "fog"), ("haze", "fog"),
    ("cloud", "cloud"), ("overcast", "cloud"),
    ("clear", "clear"), ("sunny", "clear"), ("fair", "clear"),
]


def _first_col(df, *names):
    for n in names:
        if n in df.columns:
            return n
    return None


# ---------------------------------------------------------------------------
# Nearest-node snapping (KD-tree in local metres for speed + accuracy)
# ---------------------------------------------------------------------------

class _NodeSnapper:
    def __init__(self, static_feats: Dict[object, dict]):
        from scipy.spatial import cKDTree

        self.nodes = list(static_feats.keys())
        lat0 = DOWNTOWN_LATLON[0]
        self._mlat = 111_320.0
        self._mlon = 111_320.0 * math.cos(math.radians(lat0))
        pts = np.array([
            [static_feats[n]["lat"] * self._mlat,
             static_feats[n]["lon"] * self._mlon]
            for n in self.nodes
        ])
        self.tree = cKDTree(pts)
        self.static = static_feats

    def snap(self, lat: float, lon: float):
        q = np.array([lat * self._mlat, lon * self._mlon])
        dist, idx = self.tree.query(q)
        return self.nodes[idx], float(dist)


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

def _normalize_weather(text) -> Optional[str]:
    if text is None or (isinstance(text, float) and math.isnan(text)):
        return None
    t = str(text).strip().lower()
    if not t or t == "na":
        return None
    for kw, cat in _WX_KEYWORDS:
        if kw in t:
            return cat
    return None


def load_weather(weather_dir: str = WEATHER_DIR) -> Dict[tuple, str]:
    """Build {(year, month, day, hour): weather_category} from ECCC CSVs.

    Falls back to deriving the category from precip/temperature when the text
    Weather column is blank/NA (very common in ECCC hourly data).
    """
    files = sorted(glob.glob(os.path.join(weather_dir, "*.csv")))
    lookup: Dict[tuple, str] = {}
    if not files:
        print(f"[weather] none in {weather_dir}; weather will default to 'clear'")
        return lookup

    frames = []
    for f in files:
        try:
            frames.append(pd.read_csv(f, low_memory=False))
        except Exception as e:  # noqa: BLE001
            print(f"[weather] skip {os.path.basename(f)}: {e}")
    if not frames:
        return lookup
    wx = pd.concat(frames, ignore_index=True)

    c_year = _first_col(wx, "Year")
    c_month = _first_col(wx, "Month")
    c_day = _first_col(wx, "Day")
    c_time = _first_col(wx, "Time (LST)", "Time")
    c_wx = _first_col(wx, "Weather")
    c_precip = _first_col(wx, "Precip. Amount (mm)")
    c_temp = _first_col(wx, "Temp (°C)", "Temp (C)", "Temp")
    if None in (c_year, c_month, c_day, c_time):
        print("[weather] missing Year/Month/Day/Time columns; defaulting to clear")
        return lookup

    for _, row in wx.iterrows():
        try:
            y = int(row[c_year])
            mo = int(row[c_month])
            d = int(row[c_day])
            hh = int(str(row[c_time]).split(":")[0])
        except (ValueError, TypeError):
            continue
        cat = _normalize_weather(row[c_wx]) if c_wx else None
        if cat is None:
            try:
                precip = float(row[c_precip]) if c_precip else 0.0
            except (TypeError, ValueError):
                precip = 0.0
            if precip and precip > 0:
                try:
                    temp = float(row[c_temp]) if c_temp else 10.0
                except (TypeError, ValueError):
                    temp = 10.0
                cat = "snow" if temp <= 0 else "rain"
            else:
                cat = "clear"
        lookup[(y, mo, d, hh)] = cat
    print(f"[weather] loaded {len(lookup):,} hourly records from {len(files)} file(s)")
    return lookup


# ---------------------------------------------------------------------------
# TMC counts
# ---------------------------------------------------------------------------

def load_tmc(raw_dir: str = RAW_DIR) -> pd.DataFrame:
    """Load + concatenate TMC raw CSVs into a tidy frame with a vehicle total.

    Resolves the real open-data column names and derives time parts from
    `start_time` (ISO, e.g. '2020-03-10T13:30:00').
    """
    files = sorted(glob.glob(os.path.join(raw_dir, "tmc_raw_data_*.csv")))
    if not files:
        raise FileNotFoundError(
            f"no tmc_raw_data_*.csv in {raw_dir} — see scripts/fetch_data.sh")
    frames = []
    for f in files:
        df = pd.read_csv(f, low_memory=False)
        frames.append(df)
        print(f"[tmc] {os.path.basename(f)}: {len(df):,} rows")
    df = pd.concat(frames, ignore_index=True)

    c_lat = _first_col(df, "latitude", "lat")
    c_lon = _first_col(df, "longitude", "lng", "lon")
    c_loc = _first_col(df, "centreline_id", "location_id", "location_name")
    c_start = _first_col(df, "start_time", "time_start")
    if None in (c_lat, c_lon, c_loc, c_start):
        raise ValueError(f"TMC file missing expected columns; got {list(df.columns)[:15]}")

    present = [c for c in VEHICLE_COLS if c in df.columns]
    if not present:
        raise ValueError("TMC file has none of the expected vehicle movement columns")
    df[present] = df[present].apply(pd.to_numeric, errors="coerce").fillna(0)
    df["veh_15min"] = df[present].sum(axis=1)

    ts = pd.to_datetime(df[c_start], errors="coerce")
    df = df.assign(
        loc_id=df[c_loc], lat=pd.to_numeric(df[c_lat], errors="coerce"),
        lon=pd.to_numeric(df[c_lon], errors="coerce"), ts=ts,
    ).dropna(subset=["loc_id", "lat", "lon", "ts"])
    df["year"] = df["ts"].dt.year
    df["month"] = df["ts"].dt.month
    df["day"] = df["ts"].dt.day
    df["hour"] = df["ts"].dt.hour
    df["day_of_week"] = df["ts"].dt.dayofweek  # Mon=0
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
    return df


def build_dataset(
    graph_json: str = GRAPH_JSON,
    raw_dir: str = RAW_DIR,
    weather_dir: str = WEATHER_DIR,
    max_snap_m: float = 300.0,
) -> pd.DataFrame:
    """Produce the full (unsplit) training frame in FEATURE_ORDER + target."""
    from ..graph.config import haversine_m
    from ..graph.routing import import_graph_json

    graph = import_graph_json(graph_json)
    static = compute_static_node_features(graph)
    snapper = _NodeSnapper(static)
    weather = load_weather(weather_dir)

    df = load_tmc(raw_dir)

    # Aggregate 15-min bins -> hourly volume per (intersection, date, hour).
    grp = (df.groupby(["loc_id", "year", "month", "day", "hour",
                       "day_of_week", "is_weekend"], as_index=False)
             .agg(vehicle_count=("veh_15min", "sum"),
                  lat=("lat", "first"), lon=("lon", "first")))
    print(f"[ingest] {len(grp):,} hourly location-records before snapping")

    # Snap unique intersections once.
    uniq = grp.drop_duplicates("loc_id")[["loc_id", "lat", "lon"]]
    snap_node, snap_dist = {}, {}
    for _, r in uniq.iterrows():
        node, dist = snapper.snap(float(r["lat"]), float(r["lon"]))
        snap_node[r["loc_id"]] = node
        snap_dist[r["loc_id"]] = dist
    grp["node"] = grp["loc_id"].map(snap_node)
    grp["snap_m"] = grp["loc_id"].map(snap_dist)

    before = len(grp)
    grp = grp[grp["snap_m"] <= max_snap_m].copy()
    print(f"[ingest] kept {len(grp):,}/{before:,} records within {max_snap_m:.0f} m "
          f"of a graph node ({grp['loc_id'].nunique()} intersections)")
    if grp.empty:
        raise ValueError(
            "no counts fell within the graph. The current graph is downtown-"
            "only; rebuild for the full city (build_graph.py --full) or raise "
            "--max-snap-m.")

    dlat, dlon = DOWNTOWN_LATLON
    rows: List[dict] = []
    for _, r in grp.iterrows():
        sf = static[r["node"]]
        wx = weather.get((int(r["year"]), int(r["month"]), int(r["day"]),
                          int(r["hour"])), "clear")
        rows.append({
            "location_id": r["loc_id"],
            "node_id": r["node"],
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "hour": int(r["hour"]),
            "day_of_week": int(r["day_of_week"]),
            "month": int(r["month"]),
            "is_weekend": int(r["is_weekend"]),
            "weather": wx,
            "weather_code": weather_code(wx),
            "road_degree": sf["road_degree"],
            "distance_to_downtown": haversine_m(
                float(r["lat"]), float(r["lon"]), dlat, dlon) / 1000.0,
            "near_highway": sf["near_highway"],
            "road_class_rank": sf["road_class_rank"],
            "vehicle_count": float(r["vehicle_count"]),
        })
    out = pd.DataFrame(rows)
    out = out[out["vehicle_count"] >= 0]
    print(f"[ingest] final dataset: {len(out):,} rows, "
          f"vehicle_count mean={out['vehicle_count'].mean():.0f} "
          f"max={out['vehicle_count'].max():.0f}")
    print(f"[ingest] weather mix: {out['weather'].value_counts().to_dict()}")
    return out


def split_and_write(
    df: pd.DataFrame,
    train_path: str = TRAINING_CSV,
    val_path: str = VALIDATION_CSV,
    val_frac: float = 0.2,
    seed: int = 42,
) -> None:
    """Grouped split by intersection so one never spans train & val."""
    from sklearn.model_selection import GroupShuffleSplit

    groups = df["location_id"].to_numpy()
    n_groups = df["location_id"].nunique()
    if n_groups < 2:
        # Not enough distinct intersections to group-split; fall back to random.
        val_df = df.sample(frac=val_frac, random_state=seed)
        train_df = df.drop(val_df.index)
        print(f"[split] only {n_groups} intersection(s); using a random split")
    else:
        gss = GroupShuffleSplit(n_splits=1, test_size=val_frac, random_state=seed)
        tr_idx, va_idx = next(gss.split(df, groups=groups))
        train_df, val_df = df.iloc[tr_idx], df.iloc[va_idx]

    os.makedirs(os.path.dirname(train_path), exist_ok=True)
    train_df.to_csv(train_path, index=False)
    val_df.to_csv(val_path, index=False)
    print(f"[split] train={len(train_df):,} rows "
          f"({train_df['location_id'].nunique()} intersections) -> {train_path}")
    print(f"[split] val  ={len(val_df):,} rows "
          f"({val_df['location_id'].nunique()} intersections) -> {val_path}")


def main(argv=None):
    p = argparse.ArgumentParser(description="Ingest real Toronto data -> training CSVs.")
    p.add_argument("--graph", default=GRAPH_JSON)
    p.add_argument("--raw-dir", default=RAW_DIR)
    p.add_argument("--weather-dir", default=WEATHER_DIR)
    p.add_argument("--max-snap-m", type=float, default=300.0,
                   help="Max distance (m) from a count to a graph node to keep it.")
    p.add_argument("--val-frac", type=float, default=0.2)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    df = build_dataset(args.graph, args.raw_dir, args.weather_dir, args.max_snap_m)
    split_and_write(df, val_frac=args.val_frac, seed=args.seed)


if __name__ == "__main__":
    main()
