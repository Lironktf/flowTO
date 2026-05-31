"""Match-day demand injection + the three demo scenarios (P12).

A special-generator injection at BMO Field (Exhibition Place) adds ~45,000 of
post-match egress demand to the evening OD. The mitigation models the rehearsed
road-side plan as (a) a transit/pedestrian shift that removes part of the
concentrated egress and (b) a capacity uplift on arterials near the stadium
(contraflow + signal retiming). Everything is deterministic and labeled as a
scenario multiplier (hypothetical), per the spec's stance.
"""

from __future__ import annotations

import json
import os

from ..graph.config import haversine_m
from ..graph.routing import import_graph_json
from ..simulation.simulate_traffic import simulate_traffic

# BMO Field / Exhibition Place (lng, lat) — the egress generator.
STADIUM_LNG, STADIUM_LAT = -79.4185, 43.6332

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_GRAPH = os.path.join(_REPO_ROOT, "data", "graph", "toronto_drive_graph.json")
SCENARIO_DIR = os.path.join(_REPO_ROOT, "demo", "scenarios")

# Evening rush, Fri 12 Jun 2026 (matchday). Deterministic time context.
TIME_CONTEXT = {"hour": 17, "day_of_week": 4, "month": 6, "weather": "clear"}


def load_graph(graph_path: str | None = None):
    return import_graph_json(graph_path or os.environ.get("TS_GRAPH_JSON", DEFAULT_GRAPH))


def baseline_demand(graph, *, max_pairs: int = 600):
    """The weekday-5pm OD the demo starts from (deterministic)."""
    from ..model.generate_od_matrix import generate_od_matrix
    from ..model.predict_node_demand import load_demand_model, predict_node_demand

    model = load_demand_model()
    demand = predict_node_demand(graph, model, TIME_CONTEXT)
    od = generate_od_matrix(graph, demand, TIME_CONTEXT, max_pairs=max_pairs)
    return od


def _nearest_node(graph, lng: float, lat: float):
    best, best_d = None, float("inf")
    for n, d in graph.nodes(data=True):
        nlng = d.get("x")
        nlat = d.get("y")
        if nlng is None or nlat is None:
            continue
        dist = haversine_m(lat, lng, nlat, nlng)
        if dist < best_d:
            best, best_d = n, dist
    return best


def _nodes_within(graph, lng: float, lat: float, radius_m: float):
    out = []
    for n, d in graph.nodes(data=True):
        nlng, nlat = d.get("x"), d.get("y")
        if nlng is None or nlat is None:
            continue
        if haversine_m(lat, lng, nlat, nlng) <= radius_m:
            out.append(n)
    return out


def inject_egress(graph, od, *, total_trips: float = 45_000.0, k_dest: int = 40):
    """Add ~``total_trips`` of egress from the stadium to spread destinations.

    Destinations are the strongest existing OD destinations (where people are
    already heading in the evening), so the surge loads the real egress spine.
    Deterministic: sorted, fixed split.
    """
    origin = _nearest_node(graph, STADIUM_LNG, STADIUM_LAT)
    # Rank candidate destinations by how often they appear as OD destinations.
    dest_weight: dict = {}
    for e in od:
        dest_weight[e["destination"]] = dest_weight.get(e["destination"], 0.0) + e["trips"]
    dests = sorted(dest_weight, key=lambda d: (-dest_weight[d], str(d)))[:k_dest]
    if not dests:
        return list(od)
    per = total_trips / len(dests)
    surge = list(od)
    for d in dests:
        if d != origin:
            surge.append({"origin": origin, "destination": d, "trips": per})
    return surge


def mitigate(
    graph,
    surge_od,
    *,
    transit_shift: float = 0.30,
    capacity_uplift: float = 1.4,
    radius_m: float = 1500.0,
):
    """Apply the rehearsed road-side plan to a COPY of the graph + OD.

    Models: (a) ``transit_shift`` of the egress moved to 509/511 + pedestrian
    egress (removed from the road OD); (b) ``capacity_uplift`` on arterials
    within ``radius_m`` of the stadium (contraflow + signal retiming). Returns
    ``(mitigated_graph, mitigated_od)``. Deterministic.
    """
    g = graph.copy()
    from ..graph.routing import build_edge_index

    build_edge_index(g)
    origin = _nearest_node(g, STADIUM_LNG, STADIUM_LAT)
    near = set(_nodes_within(g, STADIUM_LNG, STADIUM_LAT, radius_m))

    # (b) capacity uplift on arterial+ edges near the stadium.
    boosted = 0
    for u, v, d in g.edges(data=True):
        if (u in near or v in near) and d.get("road_class") in (
            "motorway",
            "trunk",
            "primary",
            "secondary",
        ):
            d["capacity"] = float(d.get("capacity", 0.0) or 0.0) * capacity_uplift
            boosted += 1

    # (a) shift part of the stadium egress off the road network.
    mit_od = []
    for e in surge_od:
        if e["origin"] == origin:
            mit_od.append({**e, "trips": e["trips"] * (1.0 - transit_shift)})
        else:
            mit_od.append(e)
    return g, mit_od, {"edges_boosted": boosted, "transit_shift": transit_shift}


def total_delay(graph) -> float:
    """Headline metric: total network delay (veh·min) = Σ load·(t − t0) over open edges."""
    total = 0.0
    for _u, _v, d in graph.edges(data=True):
        if d.get("status") == "closed":
            continue
        load = d.get("load", 0.0) or 0.0
        cur = d.get("current_time_min")
        base = d.get("base_time_min", 0.0) or 0.0
        if cur is None or cur == float("inf"):
            continue
        total += load * max(0.0, cur - base)
    return total


def exhibition_pressure(graph, *, radius_m: float = 1500.0) -> float:
    """Average pressure on open edges near the stadium (the surge read)."""
    near = set(_nodes_within(graph, STADIUM_LNG, STADIUM_LAT, radius_m))
    ps = []
    for u, v, d in graph.edges(data=True):
        if d.get("status") == "closed":
            continue
        if u in near or v in near:
            p = d.get("pressure")
            if isinstance(p, (int, float)) and p != float("inf"):
                ps.append(p)
    return sum(ps) / len(ps) if ps else 0.0


def run_scenario(
    name: str,
    *,
    graph=None,
    baseline_od=None,
    iterations: int = 4,
    engine: str = "kpath",
    congestion_model: str = "bpr",
) -> dict:
    """Run one of ``baseline`` | ``wc_surge`` | ``wc_fix`` and return metrics.

    Pass a shared ``graph`` + ``baseline_od`` to avoid reloading for each.
    """
    if graph is None:
        graph = load_graph()
    if baseline_od is None:
        baseline_od = baseline_demand(graph)

    if name == "baseline":
        g, od, extra = graph, baseline_od, {}
    elif name == "wc_surge":
        g, od, extra = graph, inject_egress(graph, baseline_od), {"surge": True}
    elif name == "wc_fix":
        surge_od = inject_egress(graph, baseline_od)
        g, od, extra = mitigate(graph, surge_od)
    else:
        raise ValueError(f"unknown scenario: {name!r}")

    result = simulate_traffic(
        g,
        od,
        iterations=iterations,
        weather=TIME_CONTEXT["weather"],
        time_context=TIME_CONTEXT,
        auto_calibrate=False,
        engine=engine,
        congestion_model=congestion_model,
    )
    rg = result["graph"]
    exhib = round(exhibition_pressure(rg), 4)
    return {
        "scenario": name,
        "summary": result["summary"],
        "total_delay": round(total_delay(rg), 1),
        "exhibition_pressure": exhib,
        # The demo headline: egress-area congestion near BMO Field (the heatmap
        # that melts red→green). Calm at baseline, gridlock at surge, eased at fix.
        "headline_metric": exhib,
        "extra": extra,
        # The simulated result graph — consumed by the API to emit per-edge tick
        # records (kept out of the JSON-serialized fields above).
        "graph": rg,
    }


def run_all(*, graph=None, baseline_od=None) -> dict:
    """Run all three scenarios off one shared graph + OD. Deterministic."""
    if graph is None:
        graph = load_graph()
    if baseline_od is None:
        baseline_od = baseline_demand(graph)
    return {
        name: run_scenario(name, graph=graph, baseline_od=baseline_od)
        for name in ("baseline", "wc_surge", "wc_fix")
    }


def load_scenario_json(name: str) -> dict:
    with open(os.path.join(SCENARIO_DIR, f"{name}.json")) as fh:
        return json.load(fh)


def main(argv=None):  # pragma: no cover - CLI
    import argparse

    p = argparse.ArgumentParser(prog="torontosim.demo.wc_surge")
    p.add_argument("--scenario", choices=["baseline", "wc_surge", "wc_fix", "all"], default="all")
    args = p.parse_args(argv)
    graph = load_graph()
    od = baseline_demand(graph)
    if args.scenario == "all":
        res = run_all(graph=graph, baseline_od=od)
        for name in ("baseline", "wc_surge", "wc_fix"):
            r = res[name]
            print(
                f"{name:10} delay={r['total_delay']:>14,.0f}  exhib_p={r['exhibition_pressure']:.3f}"
            )
    else:
        print(json.dumps(run_scenario(args.scenario, graph=graph, baseline_od=od), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
