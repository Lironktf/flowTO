"""Measured baseline congestion from raw TMC counts — no ML, no equilibrium.

On open (no edits) the map shows the *measured* historical congestion for the
selected day/time, read straight from the Turning-Movement-Count dataset and
averaged across years — the model is reserved for predicting how traffic
*changes* once the user edits the network.

Pipeline (built once at startup, then a per-(day_of_week, hour) lookup):

1. Aggregate the raw TMC CSV to a mean **hourly** inbound volume per
   ``(count_id, day_of_week, hour)`` and per compass approach (N/S/E/W),
   averaged across all years/months. 15-min bins → hourly via ×4.
2. Snap each survey location (lat/lon) to the nearest graph node (≤300 m).
3. For each node, classify its incident *in*-edges by which side the upstream
   neighbour sits on (N/S/E/W) and assign that approach's volume as the edge
   ``load``.
4. ``load / capacity`` → pressure → travel time (reusing the simulation's
   ``congestion_multiplier``), emitted as the same ``Record5`` tuples the binary
   frames / map renderer already consume.

Times/days outside the survey window (nights, weekends) and the ~90% of streets
with no nearby count stay free-flow (no record emitted → renderer keeps 0).
"""

from __future__ import annotations

import csv
import math
import os
from collections import defaultdict
from dataclasses import dataclass, field

from ..simulation.congestion import congestion_multiplier

# Repo-root data dir (../../../data relative to this file).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_DATA_RAW = os.path.join(_REPO_ROOT, "data", "raw")
# Prefer the extended CKAN dump (more locations/years); fall back to the committed one.
_TMC_CANDIDATES = (
    "262469c2-abfe-4756-9068-4ea5c7ba1af7.csv",
    "tmc_raw_data_2020_2029.csv",
)

_APPROACHES = ("n_appr", "s_appr", "e_appr", "w_appr")
_VEH_KINDS = ("cars", "truck", "bus")
_BINS_PER_HOUR = 4  # TMC rows are 15-minute intervals.
_SNAP_MAX_M = 300.0  # drop survey points farther than this from any graph node.


def default_tmc_path() -> str | None:
    """Path to the richest available raw TMC CSV, or ``None`` if absent."""
    for name in _TMC_CANDIDATES:
        p = os.path.join(_DATA_RAW, name)
        if os.path.exists(p):
            return p
    return None


def _approach_columns(fieldnames) -> dict[str, list[str]]:
    """{approach_prefix -> vehicle count columns} from a TMC header (excl peds/bike)."""
    cols: dict[str, list[str]] = {}
    for ap in _APPROACHES:
        cols[ap] = [
            c
            for c in fieldnames
            if c.startswith(ap) and any(k in c for k in _VEH_KINDS)
        ]
    return cols


def _classify_side(dlat: float, dlon: float) -> str:
    """Which approach an upstream neighbour represents, by its offset from the node.

    A neighbour to the *north* of the intersection feeds the ``n_appr`` (vehicles
    arriving from the north). North/south dominate when |dlat| ≥ |dlon|.
    """
    if abs(dlat) >= abs(dlon):
        return "n_appr" if dlat > 0 else "s_appr"
    return "e_appr" if dlon > 0 else "w_appr"


@dataclass
class BaselineModel:
    """Prebuilt measured-baseline index over a graph; cheap per-hour lookups."""

    # (count_id, dow, hour) -> {approach: mean hourly inbound volume}
    vol: dict = field(default_factory=dict)
    # count_id -> nearest graph node id (only those within _SNAP_MAX_M)
    snapped: dict = field(default_factory=dict)
    # node id -> [(edge_idx, approach_side)]
    inedges: dict = field(default_factory=dict)
    # edge_idx -> (capacity, base_time_min, speed_kmh)
    edge_meta: dict = field(default_factory=dict)
    n_locations: int = 0
    n_matched: int = 0
    source: str = ""

    # ---- per-hour record construction ---------------------------------- #
    def records_for_hour(self, month: int, dow: int, hour: int) -> list:
        """Record5 tuples ``(idx, load, speed, pressure, closure)`` for measured edges."""
        loads: dict[int, float] = defaultdict(float)
        for cid, node in self.snapped.items():
            vols = self.vol.get((cid, month, dow, hour))
            if not vols:
                continue
            for idx, side in self.inedges.get(node, ()):
                v = vols.get(side, 0.0)
                if v > 0.0:
                    loads[idx] += v

        records = []
        for idx, load in loads.items():
            cap, base, spd = self.edge_meta.get(idx, (0.0, 0.0, 0.0))
            pressure = (load / cap) if cap > 0 else 0.0
            mult = congestion_multiplier(pressure)  # finite: open edges only
            cur = base * mult if base else 0.0
            eff_speed = spd * (base / cur) if (cur and base) else spd
            records.append((idx, float(load), float(eff_speed), float(pressure), 0))
        return records

    def day(self, month: int, dow: int) -> list:
        """24 record-lists (one per hour) for the given month + day_of_week."""
        return [self.records_for_hour(month, dow, h) for h in range(24)]


# ---- build steps -------------------------------------------------------- #
def aggregate_tmc(path: str) -> dict:
    """Mean hourly inbound volume per (count_id, month, dow, hour, approach) + coords.

    Returns ``{"vol": {...}, "coord": {count_id: (lat, lon)}}``. Keyed on month too
    so the month selector shows that month's actual surveys (honest, no fallback —
    months sample different intersections, so coverage varies by month).
    """
    sums: dict = defaultdict(lambda: defaultdict(float))  # (cid,month,dow,hour) -> approach -> sum
    counts: dict = defaultdict(int)  # (cid,month,dow,hour) -> n rows
    coord: dict = {}

    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        appr_cols = _approach_columns(reader.fieldnames or [])
        for row in reader:
            cid = row.get("count_id")
            date = row.get("count_date")
            start = row.get("start_time")
            if not cid or not date or not start or len(start) < 13:
                continue
            try:
                y, m, d = (int(x) for x in date.split("-"))
                dow = _civil_dow(y, m, d)
                hour = int(start[11:13])
            except (ValueError, TypeError):
                continue
            key = (cid, m, dow, hour)
            ap_sum = sums[key]
            for ap, cols in appr_cols.items():
                tot = 0.0
                for c in cols:
                    try:
                        tot += float(row[c] or 0)
                    except (TypeError, ValueError, KeyError):
                        pass
                ap_sum[ap] += tot
            counts[key] += 1
            if cid not in coord:
                try:
                    coord[cid] = (float(row["latitude"]), float(row["longitude"]))
                except (TypeError, ValueError, KeyError):
                    pass

    vol: dict = {}
    for key, ap_sum in sums.items():
        n = counts[key]
        if n <= 0:
            continue
        vol[key] = {ap: (s / n) * _BINS_PER_HOUR for ap, s in ap_sum.items() if s > 0}
    return {"vol": vol, "coord": coord}


def _civil_dow(y: int, m: int, d: int) -> int:
    """Day-of-week with Monday=0 (matches the backend's convention), no datetime import."""
    # Sakamoto's algorithm → 0=Sunday..6=Saturday, then shift to Monday=0.
    t = (0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4)
    yy = y - (1 if m < 3 else 0)
    sun0 = (yy + yy // 4 - yy // 100 + yy // 400 + t[m - 1] + d) % 7
    return (sun0 + 6) % 7


def _snap_locations(coord: dict, graph, *, max_m: float = _SNAP_MAX_M) -> dict:
    """count_id -> nearest graph node id within ``max_m`` (local equirectangular)."""
    from scipy.spatial import cKDTree

    node_ids = []
    pts = []
    lat0 = 43.7  # Toronto; only used to scale longitude into metres.
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0
    for nid, data in graph.nodes(data=True):
        lat, lon = data.get("lat"), data.get("lon")
        if lat is None or lon is None:
            continue
        node_ids.append(nid)
        pts.append((lon * kx, lat * ky))
    if not pts:
        return {}
    tree = cKDTree(pts)

    snapped: dict = {}
    for cid, (lat, lon) in coord.items():
        dist, i = tree.query((lon * kx, lat * ky))
        if dist <= max_m:
            snapped[cid] = node_ids[i]
    return snapped


def _node_inedges(graph, edge_index: dict) -> dict:
    """node id -> [(edge_idx, approach_side)] for every in-edge, sided by neighbour offset."""
    coords = {nid: (d.get("lat"), d.get("lon")) for nid, d in graph.nodes(data=True)}
    inedges: dict = defaultdict(list)
    for u, v, data in graph.edges(data=True):
        idx = edge_index.get(data.get("edge_id"))
        if idx is None:
            continue
        ulat, ulon = coords.get(u, (None, None))
        vlat, vlon = coords.get(v, (None, None))
        if None in (ulat, ulon, vlat, vlon):
            continue
        side = _classify_side(ulat - vlat, ulon - vlon)
        inedges[v].append((idx, side))
    return inedges


def _edge_meta(graph, edge_index: dict) -> dict:
    """edge_idx -> (capacity, base_time_min, speed_kmh)."""
    meta: dict = {}
    for _u, _v, d in graph.edges(data=True):
        idx = edge_index.get(d.get("edge_id"))
        if idx is None:
            continue
        meta[idx] = (
            float(d.get("capacity") or 0.0),
            float(d.get("base_time_min") or 0.0),
            float(d.get("speed_kmh") or 0.0),
        )
    return meta


def build_baseline_model(graph, edge_index: dict, *, tmc_path: str | None = None) -> BaselineModel:
    """Aggregate the TMC dataset and bind it to ``graph`` (called once at startup)."""
    path = tmc_path or default_tmc_path()
    if not path:
        return BaselineModel(source="(no TMC file found)")
    agg = aggregate_tmc(path)
    snapped = _snap_locations(agg["coord"], graph)
    return BaselineModel(
        vol=agg["vol"],
        snapped=snapped,
        inedges=_node_inedges(graph, edge_index),
        edge_meta=_edge_meta(graph, edge_index),
        n_locations=len(agg["coord"]),
        n_matched=len(snapped),
        source=os.path.basename(path),
    )
