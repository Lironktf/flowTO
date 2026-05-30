"""Light capacity calibration against observed TMC peak counts (P02).

Where an edge's ``centreline_id`` matches a TMC count location, nudge its
``capacity`` toward the observed peak throughput and relabel that field
``observed``. This is intentionally light — full origin-destination matrix
estimation (ODME) is P03/P04. Uncalibrated edges keep their ``default``
confidence (honest about what's measured vs assumed).
"""

from __future__ import annotations

import networkx as nx

# Movement columns that sum to a per-interval vehicle count (research/01 schema).
# We accept any column matching this prefix/suffix shape, summed per record.
_VEH_PREFIXES = ("n_appr", "s_appr", "e_appr", "w_appr")


def _record_vehicles(rec: dict) -> float:
    total = 0.0
    for k, v in rec.items():
        kl = k.lower()
        if kl.startswith(_VEH_PREFIXES) and ("cars" in kl or "truck" in kl or "bus" in kl):
            try:
                total += float(v or 0)
            except (TypeError, ValueError):
                continue
    if total == 0.0 and "veh_15min" in rec:
        try:
            total = float(rec["veh_15min"] or 0)
        except (TypeError, ValueError):
            total = 0.0
    return total


def observed_peak_by_centreline(tmc_records, *, interval_per_hour: int = 4) -> dict:
    """Map ``centreline_id`` -> observed peak hourly vehicle throughput.

    TMC rows are 15-minute intervals; peak hourly ≈ max interval count ×4.
    """
    peak: dict = {}
    for rec in tmc_records:
        cid = rec.get("centreline_id") or rec.get("CENTRELINE_ID")
        if cid is None:
            continue
        veh = _record_vehicles(rec) * interval_per_hour
        if veh > peak.get(cid, 0.0):
            peak[cid] = veh
    return peak


def calibrate(graph: nx.MultiDiGraph, tmc_records, *, min_gain: float = 1.05) -> int:
    """Raise capacity toward observed peaks for matched edges. Returns #adjusted.

    Only *raises* capacity (observed throughput is a lower bound on capacity)
    and only when the observed peak exceeds the modeled capacity by ``min_gain``.
    """
    peak = observed_peak_by_centreline(tmc_records)
    if not peak:
        return 0
    adjusted = 0
    for _u, _v, data in graph.edges(data=True):
        cid = data.get("centreline_id")
        if cid is None or cid not in peak:
            continue
        observed = peak[cid]
        modeled = float(data.get("capacity") or 0.0)
        if observed > modeled * min_gain:
            data["capacity"] = round(observed, 1)
            conf = data.setdefault("confidence", {})
            conf["capacity"] = "observed"
            adjusted += 1
    return adjusted
