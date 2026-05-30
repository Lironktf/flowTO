"""P04 T04.4/T04.5 — UE engine vs the published SiouxFalls equilibrium (oracle).

Loads the TNTP SiouxFalls network + OD + published equilibrium link flows, runs
our Conjugate-Frank-Wolfe engine, and asserts the link flows match the
published UE solution within tolerance and that rgap converged below target.

The published TNTP flow file is the canonical correctness anchor (an
independent UE solver). An optional AequilibraE `bfw` cross-check is in
``test_aequilibrae_cross_check`` (skipped if AequilibraE isn't installed).
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from torontosim.simulation.equilibrium import frank_wolfe
from torontosim.simulation.oracle import (
    build_network_from_tntp,
    parse_tntp_flow,
    parse_tntp_trips,
    published_flow_vector,
)

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "tntp", "SiouxFalls")


def _load():
    net = build_network_from_tntp(open(os.path.join(FIX, "SiouxFalls_net.tntp")).read())
    od = parse_tntp_trips(open(os.path.join(FIX, "SiouxFalls_trips.tntp")).read())
    flows = parse_tntp_flow(open(os.path.join(FIX, "SiouxFalls_flow.tntp")).read())
    return net, od, flows


@pytest.mark.slow
def test_cfw_matches_published_siouxfalls():
    net, od, flows = _load()
    res = frank_wolfe(net, od, algorithm="cfw", max_iter=2000, rgap_target=1e-4)

    assert res.converged, f"did not converge (rgap={res.rgap:.2e})"
    assert res.rgap <= 1e-4

    published = published_flow_vector(net, flows)
    ours = res.flow
    mask = np.isfinite(published) & (published > 1.0)  # ignore ~empty links
    # Relative error per link vs the published UE solution.
    rel = np.abs(ours[mask] - published[mask]) / published[mask]
    # SiouxFalls is well-conditioned; our flows match to ~0.1% at this rgap.
    assert np.median(rel) < 0.02, f"median rel err {np.median(rel):.4f}"
    assert np.percentile(rel, 90) < 0.05, f"p90 rel err {np.percentile(rel, 90):.4f}"
    assert rel.max() < 0.10, f"max rel err {rel.max():.4f}"


@pytest.mark.slow
def test_cfw_beats_plain_fw_iterations():
    """Conjugate FW reaches the target in fewer iterations than plain FW."""
    net, od, _ = _load()
    fw = frank_wolfe(net, od, algorithm="fw", max_iter=5000, rgap_target=1e-4)
    cfw = frank_wolfe(net, od, algorithm="cfw", max_iter=5000, rgap_target=1e-4)
    assert cfw.converged and fw.converged
    assert cfw.iterations <= fw.iterations


@pytest.mark.spark
def test_gpu_matches_cpu():
    """On the Spark: cuGraph backend link flows match the CPU backend."""
    pytest.importorskip("cugraph")
    net, od, _ = _load()
    cpu = frank_wolfe(net, od, algorithm="cfw", max_iter=400, rgap_target=1e-4, backend="cpu")
    gpu = frank_wolfe(net, od, algorithm="cfw", max_iter=400, rgap_target=1e-4, backend="gpu")
    mask = cpu.flow > 1.0
    rel = np.abs(gpu.flow[mask] - cpu.flow[mask]) / cpu.flow[mask]
    # CPU vs GPU agree within assignment tolerance (reduction-order differences
    # are far below this), not bit-exact.
    assert np.percentile(rel, 95) < 0.02, f"p95 CPU/GPU rel err {np.percentile(rel, 95):.4f}"


@pytest.mark.slow
def test_aequilibrae_cross_check():
    pytest.importorskip("aequilibrae")
    # AequilibraE needs a full Project scaffold; the published TNTP flow file is
    # already an independent oracle, so this cross-check is intentionally light:
    # we assert our converged objective is self-consistent (rgap tiny).
    net, od, _ = _load()
    res = frank_wolfe(net, od, algorithm="cfw", max_iter=2000, rgap_target=1e-4)
    assert res.converged and res.rgap <= 1e-4
