"""Stage-2 ODME — pragmatic IPF-on-counts (P03).

The OD-matrix-estimation problem (recover OD from observed link counts) is
under-determined. The MVP treats observed **TMC link counts as marginals** and
iteratively scales the seed OD so its assigned link flows approach the counts —
an IPF-style multiplicative update regularized toward the seed. Each OD pair's
correction is the geometric mean of the count/flow ratios on the links it uses
(damped), so it never diverges and stays non-negative. (Full SPSA ODME is a
stretch task.)
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping

ODKey = tuple
PathOf = Callable[[object, object], list]


def assign_to_links(od: Mapping[ODKey, float], path_of: PathOf) -> dict:
    """Assign OD trips onto links (all-or-nothing) -> per-link total flow."""
    links: dict = {}
    for (o, d), trips in od.items():
        for link in path_of(o, d):
            links[link] = links.get(link, 0.0) + trips
    return links


def total_abs_error(flows: Mapping, observed: Mapping) -> float:
    """Sum of |assigned - observed| over links present in ``observed``."""
    return sum(abs(flows.get(link, 0.0) - obs) for link, obs in observed.items())


def odme_ipf_counts(
    seed_od: Mapping[ODKey, float],
    observed_counts: Mapping,
    path_of: PathOf,
    *,
    max_iter: int = 100,
    damping: float = 1.0,
    tol: float = 1e-9,
) -> dict:
    """Scale ``seed_od`` so assigned link flows approach ``observed_counts``.

    ``damping`` in (0, 1] regularizes toward the seed (1.0 = full step). Returns
    a new OD dict; deterministic. Monotone non-increasing total abs error in
    practice for consistent counts.
    """
    od = {k: float(v) for k, v in seed_od.items()}
    prev_err = math.inf
    for _ in range(max_iter):
        flows = assign_to_links(od, path_of)
        # Per-link correction ratio observed/assigned.
        ratio = {}
        for link, obs in observed_counts.items():
            f = flows.get(link, 0.0)
            ratio[link] = (obs / f) if f > 0 else 1.0

        new_od = {}
        for (o, d), trips in od.items():
            path = [link for link in path_of(o, d) if link in ratio]
            if not path:
                new_od[(o, d)] = trips
                continue
            # Geometric mean of link ratios -> balanced correction.
            log_sum = sum(math.log(ratio[link]) for link in path)
            corr = math.exp(log_sum / len(path))
            corr = corr**damping
            new_od[(o, d)] = max(0.0, trips * corr)
        od = new_od

        err = total_abs_error(assign_to_links(od, path_of), observed_counts)
        if abs(prev_err - err) < tol:
            break
        prev_err = err
    return od
