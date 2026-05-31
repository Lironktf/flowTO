"""P13 Stage-2 bridge — real-closure residuals on a grounded OD.

For each real Toronto closure (a group of P14 factory rows sharing a restriction
``ID``) we **close the graph edge nearest the restriction**, run the deterministic
Frank-Wolfe sim **open** vs **closed** on a *grounded* OD, and emit the real residual
at every nearby TMC site that has an in-window count:

  * ``sim_open`` — equilibrium flow with the road open (the counterfactual "before")
  * ``sim_int``  — equilibrium flow with the closure applied
  * ``r_sim``    = sim_int − sim_open   (the sim's own predicted residual)
  * ``r_obs``    = observed − sim_open   (the **real** residual — the Stage-2 target)

``r_obs`` is only meaningful when ``sim_open`` is on the same scale as the observed
counts, which is why the caller must pass a **counts-grounded** OD (``ipf_counts``);
without it ``r_obs`` is dominated by sim error, not the closure.

The factory row's ``centreline_id`` is the **observation site**, not the closed road
— the two are distinct. We geocode the closed edge from the restriction's
``closure_lat/closure_lon`` (``routing.get_nearest_edge``). TMC counts are keyed by an
**intersection** centreline id while graph edges carry **segment** centreline ids, so a
pure centreline join matches only ~3% of sites; we therefore snap each observed count
to a graph edge **geometrically** — the exact centreline edge when one exists, else the
edge nearest the site coordinates (``representative_edge``). A row with no in-window
count (``during_vol_mean`` NaN) yields **no** residual (no fabrication).

The sim is dependency-injected (``simulate_open`` / ``simulate_intervened``) exactly
as in ``groundtruth.counterfactual`` — the residual math reuses
``counterfactual.compute_residuals`` and the mapping logic below is torch/sim-free,
so it unit-tests without the simulation stack. See ``docs/specs/13-feedback-loop.md``
§A and ``docs/specs/14-closure-dataset.md`` Phase 6.

Consumed factory-row schema (one row per restriction × nearby TMC site):
  ``ID`` · ``centreline_id`` (observation site) · ``during_vol_mean`` (observed,
  in-window) · ``closure_lat`` · ``closure_lon`` (restriction location) ·
  ``site_lat`` · ``site_lon`` (TMC site) · ``StartTime`` · ``split`` ·
  ``has_baseline`` (optional, carried through for reporting).
"""

from __future__ import annotations

from typing import Callable, Mapping, Optional

import pandas as pd

from torontosim.graph.routing import get_nearest_edge

from .groundtruth.spatial import haversine_m

REQUIRED_COLS = [
    "ID",
    "centreline_id",
    "during_vol_mean",
    "closure_lat",
    "closure_lon",
    "site_lat",
    "site_lon",
]


def _temporal_split(rows: pd.DataFrame, test_frac: float) -> pd.DataFrame:
    """Hold out the **latest** ``test_frac`` of restrictions (by ``StartTime``).

    Splits whole closures (every row of a restriction shares one fold) so a Stage-2
    *scenario* never straddles the gate, and mimics deployment — train on earlier
    closures, test on later ones. Deterministic; no RNG.
    """
    start = pd.to_datetime(rows["StartTime"], errors="coerce", utc=True)
    first_seen = rows.assign(_start=start).groupby("ID")["_start"].min().sort_values()
    ids = list(first_seen.index)
    n_test = max(1, int(round(test_frac * len(ids))))
    test_ids = set(ids[-n_test:])  # latest-starting restrictions
    out = rows.copy()
    out["split"] = out["ID"].isin(test_ids).map({True: "test", False: "train"})
    return out


def assemble_factory_rows(
    closures: pd.DataFrame,
    pairs: pd.DataFrame,
    *,
    split: str = "temporal",
    group_col: str = "centreline_id",
    test_frac: float = 0.2,
    seed: int = 42,
):
    """Join P14 phase outputs into the row schema ``build_real_residuals`` consumes.

    ``closures`` = ``groundtruth.labels.build_labels`` output (carries ``ID``,
    ``centreline_id``, ``during_vol_mean``, ``has_baseline``); ``pairs`` =
    ``groundtruth.spatial.spatial_join`` output (carries the restriction location as
    ``closure_lat/closure_lon``, the site as ``site_lat/site_lon``, and ``StartTime``).
    Merges on ``(ID, centreline_id)`` and adds a held-out ``split``:
    ``"temporal"`` (default) holds out the latest closures — the deployment-mimicking
    test, and the only split that partitions whole closures cleanly; ``"centreline"``
    falls back to the per-site grouped split. Returns ``REQUIRED_COLS`` + ``StartTime``
    + ``split`` (+ ``has_baseline`` when present).
    """
    coord_cols = [
        "ID",
        "centreline_id",
        "closure_lat",
        "closure_lon",
        "site_lat",
        "site_lon",
        "StartTime",
    ]
    have = [c for c in coord_cols if c in pairs.columns]
    coords = pairs[have].drop_duplicates(["ID", "centreline_id"])

    keep = ["ID", "centreline_id", "during_vol_mean"]
    if "has_baseline" in closures.columns:
        keep.append("has_baseline")
    rows = closures[keep].merge(coords, on=["ID", "centreline_id"], how="inner")
    if rows.empty:
        rows["split"] = pd.Series(dtype="object")
        return rows
    if split == "temporal":
        return _temporal_split(rows, test_frac)
    from .groundtruth.package import grouped_split

    return grouped_split(rows, group_col=group_col, test_frac=test_frac, seed=seed)


def _edge_id(u, v, k, d) -> str:
    """The edge key the sim's flow dict uses (mirrors ``counterfactual._flows``)."""
    return str(d.get("edge_id") or f"{u}-{v}-{k}")


def _node_coord(data: dict):
    lat = data.get("y", data.get("lat"))
    lon = data.get("x", data.get("lon"))
    if lat is None or lon is None:
        return None, None
    return float(lat), float(lon)


def _edge_midpoint(graph, u, v, d):
    """Representative (lat, lon) for an edge — geometry midpoint, else node mean."""
    geom = d.get("geometry")
    if isinstance(geom, list) and len(geom) >= 1:
        mid = geom[len(geom) // 2]
        return float(mid[0]), float(mid[1])
    ulat, ulon = _node_coord(graph.nodes[u])
    vlat, vlon = _node_coord(graph.nodes[v])
    if None in (ulat, ulon, vlat, vlon):
        return None, None
    return (ulat + vlat) / 2.0, (ulon + vlon) / 2.0


def centreline_edge_index(graph) -> dict:
    """Map ``centreline_id -> [(edge_id, mid_lat, mid_lon)]`` for site snapping.

    A centreline can back several parallel/segment edges; we keep them all and let
    ``_representative_edge`` pick the one closest to the surveyed site.
    """
    idx: dict = {}
    for u, v, k, d in graph.edges(keys=True, data=True):
        cid = d.get("centreline_id")
        if cid is None:
            continue
        lat, lon = _edge_midpoint(graph, u, v, d)
        idx.setdefault(cid, []).append((_edge_id(u, v, k, d), lat, lon))
    return idx


def representative_edge(graph, cid, site_lat, site_lon, cl_index: dict):
    """Snap a TMC observation site to a graph edge, returning ``(edge_id, how)``.

    TMC turning-movement counts are keyed by an **intersection** centreline id, while
    graph edges carry **segment** centreline ids — the two rarely coincide (≈128 of
    ~4000 sites). So:
      1. ``"exact"`` — if the site centreline backs graph edges, take the one nearest
         the site (highest fidelity);
      2. ``"nearest"`` — else snap to the graph edge geometrically nearest the site
         coordinates (the honest proxy: the intersection's count lands on its adjacent
         segment);
      3. ``(None, "unmapped")`` — no centreline match and no usable coordinates.
    """
    cands = cl_index.get(cid)
    if cands:
        usable = [c for c in cands if c[1] is not None]
        if usable and site_lat is not None and not pd.isna(site_lat):
            best = min(usable, key=lambda c: float(haversine_m(site_lat, site_lon, c[1], c[2])))
            return best[0], "exact"
        return cands[0][0], "exact"
    if site_lat is not None and not pd.isna(site_lat):
        try:
            return get_nearest_edge(graph, float(site_lat), float(site_lon)), "nearest"
        except ValueError:
            return None, "unmapped"
    return None, "unmapped"


def closed_ops_for(graph, closure_lat, closure_lon) -> Optional[list]:
    """``close_edge`` ops for the graph edge nearest the restriction (or None)."""
    if closure_lat is None or pd.isna(closure_lat):
        return None
    try:
        eid = get_nearest_edge(graph, float(closure_lat), float(closure_lon))
    except ValueError:
        return None
    return [{"op": "close_edge", "edge_id": eid}]


def build_interventions_and_observed(graph, factory_rows: pd.DataFrame):
    """Map factory rows → (interventions, observed, meta, coverage).

    Torch/sim-free. ``interventions`` = ``[{"ID", "ops", "closed_edge"}]`` for the
    ``compute_residuals`` contract; ``observed`` = ``{(ID, edge_id): during_vol_mean}``;
    ``meta`` = ``{(ID, edge_id): {centreline_id, StartTime, split, has_baseline,
    observed}}`` for re-attaching context; ``coverage`` = honest mapping counts.
    Only restrictions with at least one mapped observation get an intervention, so
    no wasted CLOSED solve is scheduled for a restriction we can't score.
    """
    missing = [c for c in REQUIRED_COLS if c not in factory_rows.columns]
    if missing:
        raise KeyError(f"factory_rows missing required columns: {missing}")

    cl_index = centreline_edge_index(graph)

    # closed edge per restriction (one geocode per ID)
    closed_edge: dict = {}
    for iv_id, grp in factory_rows.groupby("ID"):
        first = grp.iloc[0]
        ops = closed_ops_for(graph, first["closure_lat"], first["closure_lon"])
        if ops is not None:
            closed_edge[iv_id] = ops[0]["edge_id"]

    observed: dict = {}
    meta: dict = {}
    n_rows = len(factory_rows)
    n_with_count = 0
    n_exact = 0
    n_nearest = 0
    n_site_unmapped = 0
    for _, r in factory_rows.iterrows():
        obs = r["during_vol_mean"]
        if pd.isna(obs):
            continue  # no in-window survey → no fabricated residual
        n_with_count += 1
        iv_id = r["ID"]
        if iv_id not in closed_edge:
            continue  # restriction we couldn't geocode → skip
        site_edge, how = representative_edge(
            graph, r["centreline_id"], r.get("site_lat"), r.get("site_lon"), cl_index
        )
        if site_edge is None:
            n_site_unmapped += 1
            continue
        key = (iv_id, site_edge)
        if key in observed:
            continue  # two sites snapped to one edge → keep first
        n_exact += how == "exact"
        n_nearest += how == "nearest"
        observed[key] = float(obs)
        meta[key] = {
            "centreline_id": r["centreline_id"],
            "snap": how,
            "StartTime": r.get("StartTime"),
            "split": r.get("split"),
            "has_baseline": r.get("has_baseline"),
            "observed": float(obs),
        }

    active_ids = {iv_id for (iv_id, _e) in observed}
    interventions = [
        {"ID": iv_id, "ops": [{"op": "close_edge", "edge_id": eid}], "closed_edge": eid}
        for iv_id, eid in closed_edge.items()
        if iv_id in active_ids
    ]
    coverage = {
        "n_factory_rows": int(n_rows),
        "n_restrictions": int(factory_rows["ID"].nunique()),
        "n_restrictions_geocoded": int(len(closed_edge)),
        "n_rows_with_count": int(n_with_count),
        "n_observed_mapped": int(len(observed)),
        "n_mapped_exact": int(n_exact),  # site centreline backs a graph edge
        "n_mapped_nearest": int(n_nearest),  # snapped to nearest edge by site coords
        "n_site_unmapped": int(n_site_unmapped),
        "n_active_restrictions": int(len(active_ids)),
        "n_centrelines_in_graph": int(len(cl_index)),
    }
    return interventions, observed, meta, coverage


def build_real_residuals(
    graph,
    factory_rows: pd.DataFrame,
    od_matrix,
    *,
    simulate_open: Optional[Callable[[], Mapping[str, float]]] = None,
    simulate_intervened: Optional[Callable[[list], Mapping[str, float]]] = None,
    solver: str = "full",
    backend: str = "scipy",
    max_iter: int = 100,
    rgap: float = 1e-4,
):
    """Real-closure residual rows + a coverage report.

    Reuses ``counterfactual.compute_residuals`` for the residual math. The sim
    adapter is chosen by ``solver``: ``"full"`` re-solves the whole equilibrium
    open/closed (``counterfactual.simulate_open_intervened`` — verified, slow);
    ``"blast"`` re-routes only the affected bundles over a shared path cache
    (``blast_sim.simulate_open_intervened_blast`` — ~5–10× faster, AON fidelity,
    see ``docs/specs/15-feedback-loop-perf.md``). Pass ``simulate_open``/
    ``simulate_intervened`` to inject the sim in tests. Returns
    ``(residuals_df, coverage, sim_open_full)`` where ``residuals_df``
    carries ``[ID, centreline_id, edge_id, closed_edge, sim_open, sim_int, r_sim,
    r_obs, observed, StartTime, split, has_baseline]`` and ``sim_open_full`` is the
    single global open-road solve ``{edge_id: load}`` (shared by every closure — OD
    and open topology are fixed) used to fill the Stage-2 ``sim_open`` channels.
    """
    from .groundtruth.counterfactual import compute_residuals

    interventions, observed, meta, coverage = build_interventions_and_observed(graph, factory_rows)
    coverage["solver"] = solver

    if not interventions:
        cols = [
            "ID",
            "centreline_id",
            "edge_id",
            "closed_edge",
            "sim_open",
            "sim_int",
            "r_sim",
            "r_obs",
            "observed",
            "StartTime",
            "split",
            "has_baseline",
        ]
        return pd.DataFrame(columns=cols), coverage, {}

    if simulate_open is None or simulate_intervened is None:
        if solver == "blast":
            from .blast_sim import simulate_open_intervened_blast

            simulate_open, simulate_intervened = simulate_open_intervened_blast(
                graph, od_matrix, backend=backend
            )
        else:
            from .groundtruth.counterfactual import simulate_open_intervened

            simulate_open, simulate_intervened = simulate_open_intervened(
                graph, od_matrix, backend=backend, max_iter=max_iter, rgap=rgap
            )

    sim_open_full = dict(simulate_open())  # the one global open solve

    # The model trains on r_obs = observed − sim_open (the OPEN solve only); the CLOSED
    # solve (sim_int) is needed solely for r_sim, which the gate reads only for held-out
    # (test) closures. So run the expensive closed solve ONLY for test closures — train
    # closures get sim_int = sim_open (r_sim = 0, unused). Model + gate verdict unchanged;
    # ~80% fewer equilibrium solves. See docs/specs/15-feedback-loop-perf.md.
    test_ids = {iv_id for (iv_id, _e), m in meta.items() if m.get("split") == "test"}
    test_closed_edges = {iv["closed_edge"] for iv in interventions if iv["ID"] in test_ids}
    _real_intervened = simulate_intervened

    def _gated_intervened(ops):
        eid = ops[0].get("edge_id") if ops else None
        if eid in test_closed_edges:
            return _real_intervened(ops)  # held-out closure → real closed solve for r_sim
        return sim_open_full  # train closure → skip (r_sim unused)

    coverage["n_closed_solves"] = int(len(test_closed_edges))
    res = compute_residuals(interventions, observed, simulate_open, _gated_intervened)

    closed_by_id = {iv["ID"]: iv["closed_edge"] for iv in interventions}
    res["closed_edge"] = res["ID"].map(closed_by_id)
    for col in ("centreline_id", "StartTime", "split", "has_baseline", "observed"):
        res[col] = [meta.get((row.ID, row.edge_id), {}).get(col) for row in res.itertuples()]

    coverage["n_residual_rows"] = int(len(res))
    return res, coverage, sim_open_full
