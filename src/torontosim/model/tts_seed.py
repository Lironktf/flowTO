"""Survey/Census seed for the OD prior (P03).

TTS2016R (open, CC-BY) zone OD is the preferred prior; when unavailable we fall
back to a fully-open **Census-population × Employment gravity** prior. Either
way the zone-level prior is exploded to graph nodes using Liron's ML
node-demand as within-zone weights. All functions are pure + deterministic so
the seed is reproducible for validation against past events.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from ..graph.config import haversine_m


def node_to_zone(node_xy: Mapping, zone_centroids: Mapping) -> dict:
    """Assign each node to its nearest zone centroid (proxy for point-in-poly).

    ``node_xy``: ``{node: (lon, lat)}``; ``zone_centroids``: ``{zone: (lon, lat)}``.
    Deterministic (ties broken by sorted zone id).
    """
    zones = sorted(zone_centroids, key=str)
    mapping: dict = {}
    for node, (nlon, nlat) in node_xy.items():
        best, best_d = None, math.inf
        for z in zones:
            zlon, zlat = zone_centroids[z]
            d = haversine_m(nlat, nlon, zlat, zlon)
            if d < best_d:
                best, best_d = z, d
        mapping[node] = best
    return mapping


def census_employment_gravity_prior(
    zone_pop: Mapping,
    zone_emp: Mapping,
    zone_centroids: Mapping,
    *,
    beta: float = 0.1,
    min_km: float = 0.3,
) -> dict:
    """Gravity OD prior at zone level: ``P_i * E_j * exp(-beta * d_ij)``.

    ``zone_pop`` (productions) and ``zone_emp`` (attractions) are open Census /
    Employment-Survey aggregates. Returns ``{(i, j): trips_prior}`` (i != j).
    """
    zones = sorted(set(zone_pop) & set(zone_emp) & set(zone_centroids), key=str)
    od: dict = {}
    for i in zones:
        ilon, ilat = zone_centroids[i]
        for j in zones:
            if i == j:
                continue
            jlon, jlat = zone_centroids[j]
            dist_km = max(min_km, haversine_m(ilat, ilon, jlat, jlon) / 1000.0)
            val = zone_pop[i] * zone_emp[j] * math.exp(-beta * dist_km)
            if val > 0:
                od[(i, j)] = val
    return od


def explode_to_nodes(
    zone_od: Mapping,
    node_zone: Mapping,
    node_weights: Mapping,
) -> dict:
    """Distribute a zone-level OD to node pairs using node-demand weights.

    ``node_zone``: ``{node: zone}``; ``node_weights``: ``{node: demand}`` (the ML
    node-demand acts as the within-zone share). Returns ``{(o_node, d_node):
    trips}``. Deterministic.
    """
    # Per-zone node lists + weight totals.
    by_zone: dict = {}
    for node, zone in node_zone.items():
        by_zone.setdefault(zone, []).append(node)

    def _shares(zone):
        nodes = by_zone.get(zone, [])
        total = sum(max(0.0, node_weights.get(n, 0.0)) for n in nodes)
        if total <= 0:
            # Uniform if no demand signal.
            return {n: 1.0 / len(nodes) for n in nodes} if nodes else {}
        return {n: max(0.0, node_weights.get(n, 0.0)) / total for n in nodes}

    out: dict = {}
    for (zi, zj), trips in zone_od.items():
        oi, oj = _shares(zi), _shares(zj)
        for on, ow in oi.items():
            for dn, dw in oj.items():
                if on == dn:
                    continue
                val = trips * ow * dw
                if val > 0:
                    out[(on, dn)] = out.get((on, dn), 0.0) + val
    return out
