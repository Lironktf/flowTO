"""P13 — residual closure-GNN edit-path wiring (torch-free unit tests).

The residual GNN closure path in ``api/recompute.py`` is INERT by default: the
app-local gate ships ``closures.ship=false`` and torch is not installed in CI, so
every edit takes the deterministic sim path. These tests pin that default plus the
gated-on behaviour with a fake injected model (no torch required).

Acceptance:
  (a) gate OFF / artifact missing       → sim path, unchanged
  (b) out-of-scope op (reopen / surge)  → sim path
  (c) gate ship==true + fake model      → residual path → Record5
  (d) determinism                       → identical inputs, identical records
"""

from __future__ import annotations

import json

import networkx as nx
import numpy as np
import pytest

from torontosim.api import recompute as rc
from torontosim.api import residual_edit
from torontosim.api.store import AppState
from torontosim.graph import schema


def _small_state():
    g = nx.MultiDiGraph()
    coords = {0: (-79.40, 43.64), 1: (-79.39, 43.65), 2: (-79.39, 43.63), 3: (-79.38, 43.64)}
    for n, (x, y) in coords.items():
        g.add_node(n, x=x, y=y)
    for i, (u, v) in enumerate([(0, 1), (0, 2), (1, 3), (2, 3)]):
        g.add_edge(
            u,
            v,
            key=0,
            **schema.make_edge(
                edge_id=f"e{i}",
                from_node=u,
                to_node=v,
                road_class="primary",
                length_m=1000.0,
                speed_kmh=50.0,
                lanes=2.0,
                capacity=1200.0,
                base_time_min=1.2,
                one_way=True,
                geometry=[[coords[u][1], coords[u][0]], [coords[v][1], coords[v][0]]],
            ),
        )
    od = [{"origin": 0, "destination": 3, "trips": 1500.0}]
    return AppState.from_graph(g, od, weather="clear", time_context={"hour": 17})


@pytest.fixture(autouse=True)
def _clean_module_cache():
    residual_edit.reset_cache()
    yield
    residual_edit.reset_cache()


# ── (a) gate OFF / artifact missing → sim path, unchanged ──────────────────── #


def test_shipped_gate_is_off_by_default():
    """The shipped app-local verdict must keep closures on the sim."""
    assert residual_edit.gate_ship_closures() is False


def test_should_use_residual_false_when_gate_off():
    state = _small_state()  # noqa: F841 (parallels real call site)
    # Even a pure closure must NOT take the residual path while the gate is off.
    assert residual_edit.should_use_residual([{"op": "close_edge", "edge_id": "e0"}]) is False


def test_gate_off_dispatch_takes_sim_path(monkeypatch):
    """With the gate off, recompute never invokes the residual builder."""
    state = _small_state()
    called = {"sim": 0, "residual": 0}

    def fake_run(*a, **k):
        called["sim"] += 1
        return {"records": [], "summary": {}, "rgap": None, "model_actual": "stub"}

    def fake_residual(*a, **k):
        called["residual"] += 1
        return {"records": [(0, 1.0, 2.0, 3.0, 0)], "summary": {}}

    monkeypatch.setattr(rc, "_run", fake_run)
    monkeypatch.setattr(rc, "_run_residual", fake_residual)

    rc.recompute_scenario(
        state,
        time_context={"hour": 17, "day_of_week": 2, "month": 6},
        interventions=[{"op": "close_edge", "edge_id": "e0"}],
    )
    assert called == {"sim": 1, "residual": 0}


def test_gate_on_but_missing_checkpoint_falls_back(monkeypatch, tmp_path):
    """ship=true but no checkpoint → should_use_residual stays False (sim path)."""
    monkeypatch.setattr(residual_edit, "gate_ship_closures", lambda: True)
    monkeypatch.setattr(residual_edit, "torch_available", lambda: True)
    monkeypatch.setenv("TS_RESIDUAL_CKPT", str(tmp_path / "does_not_exist.pt"))
    assert residual_edit.should_use_residual([{"op": "close_edge", "edge_id": "e0"}]) is False


def test_gate_on_but_no_torch_falls_back(monkeypatch, tmp_path):
    ckpt = tmp_path / "ck.pt"
    ckpt.write_bytes(b"stub")
    monkeypatch.setattr(residual_edit, "gate_ship_closures", lambda: True)
    monkeypatch.setattr(residual_edit, "torch_available", lambda: False)
    monkeypatch.setenv("TS_RESIDUAL_CKPT", str(ckpt))
    assert residual_edit.should_use_residual([{"op": "close_edge", "edge_id": "e0"}]) is False


def test_gate_verdict_reader_defaults_false_on_missing_or_bad(monkeypatch, tmp_path):
    monkeypatch.setenv("TS_RESIDUAL_GATE", str(tmp_path / "nope.json"))
    assert residual_edit.gate_ship_closures() is False
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    monkeypatch.setenv("TS_RESIDUAL_GATE", str(bad))
    assert residual_edit.gate_ship_closures() is False
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"closures": {"ship": True}}))
    monkeypatch.setenv("TS_RESIDUAL_GATE", str(ok))
    assert residual_edit.gate_ship_closures() is True


# ── (b) out-of-scope ops → sim path ────────────────────────────────────────── #


def test_scope_rejects_reopen_surge_and_mixed(monkeypatch, tmp_path):
    # Force the other gate conditions on so only scope can reject.
    ckpt = tmp_path / "ck.pt"
    ckpt.write_bytes(b"stub")
    monkeypatch.setattr(residual_edit, "gate_ship_closures", lambda: True)
    monkeypatch.setattr(residual_edit, "torch_available", lambda: True)
    monkeypatch.setenv("TS_RESIDUAL_CKPT", str(ckpt))

    assert residual_edit.should_use_residual([]) is False  # no edit
    assert residual_edit.should_use_residual([{"op": "reopen_edge", "edge_id": "e0"}]) is False
    assert residual_edit.should_use_residual([{"op": "demand_change", "amount": 1.0}]) is False
    assert residual_edit.should_use_residual([{"op": "change_capacity", "edge_id": "e0"}]) is False
    # mixed closure + surge is out of scope (sim handles the whole scenario)
    mixed = [{"op": "close_edge", "edge_id": "e0"}, {"op": "demand_change", "amount": 1.0}]
    assert residual_edit.should_use_residual(mixed) is False
    # pure closures (single + multi) ARE in scope when everything else is on
    assert residual_edit.should_use_residual([{"op": "close_edge", "edge_id": "e0"}]) is True
    assert (
        residual_edit.is_closure_scope(
            [{"op": "close_edge", "edge_id": "e0"}, {"op": "remove_edge", "edge_id": "e1"}]
        )
        is True
    )


# ── (c) gate ship==true + fake model → residual path → Record5 ─────────────── #


def _inject_fake_bundle(monkeypatch, state, *, dpress_value=0.05):
    """Inject a torch-free fake bundle + fake forward so predict_closure_records runs.

    The fake model returns a constant signed Δpressure for every edge — enough to
    exercise the channel build, the load/pressure apply, and the closed-edge forcing
    without torch. edge_order mirrors the small graph (e0..e3).
    """
    edge_order = state.edge_ids
    capacity = {eid: 1200.0 for eid in edge_order}
    fake_bundle = {
        "graph_id": id(state.graph),
        "edge_order": edge_order,
        "capacity": capacity,
    }
    monkeypatch.setattr(residual_edit, "get_bundle", lambda graph: fake_bundle)
    monkeypatch.setattr(
        residual_edit,
        "model_forward",
        lambda bundle, chan: np.full(len(bundle["edge_order"]), dpress_value, dtype=np.float64),
    )
    return capacity


def test_residual_path_produces_record5(monkeypatch):
    state = _small_state()
    cap = _inject_fake_bundle(monkeypatch, state, dpress_value=0.10)
    # Open-road sim baseline (the sim_open source) as Record5 tuples.
    baseline = [
        (state.edge_index["e0"], 600.0, 50.0, 0.5, 0),
        (state.edge_index["e1"], 300.0, 50.0, 0.25, 0),
        (state.edge_index["e2"], 0.0, 50.0, 0.0, 0),
        (state.edge_index["e3"], 120.0, 50.0, 0.1, 0),
    ]
    recs = residual_edit.predict_closure_records(
        state,
        baseline,
        interventions=[{"op": "close_edge", "edge_id": "e0"}],
        time_context={"hour": 17, "day_of_week": 2, "month": 6},
    )
    by_idx = {r[0]: r for r in recs}
    # Every edge present, each a 5-tuple.
    assert len(recs) == 4
    assert all(len(r) == 5 for r in recs)
    # Closed edge: zeroed load/speed/pressure, closure flag set.
    closed = by_idx[state.edge_index["e0"]]
    assert closed[1] == 0.0 and closed[2] == 0.0 and closed[3] == 0.0 and closed[4] == 1
    # An open edge: Δpressure (0.10) applied to baseline pressure, ×cap to load.
    e1 = by_idx[state.edge_index["e1"]]
    assert e1[4] == 0
    assert e1[3] == pytest.approx(0.25 + 0.10)  # new pressure
    assert e1[1] == pytest.approx(300.0 + 0.10 * cap["e1"])  # new load


def test_residual_path_via_dispatch(monkeypatch):
    """End-to-end through recompute_scenario with the gate mocked on + fake model.

    The open-road baseline is itself produced by recompute (interventions=[]); we
    stub _run to return a deterministic baseline so no real sim/torch is needed.
    """
    state = _small_state()
    _inject_fake_bundle(monkeypatch, state, dpress_value=0.05)
    monkeypatch.setattr(residual_edit, "gate_ship_closures", lambda: True)
    monkeypatch.setattr(residual_edit, "torch_available", lambda: True)
    monkeypatch.setattr(residual_edit, "checkpoint_present", lambda: True)

    baseline_records = [
        (state.edge_index["e0"], 600.0, 50.0, 0.5, 0),
        (state.edge_index["e1"], 300.0, 50.0, 0.25, 0),
        (state.edge_index["e2"], 0.0, 50.0, 0.0, 0),
        (state.edge_index["e3"], 120.0, 50.0, 0.1, 0),
    ]

    def fake_run(state_, model_kind, tc, interventions, iterations):
        # only ever called for the no-edit open-road baseline here
        assert interventions == []
        return {
            "records": baseline_records,
            "summary": {"src": "sim_open"},
            "rgap": 0.0,
            "model_actual": "stub",
        }

    monkeypatch.setattr(rc, "_run", fake_run)

    res = rc.recompute_scenario(
        state,
        time_context={"hour": 17, "day_of_week": 2, "month": 6},
        interventions=[{"op": "close_edge", "edge_id": "e0"}],
    )
    assert res["predictor"] == "residual_gnn"
    assert res["verified"] is False
    assert res["cached"] is False
    by_idx = {r[0]: r for r in res["records"]}
    assert by_idx[state.edge_index["e0"]][4] == 1  # closed
    assert len(res["records"]) == 4


# ── (d) determinism ────────────────────────────────────────────────────────── #


def test_residual_path_is_deterministic(monkeypatch):
    state = _small_state()
    _inject_fake_bundle(monkeypatch, state, dpress_value=0.07)
    baseline = [
        (state.edge_index["e0"], 600.0, 50.0, 0.5, 0),
        (state.edge_index["e1"], 300.0, 50.0, 0.25, 0),
        (state.edge_index["e2"], 90.0, 50.0, 0.075, 0),
        (state.edge_index["e3"], 120.0, 50.0, 0.1, 0),
    ]
    ivs = [{"op": "close_edge", "edge_id": "e1"}]
    r1 = residual_edit.predict_closure_records(state, baseline, interventions=ivs)
    r2 = residual_edit.predict_closure_records(state, baseline, interventions=ivs)
    assert r1 == r2
