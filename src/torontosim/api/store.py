"""In-memory scenario store + shared app state (P06).

``AppState`` holds the read-only baseline graph, the baseline OD, a stable
edge-id index (string id -> u32 used by the binary frames), and the cached
baseline simulation result. ``ScenarioStore`` is the per-scenario CRUD + run /
preview / compare orchestration over the simulator and blast-radius.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

from ..simulation.simulate_traffic import (
    compare_simulations,
    simulate_scenario,
    simulate_traffic,
)


@dataclass
class AppState:
    graph: object
    od_matrix: list
    weather: str = "clear"
    time_context: dict = field(default_factory=dict)
    edge_ids: list = field(default_factory=list)  # index -> edge_id (str)
    edge_index: dict = field(default_factory=dict)  # edge_id -> index
    _baseline: dict | None = None
    # Cached AON/blast baseline + its lock — used by blast_baseline(). These were
    # dropped in an AppState refactor while blast_baseline() still references them,
    # so any blast/compare path raised AttributeError; re-declared here.
    _blast_baseline: dict | None = None
    _baseline_lock: object = field(default_factory=threading.Lock)
    # Baseline OD is built lazily (see ensure_od) so the server boots without
    # loading the demand model. od_max_pairs is the gravity cap for that build.
    od_max_pairs: int = 800
    _od_lock: object = field(default_factory=threading.Lock)
    # Param-driven recompute cache (api/recompute.py): LRU keyed on
    # (model, time_context, interventions) -> {records, summary, ...}. A per-key
    # lock collapses concurrent identical requests; _cache_lock guards the maps.
    _recompute_cache: "OrderedDict" = field(default_factory=OrderedDict)
    _recompute_locks: dict = field(default_factory=dict)
    _cache_lock: object = field(default_factory=threading.Lock)

    @classmethod
    def from_graph(cls, graph, od_matrix, *, weather="clear", time_context=None):
        edge_ids = sorted(
            {d.get("edge_id") for _u, _v, d in graph.edges(data=True) if d.get("edge_id")},
            key=str,
        )
        edge_index = {eid: i for i, eid in enumerate(edge_ids)}
        return cls(
            graph=graph,
            od_matrix=od_matrix,
            weather=weather,
            time_context=time_context or {},
            edge_ids=edge_ids,
            edge_index=edge_index,
        )

    def ensure_od(self) -> list:
        """Build the baseline OD matrix on first legacy use, then cache it.

        The main UX (baseline + ML day-stream) never calls this — ``api/recompute``
        grounds its own OD per request — so startup can skip the demand-model load.
        Only the legacy scenario run/preview/compare and ``/demo/run`` need a
        shared baseline OD; the first such call pays a one-time model+predict+OD
        build (double-checked under a lock so concurrent callers share the work).
        """
        if self.od_matrix:
            return self.od_matrix
        with self._od_lock:
            if self.od_matrix:
                return self.od_matrix
            from ..model.generate_od_matrix import generate_od_matrix
            from ..model.predict_node_demand import load_demand_model, predict_node_demand

            tc = self.time_context or {"hour": 17, "day_of_week": 4, "month": 6, "weather": "clear"}
            model = load_demand_model()
            demand = predict_node_demand(self.graph, model, tc)
            self.od_matrix = generate_od_matrix(self.graph, demand, tc, max_pairs=self.od_max_pairs)
            return self.od_matrix

    def baseline(self, *, iterations: int = 4, congestion_model: str = "bpr") -> dict:
        """Cached baseline run (no interventions) — the compare reference.

        Lock-guarded (double-checked): the first caller computes; concurrent
        callers wait rather than each kicking off a ~2-min full-graph sim.
        """
        if self._baseline is None:
            self.ensure_od()
            self._baseline = simulate_traffic(
                self.graph,
                self.od_matrix,
                iterations=iterations,
                weather=self.weather,
                time_context=self.time_context,
                auto_calibrate=False,
                congestion_model=congestion_model,
            )
        return self._baseline

    def blast_baseline(self, *, iterations: int = 4, congestion_model: str = "bpr") -> dict:
        """Cached AON baseline via the blast path (no interventions).

        A blast scenario re-routes only affected ODs over an AON assignment, so
        its global numbers are NOT comparable to the iterative ``baseline()``.
        This same-method reference makes blast-vs-baseline deltas correct + fast.
        """
        if self._blast_baseline is None:
            with self._baseline_lock:
                if self._blast_baseline is None:
                    self._blast_baseline = simulate_scenario(
                        self.graph,
                        self.od_matrix,
                        [],
                        iterations=iterations,
                        weather=self.weather,
                        time_context=self.time_context,
                        congestion_model=congestion_model,
                        recompute="blast",
                    )
        return self._blast_baseline


def edge_records(state: AppState, graph) -> list:
    """Build binary-frame records for a result graph (see api.encoding)."""
    records = []
    for _u, _v, d in graph.edges(data=True):
        eid = d.get("edge_id")
        idx = state.edge_index.get(eid)
        if idx is None:
            continue
        closed = d.get("status") == "closed"
        base = d.get("base_time_min") or 0.0
        cur = d.get("current_time_min")
        spd = d.get("speed_kmh") or 0.0
        if cur and cur not in (0, float("inf")) and base:
            eff_speed = spd * (base / cur)
        else:
            eff_speed = 0.0 if closed else spd
        pressure = d.get("pressure")
        pressure = 0.0 if pressure in (None, float("inf")) else float(pressure)
        records.append((idx, d.get("load", 0.0) or 0.0, eff_speed, pressure, closed))
    return records


class ScenarioStore:
    def __init__(self, state: AppState, *, snapshot_dir: str | None = None):
        self.state = state
        self.scenarios: dict[str, dict] = {}
        self.snapshot_dir = snapshot_dir

    # ---- CRUD ----------------------------------------------------------- #
    def create(self, payload: dict) -> dict:
        sid = uuid.uuid4().hex[:12]
        scenario = {"id": sid, **payload}
        self.scenarios[sid] = scenario
        self._snapshot(sid)
        return scenario

    def get(self, sid: str) -> dict | None:
        return self.scenarios.get(sid)

    def patch(self, sid: str, patch: dict) -> dict | None:
        sc = self.scenarios.get(sid)
        if sc is None:
            return None
        sc.update({k: v for k, v in patch.items() if v is not None})
        self._snapshot(sid)
        return sc

    def delete(self, sid: str) -> bool:
        return self.scenarios.pop(sid, None) is not None

    def list(self) -> list:
        return list(self.scenarios.values())

    def _snapshot(self, sid: str) -> None:
        if not self.snapshot_dir:
            return
        os.makedirs(self.snapshot_dir, exist_ok=True)
        with open(os.path.join(self.snapshot_dir, f"{sid}.json"), "w") as fh:
            json.dump(self.scenarios[sid], fh, indent=2, default=str)

    # ---- run / preview / compare --------------------------------------- #
    def _ops(self, sid: str) -> list:
        sc = self.scenarios[sid]
        return [iv if isinstance(iv, dict) else iv for iv in sc.get("interventions", [])]

    def run(self, sid: str, req: dict) -> dict:
        sc = self.scenarios[sid]
        self.state.ensure_od()  # legacy path: build the shared baseline OD on first use
        result = simulate_scenario(
            self.state.graph,
            self.state.od_matrix,
            sc.get("interventions", []),
            iterations=req.get("iterations", 4),
            weather=sc.get("weather", self.state.weather),
            time_context=sc.get("time_context", self.state.time_context),
            engine=req.get("engine", "kpath"),
            congestion_model=req.get("congestion_model", "bpr"),
            backend=req.get("backend", "cpu"),
            recompute=req.get("recompute", "full"),
        )
        sc["_last_result"] = result
        return result

    def preview(self, sid: str, interventions: list, req: dict) -> dict:
        """Run a hypothetical intervention set WITHOUT committing it."""
        self.state.ensure_od()  # legacy path: build the shared baseline OD on first use
        result = simulate_scenario(
            self.state.graph,
            self.state.od_matrix,
            interventions,
            iterations=req.get("iterations", 4),
            weather=self.state.weather,
            time_context=self.state.time_context,
            engine=req.get("engine", "kpath"),
            congestion_model=req.get("congestion_model", "bpr"),
            recompute=req.get("recompute", "full"),
        )
        return result

    def compare(self, sid: str) -> dict:
        sc = self.scenarios[sid]
        scenario_result = sc.get("_last_result")
        if scenario_result is None:
            scenario_result = self.run(sid, {})
        # Compare against a baseline computed with the SAME assignment method:
        # a blast scenario (AON re-route) vs the iterative full baseline would
        # diff two different methods and report nonsense global deltas.
        is_blast = (
            scenario_result.get("recompute") == "blast" or scenario_result.get("engine") == "blast"
        )
        base = self.state.blast_baseline() if is_blast else self.state.baseline()
        return compare_simulations(base, scenario_result)
