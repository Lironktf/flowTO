"""FastAPI app factory wiring REST + WebSocket over the simulation (P06).

``create_app(state=...)`` lets tests inject a small graph; the production server
(`serve()`) loads the full Toronto graph + baseline OD once at startup.
"""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

from .encoding import pack_frame
from .jobs import JobManager
from .schemas import (
    CompareResult,
    CopilotConfirm,
    CopilotConfirmResult,
    RunRequest,
    RunResult,
    Scenario,
    ScenarioCreate,
    ScenarioPatch,
)
from .store import AppState, ScenarioStore, edge_records


def _transit_data_dir() -> str:
    import os

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    return os.path.abspath(os.environ.get("TS_DATA_DIR", os.path.join(repo_root, "data")))


def _load_real_feed(agency: str, *, date: str):
    """Return a cached real GTFS feed for ``agency`` (any date), else ``None``."""
    from ..transit.gtfs_reader import load_cached_feed

    return load_cached_feed(agency, date, _transit_data_dir())


def create_app(state: AppState, *, snapshot_dir: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Warm only the initial baseline. Warming all three demo scenarios here
        # delays the first graph response and spends CPU on data the map does not
        # need yet.
        def warm():
            try:
                _get_demo("baseline")
            except Exception:  # noqa: BLE001 — warmup is best-effort
                pass
            # Pre-load the copilot model so the first ask dodges the cold load.
            try:
                from ..copilot import ollama_client, planner

                if planner._live_enabled() and ollama_client.available():
                    ollama_client.warmup()
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
        # Strip internal keys (e.g. _last_result holds a full graph) — they are
        # not part of a scenario's public shape and aren't JSON-serializable.
        public = [{k: v for k, v in sc.items() if not k.startswith("_")} for sc in store.list()]
        return {"scenarios": public}

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

    @app.post("/copilot/stream")
    def copilot_stream(payload: dict):
        """SSE token stream for the free-text ask/explain path + a latency HUD.

        Streams Nemotron tokens as Server-Sent Events; the final event carries
        first-token and total latency (ms). Grounds any bylaw claim in RAG.
        """
        import json as _json
        import time

        from ..copilot import ollama_client, rag

        prompt = payload.get("prompt", "")
        try:
            hits = rag.retrieve(prompt, k=3)
        except Exception:  # noqa: BLE001
            hits = []
        ctx = "\n".join(f"- {h['title']}" for h in hits)
        system = (
            "You are a Toronto city-planning copilot. Answer the planner concisely (≤4 sentences). "
            "Ground any bylaw/policy claim ONLY in this context; do not invent citations:\n" + ctx
        )

        def gen():
            t0 = time.monotonic()
            first_ms = None
            try:
                for evt in ollama_client.stream(system, prompt):
                    if evt["first"]:
                        first_ms = round((time.monotonic() - t0) * 1000)
                    out = {"token": evt["token"], "done": evt["done"]}
                    if evt["done"]:
                        out["first_token_ms"] = first_ms
                        out["total_ms"] = evt["total_ms"]
                        out["backend"] = rag.backend_name()
                    yield f"data: {_json.dumps(out)}\n\n"
            except Exception as exc:  # noqa: BLE001 — surface a clean done event
                yield f"data: {_json.dumps({'error': str(exc), 'done': True})}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/copilot/debug", response_class=HTMLResponse)
    def copilot_debug_page():
        """Standalone copilot debug console (no build step — just open the URL)."""
        from ..copilot.debug_page import DEBUG_HTML

        return HTMLResponse(DEBUG_HTML)

    @app.post("/copilot/agent")
    def copilot_agent(payload: dict):
        """Bounded, read-only multi-tool agent loop (investigate → propose).

        Nemotron chains read-only tools (simulate-on-scratch, optimize, retrieve)
        then proposes a plan for human confirmation — it never mutates the store.
        """
        try:
            from ..copilot.agent import run_agent
        except ImportError:
            raise HTTPException(501, "copilot not available (P09 not installed)") from None
        before = len(store.scenarios)
        result = run_agent(payload.get("prompt", ""), state)
        assert len(store.scenarios) == before  # the loop must stay read-only
        return result.model_dump()

    @app.post("/copilot/confirm", response_model=CopilotConfirmResult)
    def copilot_confirm(payload: CopilotConfirm):
        """Apply a previewed tool call → create scenario → run → compare → explain.

        The copilot never mutates the sim directly; this is the explicit
        user-confirmed apply step. Auto-runs so the planner sees results at once.
        """
        try:
            from ..copilot.explain import explain_compare
        except ImportError:
            raise HTTPException(501, "copilot not available (P09 not installed)") from None

        interventions = [iv.to_op() for iv in payload.interventions]
        if not interventions:
            raise HTTPException(422, "no interventions to apply")
        _validate_edges(interventions)

        sc = store.create({"name": payload.name, "interventions": interventions})
        sid = sc["id"]
        result = store.run(sid, payload.run.model_dump())
        diff = store.compare(sid)
        delta = diff.get("summary_delta", {})
        edges = diff.get("most_impacted_edges", [])
        return CopilotConfirmResult(
            scenario_id=sid,
            summary=result["summary"],
            summary_delta=delta,
            most_impacted_edges=edges,
            explanation=explain_compare(delta, top_edges=edges),
        )

    @app.post("/optimize")
    def optimize(payload: dict):
        try:
            from ..optimizer.heuristic import propose
        except ImportError:
            raise HTTPException(501, "optimizer not available (P10 not installed)") from None
        return propose(state, payload)

    # ---- transit overlay (P08) ----------------------------------------- #
    # Prefer cached **real** GTFS feeds (data/transit/{agency}_{date}.json, baked
    # by transit.gtfs_reader) when present; else the hand-authored demo set so
    # the overlay always renders.
    @app.get("/transit/routes")
    def transit_routes(agencies: str = "ttc"):
        from ..transit.routes import demo_routes

        wanted = {a.strip() for a in agencies.split(",") if a.strip()}
        routes = []
        for agency in sorted(wanted):
            feed = _load_real_feed(agency, date="latest")
            if feed:
                routes.extend(feed.get("routes", []))
        if not routes:
            routes = [r for r in demo_routes() if r["agency"] in wanted]
        return {"routes": routes}

    @app.get("/transit/trajectories")
    def transit_trajectories(date: str = "2026-06-12", agencies: str = "ttc"):
        from ..transit.routes import demo_trajectories

        wanted = {a.strip() for a in agencies.split(",") if a.strip()}
        trajs = []
        for agency in sorted(wanted):
            feed = _load_real_feed(agency, date=date)
            if feed:
                trajs.extend(feed.get("trajectories", []))
        if not trajs:
            trajs = [t for t in demo_trajectories() if t["agency"] in wanted]
        return {"date": date, "trajectories": trajs}

    # ---- FIFA WC demo: real engine runs on the real graph (P12) --------- #
    app.state.demo_cache = {}
    app.state.demo_locks = {
        scenario: threading.Lock() for scenario in ("baseline", "wc_surge", "wc_fix")
    }

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

    def _get_demo(scenario: str) -> dict:
        cached = app.state.demo_cache.get(scenario)
        if cached is not None:
            return cached
        # The startup warm-up and an early browser request may arrive together.
        # Compute each scenario once and let the second caller reuse the result.
        with app.state.demo_locks[scenario]:
            cached = app.state.demo_cache.get(scenario)
            if cached is None:
                cached = _compute_demo(scenario)
                app.state.demo_cache[scenario] = cached
            return cached

    @app.get("/demo/run")
    def demo_run(scenario: str = "baseline"):
        """Run baseline | wc_surge | wc_fix on the real graph; return per-edge records.

        Deterministic → cached. Records are ``[edge_idx, load, speed, pressure,
        closure]`` aligned to the ``/edges`` index, so the frontend recolors the
        real road network with live engine pressures.
        """
        if scenario not in ("baseline", "wc_surge", "wc_fix"):
            raise HTTPException(422, f"unknown demo scenario: {scenario!r}")
        return _get_demo(scenario)

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
