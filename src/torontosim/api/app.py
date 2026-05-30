"""FastAPI app factory wiring REST + WebSocket over the simulation (P06).

``create_app(state=...)`` lets tests inject a small graph; the production server
(`serve()`) loads the full Toronto graph + baseline OD once at startup.
"""

from __future__ import annotations

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
    app = FastAPI(title="TorontoSim API", version="0.1.0")
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

    # ---- copilot / optimizer placeholders (P09/P10 fill in) ------------- #
    @app.post("/copilot/plan")
    def copilot_plan(payload: dict):
        try:
            from ..copilot.planner import plan_intervention
        except ImportError:
            raise HTTPException(501, "copilot not available (P09 not installed)") from None
        return plan_intervention(payload.get("prompt", ""), state)

    @app.post("/optimize")
    def optimize(payload: dict):
        try:
            from ..optimizer.heuristic import propose
        except ImportError:
            raise HTTPException(501, "optimizer not available (P10 not installed)") from None
        return propose(state, payload)

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
