"""P11 — timing harness: records, nesting, deterministic labels, low overhead."""

from __future__ import annotations

import time

from torontosim.perf import timing


def setup_function():
    timing.reset_timings()


def test_timer_records_label_and_duration():
    with timing.timer("work"):
        time.sleep(0.01)
    recs = timing.get_timings()
    assert len(recs) == 1
    assert recs[0]["label"] == "work"
    assert recs[0]["ms"] >= 9.0  # ~10ms sleep


def test_timed_decorator_records_per_call():
    @timing.timed("fn")
    def fn(x):
        return x * 2

    assert fn(3) == 6
    fn(4)
    assert [r["label"] for r in timing.get_timings()] == ["fn", "fn"]


def test_nested_timers_compose_outer_after_inner():
    with timing.timer("outer"):
        with timing.timer("inner"):
            time.sleep(0.005)
    labels = [r["label"] for r in timing.get_timings()]
    # Inner completes (and records) before the outer context exits.
    assert labels == ["inner", "outer"]


def test_summary_aggregates_by_label():
    for _ in range(3):
        with timing.timer("loop"):
            pass
    s = timing.summary()
    assert s["loop"]["count"] == 3
    assert "mean_ms" in s["loop"]


def test_bench_on_small_state_has_table_schema():
    """bench.benchmark on an injected small graph emits the expected schema."""
    import networkx as nx

    from torontosim.api.store import AppState
    from torontosim.graph import schema as gschema
    from torontosim.perf.bench import benchmark, to_markdown

    g = nx.MultiDiGraph()
    coords = {0: (-79.40, 43.64), 1: (-79.39, 43.65), 2: (-79.39, 43.63), 3: (-79.38, 43.64)}
    for n, (x, y) in coords.items():
        g.add_node(n, x=x, y=y)
    for i, (u, v) in enumerate([(0, 1), (0, 2), (1, 3), (2, 3)]):
        g.add_edge(
            u,
            v,
            key=0,
            **gschema.make_edge(
                edge_id=f"e{i}",
                from_node=u,
                to_node=v,
                road_class="primary",
                length_m=1000.0,
                speed_kmh=50.0,
                lanes=2.0,
                capacity=1200.0,
                base_time_min=1.2,
            ),
        )
    state = AppState.from_graph(
        g,
        [{"origin": 0, "destination": 3, "trips": 1500.0}],
        weather="clear",
        time_context={"hour": 17},
    )
    res = benchmark(state, close_edge_id="e0")
    for key in (
        "recompute_full_ms",
        "recompute_blast_ms",
        "speedup",
        "affected_subgraph_fraction",
        "closed_edge",
        "n_edges",
    ):
        assert key in res
    assert res["recompute_full_ms"] is not None
    assert "Speedup" in to_markdown(res)
