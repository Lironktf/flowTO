"""Torch/sim-free tests for the Stage-2 real-residual bridge.

Covers the mapping logic (geocode restriction → closed edge, snap observed counts to
the site's centreline edge, no fabrication for missing counts) and the residual math
via injected sim callbacks. No torch, no equilibrium solve.
"""

from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from torontosim.feedback.real_residuals import (
    assemble_factory_rows,
    build_interventions_and_observed,
    build_real_residuals,
    centreline_edge_index,
    closed_ops_for,
    representative_edge,
)


def _line_graph() -> nx.MultiDiGraph:
    """A->B->C->D along a meridian; edge i carries centreline_id 100*i, edge_id e{i}."""
    g = nx.MultiDiGraph()
    coords = {
        "A": (43.650, -79.380),
        "B": (43.651, -79.380),
        "C": (43.652, -79.380),
        "D": (43.653, -79.380),
    }
    for n, (lat, lon) in coords.items():
        g.add_node(n, y=lat, x=lon)
    spans = [("A", "B", "e1", 100), ("B", "C", "e2", 200), ("C", "D", "e3", 300)]
    for u, v, eid, cid in spans:
        (ulat, ulon), (vlat, vlon) = coords[u], coords[v]
        g.add_edge(
            u,
            v,
            key=0,
            edge_id=eid,
            centreline_id=cid,
            geometry=[[ulat, ulon], [vlat, vlon]],
        )
    return g


def _midpoint(g, eid):
    for u, v, d in g.edges(data=True):
        if d["edge_id"] == eid:
            return (g.nodes[u]["y"] + g.nodes[v]["y"]) / 2, g.nodes[u]["x"]
    raise KeyError(eid)


def _rows(g) -> pd.DataFrame:
    e1 = _midpoint(g, "e1")  # restriction R1 sits here
    e2 = _midpoint(g, "e2")  # the surveyed site (centreline 200)
    e3 = _midpoint(g, "e3")  # restriction R2 sits here
    return pd.DataFrame(
        [
            # R1: observed at centreline 200 (→ e2)
            dict(
                ID="R1",
                centreline_id=200,
                during_vol_mean=120.0,
                closure_lat=e1[0],
                closure_lon=e1[1],
                site_lat=e2[0],
                site_lon=e2[1],
                StartTime="2023-01-01",
                split="train",
                has_baseline=1,
            ),
            # R1: no in-window count → must yield NO residual row
            dict(
                ID="R1",
                centreline_id=300,
                during_vol_mean=np.nan,
                closure_lat=e1[0],
                closure_lon=e1[1],
                site_lat=e3[0],
                site_lon=e3[1],
                StartTime="2023-01-01",
                split="train",
                has_baseline=0,
            ),
            # R1: site centreline NOT in graph → geometric fallback to nearest edge (e3)
            dict(
                ID="R1",
                centreline_id=999,
                during_vol_mean=30.0,
                closure_lat=e1[0],
                closure_lon=e1[1],
                site_lat=e3[0],
                site_lon=e3[1],
                StartTime="2023-01-01",
                split="train",
                has_baseline=0,
            ),
            # R2: closed near e3, observed at centreline 200 (→ e2)
            dict(
                ID="R2",
                centreline_id=200,
                during_vol_mean=80.0,
                closure_lat=e3[0],
                closure_lon=e3[1],
                site_lat=e2[0],
                site_lon=e2[1],
                StartTime="2023-06-01",
                split="test",
                has_baseline=1,
            ),
        ]
    )


def test_centreline_index_and_geocode():
    g = _line_graph()
    idx = centreline_edge_index(g)
    assert set(idx) == {100, 200, 300}
    assert idx[200][0][0] == "e2"
    # restriction at e1's midpoint geocodes to e1
    e1 = _midpoint(g, "e1")
    assert closed_ops_for(g, *e1) == [{"op": "close_edge", "edge_id": "e1"}]
    # missing coords → no ops
    assert closed_ops_for(g, np.nan, np.nan) is None


def test_representative_edge_exact_then_nearest():
    g = _line_graph()
    idx = centreline_edge_index(g)
    e2 = _midpoint(g, "e2")
    # exact: a graph-backed centreline returns its edge
    assert representative_edge(g, 200, e2[0], e2[1], idx) == ("e2", "exact")
    # nearest: an intersection-only centreline (not a segment) snaps by coordinates
    e3 = _midpoint(g, "e3")
    assert representative_edge(g, 999, e3[0], e3[1], idx) == ("e3", "nearest")
    # neither centreline nor coords → unmapped
    assert representative_edge(g, 999, np.nan, np.nan, idx) == (None, "unmapped")


def test_interventions_and_observed_mapping():
    g = _line_graph()
    iv, observed, meta, cov = build_interventions_and_observed(g, _rows(g))

    # closed edges geocoded from the restriction location
    closed = {x["ID"]: x["closed_edge"] for x in iv}
    assert closed == {"R1": "e1", "R2": "e3"}

    # observed: exact centreline → e2; the intersection-only 999 snaps to nearest (e3)
    assert observed == {("R1", "e2"): 120.0, ("R1", "e3"): 30.0, ("R2", "e2"): 80.0}

    assert cov["n_observed_mapped"] == 3
    assert cov["n_mapped_exact"] == 2  # R1/R2 centreline 200
    assert cov["n_mapped_nearest"] == 1  # R1 centreline 999 → e3
    assert cov["n_site_unmapped"] == 0
    assert cov["n_rows_with_count"] == 3  # 120, 30, 80 (the NaN excluded)
    assert meta[("R1", "e2")]["split"] == "train"
    assert meta[("R2", "e2")]["centreline_id"] == 200
    assert meta[("R1", "e3")]["snap"] == "nearest"


def test_build_real_residuals_signs_and_no_fabrication():
    g = _line_graph()
    rows = _rows(g)
    sim_open = {"e1": 10.0, "e2": 50.0, "e3": 5.0}
    calls = []

    def fake_open():
        return sim_open

    def fake_intervened(ops):
        calls.append(ops[0]["edge_id"])
        closed = ops[0]["edge_id"]
        out = dict(sim_open)
        out[closed] = 0.0
        if closed == "e1":  # closing e1 reroutes flow onto e2
            out["e2"] = 70.0
        return out

    res, cov, sim_open_full = build_real_residuals(
        g,
        rows,
        od_matrix=None,
        simulate_open=fake_open,
        simulate_intervened=fake_intervened,
    )

    # one CLOSED solve per active restriction — none wasted on unmapped restrictions
    assert sorted(calls) == ["e1", "e3"]
    # the full open solve is surfaced for the Stage-2 sim_open channels
    assert sim_open_full == {"e1": 10.0, "e2": 50.0, "e3": 5.0}

    r1e2 = res[(res["ID"] == "R1") & (res["edge_id"] == "e2")].iloc[0]
    assert r1e2["sim_open"] == 50.0 and r1e2["sim_int"] == 70.0
    assert r1e2["r_sim"] == pytest.approx(20.0)  # 70 - 50
    assert r1e2["r_obs"] == pytest.approx(70.0)  # 120 - 50
    assert r1e2["closed_edge"] == "e1"
    assert r1e2["split"] == "train"

    # R1's nearest-snapped site (e3) is untouched by closing e1 → r_sim 0
    r1e3 = res[(res["ID"] == "R1") & (res["edge_id"] == "e3")].iloc[0]
    assert r1e3["r_sim"] == pytest.approx(0.0)
    assert r1e3["r_obs"] == pytest.approx(25.0)  # 30 - 5

    r2 = res[res["ID"] == "R2"].iloc[0]
    assert r2["r_sim"] == pytest.approx(0.0)  # closing e3 leaves e2 at 50
    assert r2["r_obs"] == pytest.approx(30.0)  # 80 - 50
    assert r2["split"] == "test"

    # three mapped sites — the NaN row never appears
    assert len(res) == 3
    assert cov["n_residual_rows"] == 3


def test_assemble_factory_rows_join_and_split():
    # build_labels-style closures (ID × site centreline)
    closures = pd.DataFrame(
        [
            dict(ID="R1", centreline_id=200, during_vol_mean=120.0, has_baseline=1),
            dict(ID="R2", centreline_id=300, during_vol_mean=80.0, has_baseline=0),
            dict(ID="R3", centreline_id=400, during_vol_mean=55.0, has_baseline=1),
        ]
    )
    # spatial_join-style pairs (carry coords + window, duplicated per survey)
    pairs = pd.DataFrame(
        [
            dict(
                ID="R1",
                centreline_id=200,
                closure_lat=43.65,
                closure_lon=-79.38,
                site_lat=43.651,
                site_lon=-79.38,
                StartTime="2023-01-01",
            ),
            dict(
                ID="R1",
                centreline_id=200,
                closure_lat=43.65,
                closure_lon=-79.38,
                site_lat=43.651,
                site_lon=-79.38,
                StartTime="2023-01-01",
            ),  # dup
            dict(
                ID="R2",
                centreline_id=300,
                closure_lat=43.70,
                closure_lon=-79.40,
                site_lat=43.701,
                site_lon=-79.40,
                StartTime="2023-02-01",
            ),
            dict(
                ID="R3",
                centreline_id=400,
                closure_lat=43.66,
                closure_lon=-79.39,
                site_lat=43.661,
                site_lon=-79.39,
                StartTime="2023-03-01",
            ),
        ]
    )
    rows = assemble_factory_rows(closures, pairs, test_frac=0.34)
    # one row per (ID, centreline_id), coords + window joined, has_baseline carried
    assert len(rows) == 3
    assert set(rows["ID"]) == {"R1", "R2", "R3"}
    assert set(["closure_lat", "site_lat", "StartTime", "split", "has_baseline"]) <= set(
        rows.columns
    )
    # temporal split (default): the LATEST-starting restriction (R3) is held out
    assert set(rows[rows.split == "test"]["ID"]) == {"R3"}
    assert set(rows[rows.split == "train"]["ID"]) == {"R1", "R2"}

    # the per-site centreline split is still available as a fallback
    grouped = assemble_factory_rows(closures, pairs, split="centreline", test_frac=0.34, seed=1)
    train_cl = set(grouped[grouped.split == "train"]["centreline_id"])
    test_cl = set(grouped[grouped.split == "test"]["centreline_id"])
    assert train_cl.isdisjoint(test_cl)


def test_missing_columns_raise():
    g = _line_graph()
    with pytest.raises(KeyError):
        build_interventions_and_observed(g, pd.DataFrame({"ID": ["R1"]}))


def test_empty_when_no_observations():
    g = _line_graph()
    rows = _rows(g)
    rows["during_vol_mean"] = np.nan
    res, cov, sim_open_full = build_real_residuals(
        g,
        rows,
        od_matrix=None,
        simulate_open=lambda: {},
        simulate_intervened=lambda ops: {},
    )
    assert res.empty
    assert cov["n_observed_mapped"] == 0
    assert sim_open_full == {}
