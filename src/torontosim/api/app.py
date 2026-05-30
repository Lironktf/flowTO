"""FastAPI app factory wiring REST + WebSocket over the simulation (P06).

``create_app(state=...)`` lets tests inject a small graph; the production server
(`serve()`) loads the full Toronto graph + baseline OD once at startup.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .encoding import pack_frame
from .jobs import JobManager
from .schemas import (
    CompareResult,
    RunRequest,
    RunResult,
    Scenario,
    ScenarioCreate,
    ScenarioPatch,
)
from .store import AppState, ScenarioStore, edge_records


def create_app(state: AppState, *, snapshot_dir: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Pre-run the three demo scenarios in a background thread so the first
        # click is instant (a full-graph kpath run is ~tens of seconds).
        import threading

        def warm():
            for sc in ("baseline", "wc_surge", "wc_fix"):
                try:
                    _app.state.demo_cache.setdefault(sc, _compute_demo(sc))
                except Exception:  # noqa: BLE001 — warmup is best-effort
                    pass

        threading.Thread(target=warm, daemon=True).start()
        yield

    app = FastAPI(title="TorontoSim API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Vite dev server; auth is explicitly out of scope.
        allow_methods=["*"],
        allow_headers=["*"],
    )
    store = ScenarioStore(state, snapshot_dir=snapshot_dir)
    jobs = JobManager()
    app.state.store = store
    app.state.jobs = jobs

    # ---- health / debug ------------------------------------------------- #
    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "edges": len(state.edge_ids), "scenarios": len(store.scenarios)}

    @app.get("/debug/state")
    def debug_state():
        return {
            "n_edges": len(state.edge_ids),
            "n_od": len(state.od_matrix),
            "scenarios": [s["id"] for s in store.list()],
        }

    @app.get("/edges")
    def edges_index():
        """The once-uploaded edge table: index -> edge_id + geometry."""
        out = []
        geo = {
            d.get("edge_id"): {
                "geometry": d.get("geometry"),
                "road_name": d.get("road_name"),
                "road_class": d.get("road_class"),
            }
            for _u, _v, d in state.graph.edges(data=True)
        }
        for i, eid in enumerate(state.edge_ids):
            meta = geo.get(eid, {})
            out.append({"idx": i, "edge_id": eid, **meta})
        return {"edges": out}

    # ---- scenario CRUD -------------------------------------------------- #
    @app.post("/scenarios", response_model=Scenario)
    def create_scenario(payload: ScenarioCreate):
        return store.create(payload.model_dump())

    @app.get("/scenarios")
    def list_scenarios():
        return {"scenarios": store.list()}

    @app.get("/scenarios/{sid}", response_model=Scenario)
    def get_scenario(sid: str):
        sc = store.get(sid)
        if sc is None:
            raise HTTPException(404, "scenario not found")
        return sc

    @app.patch("/scenarios/{sid}", response_model=Scenario)
    def patch_scenario(sid: str, patch: ScenarioPatch):
        sc = store.patch(sid, patch.model_dump(exclude_none=True))
        if sc is None:
            raise HTTPException(404, "scenario not found")
        return sc

    @app.delete("/scenarios/{sid}")
    def delete_scenario(sid: str):
        if not store.delete(sid):
            raise HTTPException(404, "scenario not found")
        return {"deleted": sid}

    @app.get("/scenarios/{sid}/interventions")
    def get_interventions(sid: str):
        sc = store.get(sid)
        if sc is None:
            raise HTTPException(404, "scenario not found")
        return {"interventions": sc.get("interventions", [])}

    # ---- run / preview / compare --------------------------------------- #
    def _validate_edges(interventions):
        for iv in interventions:
            eid = iv.get("edge_id")
            if iv.get("op") in ("close_edge", "reopen_edge", "remove_edge", "change_capacity"):
                if eid is None or eid not in state.edge_index:
                    raise HTTPException(422, f"unknown edge_id: {eid!r}")

    @app.post("/scenarios/{sid}/run", response_model=RunResult)
    def run_scenario(sid: str, req: RunRequest):
        sc = store.get(sid)
        if sc is None:
            raise HTTPException(404, "scenario not found")
        _validate_edges(sc.get("interventions", []))
        result = store.run(sid, req.model_dump())
        return RunResult(
            scenario_id=sid,
            summary=result["summary"],
            engine=result.get("engine", req.engine),
            congestion_model=result.get("congestion_model", req.congestion_model),
            recompute=result.get("recompute", req.recompute),
            blast_stats=result.get("blast_stats"),
            rgap=result.get("rgap"),
        )

    @app.post("/scenarios/{sid}/preview")
    def preview_scenario(sid: str, req: RunRequest):
        sc = store.get(sid)
        if sc is None:
            raise HTTPException(404, "scenario not found")
        interventions = sc.get("interventions", [])
        _validate_edges(interventions)
        before = len(store.scenarios)
        result = store.preview(sid, interventions, req.model_dump())
        # Preview must not mutate stored scenario state.
        assert len(store.scenarios) == before
        return {"scenario_id": sid, "summary": result["summary"], "mutated": False}

    @app.get("/scenarios/{sid}/compare", response_model=CompareResult)
    def compare_scenario(sid: str, against: str = "baseline"):
        sc = store.get(sid)
        if sc is None:
            raise HTTPException(404, "scenario not found")
        diff = store.compare(sid)
        return CompareResult(
            scenario_id=sid,
            against=against,
            summary_delta=diff.get("summary_delta", {}),
            most_impacted_edges=diff.get("most_impacted_edges", []),
        )

    @app.get("/scenarios/{sid}/records")
    def scenario_records(sid: str):
        """Per-edge tick records of a scenario's last run (Edit-mode repaint)."""
        sc = store.get(sid)
        if sc is None:
            raise HTTPException(404, "scenario not found")
        result = sc.get("_last_result")
        if result is None:
            raise HTTPException(409, "scenario has not been run yet")
        return {"records": edge_records(state, result["graph"]), "summary": result["summary"]}

    # ---- copilot / optimizer placeholders (P09/P10 fill in) ------------- #
    @app.post("/copilot/plan")
    def copilot_plan(payload: dict):
        try:
            from ..copilot.planner import plan_intervention
        except ImportError:
            raise HTTPException(501, "copilot not available (P09 not installed)") from None
        return plan_intervention(payload.get("prompt", ""), state)

    @app.post("/copilot/explain")
    def copilot_explain(payload: dict):
        try:
            from ..copilot.explain import explain_compare
        except ImportError:
            raise HTTPException(501, "copilot not available") from None
        return {
            "explanation": explain_compare(
                payload.get("summary_delta", {}), top_edges=payload.get("most_impacted_edges")
            )
        }

    @app.post("/optimize")
    def optimize(payload: dict):
        try:
            from ..optimizer.heuristic import propose
        except ImportError:
            raise HTTPException(501, "optimizer not available (P10 not installed)") from None
        return propose(state, payload)

    # ---- transit overlay (P08) ----------------------------------------- #
    @app.get("/transit/routes")
    def transit_routes(agencies: str = "ttc"):
        from ..transit.routes import demo_routes

        wanted = {a.strip() for a in agencies.split(",") if a.strip()}
        return {"routes": [r for r in demo_routes() if r["agency"] in wanted]}

    @app.get("/transit/trajectories")
    def transit_trajectories(date: str = "2026-06-12", agencies: str = "ttc"):
        from ..transit.routes import demo_trajectories

        wanted = {a.strip() for a in agencies.split(",") if a.strip()}
        return {
            "date": date,
            "trajectories": [t for t in demo_trajectories() if t["agency"] in wanted],
        }

    # ---- FIFA WC demo: real engine runs on the real graph (P12) --------- #
    app.state.demo_cache = {}

    def _compute_demo(scenario: str) -> dict:
        from ..demo import wc_surge

        res = wc_surge.run_scenario(
            scenario, graph=state.graph, baseline_od=state.od_matrix, engine="kpath"
        )
        return {
            "scenario": scenario,
            "summary": res["summary"],
            "headline_metric": res["headline_metric"],
            "exhibition_pressure": res["exhibition_pressure"],
            "records": edge_records(state, res["graph"]),
        }

    @app.get("/demo/run")
    def demo_run(scenario: str = "baseline"):
        """Run baseline | wc_surge | wc_fix on the real graph; return per-edge records.

        Deterministic → cached. Records are ``[edge_idx, load, speed, pressure,
        closure]`` aligned to the ``/edges`` index, so the frontend recolors the
        real road network with live engine pressures.
        """
        if scenario not in ("baseline", "wc_surge", "wc_fix"):
            raise HTTPException(422, f"unknown demo scenario: {scenario!r}")
        if scenario not in app.state.demo_cache:
            app.state.demo_cache[scenario] = _compute_demo(scenario)
        return app.state.demo_cache[scenario]

    # ---- jobs ----------------------------------------------------------- #
    @app.get("/jobs/{job_id}")
    def get_job(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return {"id": job.id, "state": job.state, "progress": job.progress, "error": job.error}

    # ---- WebSocket tick stream ----------------------------------------- #
    @app.websocket("/scenarios/{sid}/stream")
    async def stream(ws: WebSocket, sid: str):
        await ws.accept()
        sc = store.get(sid)
        if sc is None:
            await ws.close(code=4404)
            return
        result = sc.get("_last_result") or store.run(sid, {})
        try:
            # Stream one binary frame per captured propagation frame, then close.
            frames = result.get("frames") or [None]
            for fr in frames:
                graph = result["graph"]
                records = edge_records(state, graph)
                await ws.send_bytes(pack_frame(records))
            await ws.close()
        except WebSocketDisconnect:
            return

    return app


def serve(host: str = "0.0.0.0", port: int = 8000):  # pragma: no cover - runtime entry
    """Production entry: load the full graph + baseline OD, then run uvicorn."""
    import uvicorn

    from ._bootstrap import load_default_state

    app = create_app(load_default_state())
    uvicorn.run(app, host=host, port=port)
