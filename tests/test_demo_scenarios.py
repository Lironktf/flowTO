"""P12 — the demo's on-stage guarantee: deterministic, monotone headline metric.

  * each scenario JSON loads;
  * wc_surge produces visibly higher congestion near Exhibition than baseline;
  * wc_fix reduces the headline metric vs wc_surge;
  * re-running gives identical numbers (rehearsal == performance).

The surge/fix relationships are *mechanism-level* (injecting stadium egress
raises Exhibition pressure; the mitigation lowers it) and hold by large margins
at any demand scale. The PR-fast checks therefore run them on a small OD
(``_FAST_PAIRS`` pairs, ``_FAST_ITERS`` iterations) — seconds instead of the
minutes a full-scale assignment takes. The full-fidelity guarantee at the demo's
real demand + iteration count runs in the nightly/``slow`` suite
(``test_full_fidelity_demo_guarantee``, ``test_deterministic_rerun``).

Shares one graph + baseline OD load across the three scenarios (slow to build
once).
"""

from __future__ import annotations

import pytest

from torontosim.demo import wc_surge

# Small demand + few equilibrium iterations: enough to exercise the surge/fix
# mechanism without the minutes-long full-scale assignment over the 81k-edge
# graph. The monotone relationships hold by orders of magnitude at this scale
# (see ``test_full_fidelity_demo_guarantee`` for the demo's real numbers).
_FAST_PAIRS = 60
_FAST_ITERS = 2


@pytest.fixture(scope="module")
def demo_runs():
    graph = wc_surge.load_graph()
    od = wc_surge.baseline_demand(graph, max_pairs=_FAST_PAIRS)
    return {
        name: wc_surge.run_scenario(name, graph=graph, baseline_od=od, iterations=_FAST_ITERS)
        for name in ("baseline", "wc_surge", "wc_fix")
    }


def test_scenario_jsons_load():
    for name in ("baseline", "wc_surge", "wc_fix"):
        cfg = wc_surge.load_scenario_json(name)
        assert cfg["id"] == name


def test_surge_worse_than_baseline_near_exhibition(demo_runs):
    base = demo_runs["baseline"]["exhibition_pressure"]
    surge = demo_runs["wc_surge"]["exhibition_pressure"]
    assert surge > base, f"surge {surge} should exceed baseline {base} near Exhibition"
    # The surge also worsens total network delay.
    assert demo_runs["wc_surge"]["total_delay"] > demo_runs["baseline"]["total_delay"]


def test_fix_improves_headline_vs_surge(demo_runs):
    surge = demo_runs["wc_surge"]["headline_metric"]
    fix = demo_runs["wc_fix"]["headline_metric"]
    assert fix < surge, f"fix {fix} should reduce the surge headline {surge}"


@pytest.mark.heavy
def test_full_fidelity_demo_guarantee():
    """The real on-stage numbers: run all three scenarios at the demo's full
    demand + iteration count and assert the same monotone guarantee. Heavy
    (minutes on the 81k-edge graph) — runs in the nightly/full suite."""
    graph = wc_surge.load_graph()
    od = wc_surge.baseline_demand(graph)
    runs = wc_surge.run_all(graph=graph, baseline_od=od)
    assert runs["wc_surge"]["exhibition_pressure"] > runs["baseline"]["exhibition_pressure"]
    assert runs["wc_surge"]["total_delay"] > runs["baseline"]["total_delay"]
    assert runs["wc_fix"]["headline_metric"] < runs["wc_surge"]["headline_metric"]


@pytest.mark.heavy
def test_deterministic_rerun():
    """rehearsal == performance: identical numbers across full-scale reruns."""
    graph = wc_surge.load_graph()
    od = wc_surge.baseline_demand(graph)
    a = wc_surge.run_scenario("wc_surge", graph=graph, baseline_od=od)
    b = wc_surge.run_scenario("wc_surge", graph=graph, baseline_od=od)
    assert a["headline_metric"] == b["headline_metric"]
    assert a["total_delay"] == b["total_delay"]
    assert a["summary"] == b["summary"]
