"""
Turn per-node demand into an origin -> destination trip matrix.

The demand model says "how many cars want to move near node X". A gravity model
turns that into actual trips between node pairs:

    OD(i, j) = origin_strength(i) * destination_strength(j) / (1 + distance_km)

with time-of-day biasing:
  * morning   : outer/residential nodes -> downtown   (the commute in)
  * evening   : downtown -> outer/residential nodes    (the commute out)
  * weekend pm: extra destination pull toward downtown/entertainment-ish nodes

    generate_od_matrix(graph, node_demands, time_context, max_pairs=1000)
      -> [ {"origin": node_id, "destination": node_id, "trips": float}, ... ]

The goal is a *plausible* set of trips to route, not a calibrated travel-demand
survey. The simulator can additionally scale total trips to hit a target
congestion level (see simulate_traffic.auto_calibrate).
"""

from __future__ import annotations

import math
from typing import Dict, List

from ..graph.config import haversine_m
from .features import compute_static_node_features, normalize_time_context

# Candidate-set sizes: we only consider the top-N strongest origins and
# destinations to keep the pair enumeration O(N^2) instead of O(nodes^2).
TOP_ORIGINS = 500
TOP_DESTS = 500

# Geographic sanity bounds on a trip (km). Skip pairs outside this range.
MIN_TRIP_KM = 0.4
MAX_TRIP_KM = 25.0

# Nominal total trips before the simulator's optional auto-calibration.
NOMINAL_TOTAL_TRIPS = 100_000.0


def _downtown_pull(dist_km: float) -> float:
    """0..1-ish weight that's high downtown and decays outward."""
    return math.exp(-dist_km / 5.0)


def _outer_pull(dist_km: float) -> float:
    """Complement of downtown pull: high in the outskirts."""
    return 1.0 - math.exp(-dist_km / 8.0)


# Trips should enter/leave the network on real roads, not residential stubs.
# Endpoints on bigger roads (higher rank) get more OD strength; pure-local
# rank-1 nodes are still allowed but weighted down so congestion concentrates
# on arterials rather than tiny side streets (a last-mile funnel artifact).
_RANK_ENDPOINT_FACTOR = {6: 1.6, 5: 1.5, 4: 1.4, 3: 1.25, 2: 1.1, 1: 0.5}


def _strengths(node_demands, static, tc):
    """Compute per-node origin and destination strengths for this time context.

    Both start from predicted demand, then get nudged by time of day so trips
    flow the way real commutes do, and by road class so trips concentrate on
    arterials.
    """
    hour = tc["hour"]
    is_weekend = tc["is_weekend"]
    morning = (6 <= hour <= 10) and not is_weekend
    evening = (16 <= hour <= 19) and not is_weekend
    weekend_pm = is_weekend and (17 <= hour <= 23)

    origin_strength: Dict[object, float] = {}
    dest_strength: Dict[object, float] = {}
    for node, demand in node_demands.items():
        sf = static.get(node)
        if sf is None or demand <= 0:
            continue
        dist = sf["distance_to_downtown"]
        rank_factor = _RANK_ENDPOINT_FACTOR.get(sf["road_class_rank"], 0.5)
        o = demand * rank_factor
        d = demand * rank_factor
        if morning:
            o *= 0.5 + _outer_pull(dist)  # commuters start outside
            d *= 0.5 + 2.0 * _downtown_pull(dist)  # heading downtown
        elif evening:
            o *= 0.5 + 2.0 * _downtown_pull(dist)  # leaving downtown
            d *= 0.5 + _outer_pull(dist)  # heading home
        elif weekend_pm:
            d *= 0.6 + 1.5 * _downtown_pull(dist)  # nightlife/venues pull
        origin_strength[node] = o
        dest_strength[node] = d
    return origin_strength, dest_strength


def generate_od_matrix(
    graph,
    node_demands: Dict[object, float],
    time_context: dict,
    max_pairs: int = 1000,
    nominal_total: float = NOMINAL_TOTAL_TRIPS,
    calibration: str = "none",
) -> List[dict]:
    """Build the OD trip list. See module docstring for the model.

    ``calibration`` (P03): ``none`` keeps the demo-safe gravity baseline
    (default — per GOAL's "prefer the safe column"); ``ipf``/``ipf_counts``
    additionally balance the gravity matrix to production/attraction marginals
    derived from the node-demand strengths (Furness Stage 1). Full ODME against
    TMC counts (``ipf_counts`` with observed link flows) is applied downstream
    in the assignment loop where an assignment is available.
    """
    tc = normalize_time_context(time_context)
    static = compute_static_node_features(graph)

    origin_strength, dest_strength = _strengths(node_demands, static, tc)
    if not origin_strength or not dest_strength:
        return []

    origins = sorted(origin_strength, key=lambda n: -origin_strength[n])[:TOP_ORIGINS]
    dests = sorted(dest_strength, key=lambda n: -dest_strength[n])[:TOP_DESTS]

    pairs = []
    for i in origins:
        oi = origin_strength[i]
        ilat, ilon = static[i]["lat"], static[i]["lon"]
        for j in dests:
            if i == j:
                continue
            jlat, jlon = static[j]["lat"], static[j]["lon"]
            dist_km = haversine_m(ilat, ilon, jlat, jlon) / 1000.0
            if dist_km < MIN_TRIP_KM or dist_km > MAX_TRIP_KM:
                continue
            val = oi * dest_strength[j] / (1.0 + dist_km)
            if val > 0:
                pairs.append((i, j, val))

    if not pairs:
        return []

    # Keep the strongest max_pairs, then scale so the total is `nominal_total`.
    pairs.sort(key=lambda t: -t[2])
    pairs = pairs[:max_pairs]

    if calibration in ("ipf", "ipf_counts"):
        pairs = _calibrate_ipf(pairs, origin_strength, dest_strength)

    total_val = sum(v for _, _, v in pairs)
    scale = (nominal_total / total_val) if total_val > 0 else 0.0

    return [{"origin": i, "destination": j, "trips": v * scale} for (i, j, v) in pairs]


def _calibrate_ipf(pairs, origin_strength, dest_strength):
    """Sparse Furness: balance pair values to per-origin/per-dest marginals.

    Marginals are the node-demand strengths (productions ~ origin_strength,
    attractions ~ dest_strength), restricted to the nodes present in ``pairs``
    and renormalized to a common total. Deterministic; structural zeros (pairs
    absent from the gravity step) stay absent.
    """
    used_o = sorted({i for i, _, _ in pairs}, key=str)
    used_d = sorted({j for _, j, _ in pairs}, key=str)
    prod = {i: max(0.0, origin_strength.get(i, 0.0)) for i in used_o}
    attr = {j: max(0.0, dest_strength.get(j, 0.0)) for j in used_d}
    p_tot, a_tot = sum(prod.values()), sum(attr.values())
    if p_tot <= 0 or a_tot <= 0:
        return pairs
    # Common total so row/col marginals are consistent for IPF.
    attr = {j: a * (p_tot / a_tot) for j, a in attr.items()}

    vals = {(i, j): v for i, j, v in pairs}
    for _ in range(50):
        # Row (origin) balance.
        row_sum: Dict[object, float] = {}
        for (i, j), v in vals.items():
            row_sum[i] = row_sum.get(i, 0.0) + v
        for i, j in list(vals):
            rs = row_sum.get(i, 0.0)
            if rs > 0:
                vals[(i, j)] *= prod[i] / rs
        # Column (dest) balance.
        col_sum: Dict[object, float] = {}
        for (i, j), v in vals.items():
            col_sum[j] = col_sum.get(j, 0.0) + v
        for i, j in list(vals):
            cs = col_sum.get(j, 0.0)
            if cs > 0:
                vals[(i, j)] *= attr[j] / cs

    return [(i, j, vals[(i, j)]) for (i, j, _) in pairs]
