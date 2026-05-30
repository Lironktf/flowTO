"""P12 — the demo's on-stage guarantee: deterministic, monotone headline metric.

  * each scenario JSON loads;
  * wc_surge produces visibly higher congestion near Exhibition than baseline;
  * wc_fix reduces the headline metric vs wc_surge;
  * re-running gives identical numbers (rehearsal == performance).

Shares one graph + baseline OD load across scenarios (slow to build once).
"""

from __future__ import annotations

import pytest

from torontosim.demo import wc_surge


@pytest.fixture(scope="module")
def demo_runs():
    graph = wc_surge.load_graph()
    od = wc_surge.baseline_demand(graph)
    return wc_surge.run_all(graph=graph, baseline_od=od)


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


def test_deterministic_rerun():
    graph = wc_surge.load_graph()
    od = wc_surge.baseline_demand(graph)
    a = wc_surge.run_scenario("wc_surge", graph=graph, baseline_od=od)
    b = wc_surge.run_scenario("wc_surge", graph=graph, baseline_od=od)
    assert a["headline_metric"] == b["headline_metric"]
    assert a["total_delay"] == b["total_delay"]
    assert a["summary"] == b["summary"]
