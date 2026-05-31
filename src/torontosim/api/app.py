"""FastAPI app factory wiring REST + WebSocket over the simulation (P06).

``create_app(state=...)`` lets tests inject a small graph; the production server
(`serve()`) loads the full Toronto graph + baseline OD once at startup.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

from ..datapipeline.tmc_baseline import build_baseline_model
from .daycompute import DayCompute, base_time_context, hour_order
from .encoding import pack_day_frame, pack_frame
from .jobs import JobManager
from .prewarm import PrewarmManager
from .recompute import recompute_scenario
from .schemas import (
    CompareResult,
    CopilotConfirm,
    CopilotConfirmResult,
    Intervention,
    RetimeRequest,
    RunRequest,
    RunResult,
    Scenario,
    ScenarioCreate,
    ScenarioPatch,
    SimulateRequest,
    SimulateResult,
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
        # Warm the GNN baseline (the no-edit "usual congestion" view): load the
        # 175 MB tensor bundle once and precompute the default day's 24-frame blob so
        # the first /baseline/predicted is instant. Best-effort + non-blocking; once
        # the bundle is warm any day/month is ~0.3s. (Edits use the equilibrium
        # day-stream — a separate path.)
        def warm():
            from . import gnn_baseline as gb

            try:
                gb.warm_default(state)
            except Exception:  # noqa: BLE001 — warmup is best-effort
                pass
            # Pre-warm the copilot's compare baselines so congestion queries,
            # /confirm comparisons and the agent's scratch sims don't cold-compute
            # a full ~80k-edge baseline on first use (paid once here, in the bg).
            for warmer in (state.baseline, state.blast_baseline):
                try:
                    warmer()
                except Exception:  # noqa: BLE001 — warmup is best-effort
                    pass
            # Pre-load the copilot model so the first ask dodges the cold load.
            try:
                from ..copilot import ollama_client, planner

                if planner._live_enabled() and ollama_client.available():
                    ollama_client.warmup()
            except Exception:  # noqa: BLE001 — warmup is best-effort
                pass

        # Keep-alive: the model's keep_alive is 10m, so re-ping every 5m to keep it
        # resident — kills the ~8-11s cold reload mid-session. Cancellable on shutdown.
        stop_keepalive = threading.Event()

        def keepalive():
            from ..copilot import ollama_client, planner

            while not stop_keepalive.wait(300):  # 5 min, comfortably inside keep_alive=10m
                try:
                    if planner._live_enabled() and ollama_client.available(timeout=3.0):
                        ollama_client.warmup(timeout=30.0)
                except Exception:  # noqa: BLE001 — best-effort; never crash the loop
                    pass

        threading.Thread(target=warm, daemon=True).start()
        threading.Thread(target=keepalive, daemon=True).start()
        try:
            yield
        finally:
            stop_keepalive.set()

    app = FastAPI(title="TorontoSim API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Vite dev server; auth is explicitly out of scope.
        allow_methods=["*"],
        allow_headers=["*"],
    )
    store = ScenarioStore(state, snapshot_dir=snapshot_dir)
    jobs = JobManager()
    prewarm = PrewarmManager(state)
    daycompute = DayCompute(state)
    app.state.store = store
    app.state.jobs = jobs
    app.state.prewarm = prewarm
    app.state.daycompute = daycompute

    # Measured-baseline index (built once, lazily). See /baseline/day below.
    _baseline = {"model": None}
    _baseline_lock = threading.Lock()

    def build_baseline_now():
        with _baseline_lock:
            if _baseline["model"] is None:
                _baseline["model"] = build_baseline_model(state.graph, state.edge_index)
            return _baseline["model"]

    app.state.build_baseline = build_baseline_now

    # ---- health / debug ------------------------------------------------- #
    @app.get("/healthz")
    def healthz():
        return {
            "status": "ok",
            "edges": len(state.edge_ids),
            "scenarios": len(store.scenarios),
            "baseline_ready": state.baseline_ready,  # gates the copilot UI until warm
        }

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
        from .restricted_roads import classify_edge

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
            restricted = classify_edge(eid)
            if restricted:
                meta = {**meta, "restricted": restricted}
            out.append({"idx": i, "edge_id": eid, **meta})
        return {"edges": out}

    @app.get("/baseline/day")
    def baseline_day(dow: int = 2, month: int = 6):
        """Measured 24-hour baseline for a month + day-of-week, from raw TMC (no ML).

        Returns 24 concatenated day-frames (``pack_day_frame(hour, epoch=0, recs)``);
        the client walks them and ingests each into its hourly buffer. Hours/days/
        months with no survey data return empty frames (free-flow). ``dow`` is
        Monday=0; ``month`` is 1..12. Coverage varies by month (honest, no fallback).
        """
        if dow < 0 or dow > 6:
            raise HTTPException(400, "dow must be 0..6 (Monday=0)")
        if month < 1 or month > 12:
            raise HTTPException(400, "month must be 1..12")
        model = build_baseline_now()
        day = model.day(month, dow)
        body = b"".join(pack_day_frame(h, 0, recs) for h, recs in enumerate(day))
        return Response(content=body, media_type="application/octet-stream")

    @app.get("/baseline/predicted")
    def baseline_predicted(dow: int = 2, month: int = 6):
        """Full-coverage *predicted* baseline day (GNN, no interventions): 24 frames.

        The GraphSAGE model predicts a per-edge pressure for EVERY edge directly, so
        this is the no-edit "usual congestion" view — same blob shape as
        ``/baseline/day`` (the client reuses ``ingestBaselineDay``). Computed on
        demand (~0.3s once the bundle is warm) and cached; the default day is warmed
        and persisted at startup. ``dow`` is Monday=0; ``month`` is 1..12. (Edits use
        the equilibrium ``/day/stream`` so closures/surges reroute.)
        """
        if dow < 0 or dow > 6:
            raise HTTPException(400, "dow must be 0..6 (Monday=0)")
        if month < 1 or month > 12:
            raise HTTPException(400, "month must be 1..12")
        from . import gnn_baseline as gb

        return Response(
            content=gb.day_blob(state, dow, month), media_type="application/octet-stream"
        )

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

    # ---- param-driven simulate (front-end wiring) ----------------------- #
    @app.post("/simulate", response_model=SimulateResult)
    def simulate(req: SimulateRequest):
        """Predict demand for ``time_context`` with the chosen model, apply the
        user's modifications (closures + demand surges), simulate, and return
        per-edge records. Pure function of the inputs → cached (see recompute).
        """
        ops = [iv.to_op() for iv in req.interventions]
        _validate_edges(ops)  # demand_change is exempt (not an edge op)
        res = recompute_scenario(
            state,
            model_kind=req.demand_model,
            time_context=req.time_context,
            interventions=ops,
            iterations=req.iterations,
        )
        return SimulateResult(**res)

    @app.post("/simulate/prewarm")
    def simulate_prewarm(req: SimulateRequest):
        """Speculatively warm the cache for a *pending* param state + likely-next
        states (adjacent hours, the other model) so a later Run is instant.
        Non-blocking; stale queued warms are cancelled. See api/prewarm.py.
        """
        ops = [iv.to_op() for iv in req.interventions]
        _validate_edges(ops)
        queued = prewarm.request(
            model_kind=req.demand_model,
            time_context=req.time_context,
            interventions=ops,
            iterations=req.iterations,
        )
        return {"queued": queued}

    # ---- day time-series stream (free playback) ------------------------- #
    _GRAPH_EDGE_OPS = ("close_edge", "reopen_edge", "remove_edge", "change_capacity")

    @app.websocket("/day/stream")
    async def day_stream(ws: WebSocket):
        """Stream a whole day as 24 hourly binary frames so the front-end can play
        a view back without ever recomputing on a scrub.

        The client sends one JSON spec
        ``{demand_model, time_context{day_of_week,month,...}, interventions,
        current_hour, epoch, iterations}`` then receives, per hour: a tagged binary
        frame (``pack_day_frame``) as it completes — current hour first. A view
        change = the client opening a new socket; this handler cancels its
        not-yet-started hours and returns. ``epoch`` tags every frame so the client
        can drop any straggler from a superseded view.
        """
        await ws.accept()
        try:
            spec = await ws.receive_json()
            model_kind = str(spec.get("demand_model", "xgboost"))
            base_tc = base_time_context(spec.get("time_context", {}))
            raw_iv = spec.get("interventions", []) or []
            # Drop graph ops referencing unknown edges (the per-hour pipeline would
            # otherwise raise); demand_change + valid edge ops pass through.
            interventions = [
                iv
                for iv in raw_iv
                if not (
                    iv.get("op") in _GRAPH_EDGE_OPS and iv.get("edge_id") not in state.edge_index
                )
            ]
            tc_hour = (spec.get("time_context") or {}).get("hour", 8)
            current_hour = int(spec.get("current_hour", tc_hour) or 0)
            epoch = int(spec.get("epoch", 0) or 0)
            iterations = int(spec.get("iterations", 4) or 4)
        except Exception:  # noqa: BLE001 — malformed spec or client vanished mid-handshake
            # The client may have already closed (it supersedes by reconnecting);
            # closing an already-closed socket raises, so guard it.
            try:
                await ws.close(code=4400)
            except Exception:  # noqa: BLE001
                pass
            return

        dc = app.state.daycompute
        loop = asyncio.get_running_loop()
        futures = [
            loop.run_in_executor(
                dc.pool, dc.compute_hour, model_kind, base_tc, interventions, hour, iterations
            )
            for hour in hour_order(current_hour)
        ]

        sent_meta = False
        try:
            for fut in asyncio.as_completed(futures):
                try:
                    hour, res = await fut
                except Exception:  # noqa: BLE001 — a single hour failed; skip it
                    continue
                if not sent_meta:
                    await ws.send_json(
                        {
                            "type": "meta",
                            "total": 24,
                            "epoch": epoch,
                            "model_actual": res.get("model_actual", ""),
                        }
                    )
                    sent_meta = True
                await ws.send_bytes(pack_day_frame(hour, epoch, res["records"]))
            try:
                await ws.send_json({"type": "done", "epoch": epoch})
            except Exception:  # noqa: BLE001
                pass
        except (WebSocketDisconnect, RuntimeError):
            # Client opened a new view (or the socket dropped): stop streaming.
            pass
        finally:
            # Cancel queued-but-not-started hours; in-flight ones finish into the
            # cache (CPU-bound, can't be interrupted) and may help on return.
            for fut in futures:
                fut.cancel()

    # ---- copilot / optimizer placeholders (P09/P10 fill in) ------------- #
    @app.post("/copilot/plan")
    def copilot_plan(payload: dict):
        try:
            from ..copilot.planner import plan_intervention
        except ImportError:
            raise HTTPException(501, "copilot not available (P09 not installed)") from None
        # An optional pre-computed classification ({"intent": ...}) drives dispatch
        # deterministically (used by /route and by tests/debug to skip the model).
        return plan_intervention(
            payload.get("prompt", ""), state, classification=payload.get("classification")
        )

    @app.get("/copilot/suggestions")
    def copilot_suggestions():
        """Dynamic suggestion chips grounded in the real graph (no hardcoded prompts)."""
        try:
            from ..copilot.planner import suggested_prompts
        except ImportError:
            raise HTTPException(501, "copilot not available (P09 not installed)") from None
        return {"prompts": suggested_prompts(state)}

    @app.post("/copilot/route")
    def copilot_route(payload: dict):
        """Single intent classifier → routing decision (replaces the frontend regex
        + backend keyword cascade). For plan-mode intents the dispatched ToolCall is
        returned inline (no second hop); chat/agent modes tell the frontend which
        streaming / loop endpoint to call. The classification is reused for dispatch
        so the model classifies exactly once."""
        try:
            from ..copilot.classify import classify
            from ..copilot.planner import plan_intervention
        except ImportError:
            raise HTTPException(501, "copilot not available (P09 not installed)") from None
        prompt = payload.get("prompt", "")
        # Optional recent-conversation context so referential asks ("the worst
        # road", "that road", "it") resolve to a concrete road in classification.
        cls = classify(prompt, history=payload.get("history", ""))
        out: dict = {"mode": cls.mode, "intent": cls.intent}
        if cls.mode == "plan":
            out["result"] = plan_intervention(prompt, state, classification=cls)
        return out

    @app.post("/copilot/followups")
    def copilot_followups(payload: dict):
        """Context-aware follow-up prompt chips for the frontend (intent-keyed,
        deterministic, no model call)."""
        try:
            from ..copilot.followups import followups
        except ImportError:
            raise HTTPException(501, "copilot not available (P09 not installed)") from None
        return {
            "prompts": followups(
                payload.get("prompt", ""),
                payload.get("reply", ""),
                payload.get("intent", ""),
            )
        }

    @app.post("/assess")
    def assess_closure(payload: dict):
        """SSOT warn-don't-block assessment — shared by clickops + copilot. Returns
        severity-coded warnings for the proposed interventions; never refuses."""
        try:
            from ..copilot.assess import assess
        except ImportError:
            raise HTTPException(501, "copilot not available (P09 not installed)") from None
        ivs = [Intervention.model_validate(iv) for iv in payload.get("interventions", [])]
        warnings = assess(ivs, state, prompt=payload.get("prompt", ""))
        return {"warnings": [w.model_dump() for w in warnings]}

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
        import os

        from ..demo import wc_surge

        state.ensure_od()  # legacy demo path: build the shared baseline OD on first use
        res = wc_surge.run_scenario(
            scenario,
            graph=state.graph,
            baseline_od=state.od_matrix,
            engine="kpath",
            backend=os.environ.get("TS_BACKEND", "cpu"),
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

    retime_lock = threading.Lock()

    @app.post("/baseline/retime")
    def baseline_retime(req: RetimeRequest):
        """Rebuild the baseline demand at a new time-of-day / date.

        Time-of-day is encoded in the OD matrix (commute direction + rush factor),
        so changing the hour/day re-derives demand from the model and re-runs the
        baseline — not a cheap per-run param. Returns the repaint records for the
        new baseline. Heavy (model predict + gravity + sim); the UI gates it behind
        an explicit 'apply' with a loading state, not per-scrub. A non-blocking lock
        rejects a second retime while one is running (the CPU sim would otherwise
        stack and freeze the server for minutes).
        """
        if not retime_lock.acquire(blocking=False):
            raise HTTPException(409, "a baseline retime is already in progress")
        try:
            tc = {
                k: v
                for k, v in {
                    "minute": req.minute,
                    "day_of_year": req.day_of_year,
                    "weather": req.weather,
                }.items()
                if v is not None
            }
            # Carry forward the current values for whatever wasn't supplied.
            merged = {**state.time_context, **tc}
            state.retime(merged)
            app.state.demo_cache = {}  # demo records were computed from the old OD
            res = _get_demo("baseline")
            return {
                "time_context": state.time_context,
                "summary": res["summary"],
                "records": res["records"],
            }
        finally:
            retime_lock.release()

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
    import os

    # Belt-and-suspenders for scripts/run_api.sh's BLAS pinning: only takes
    # effect if serve() is the first thing to import numpy in this process
    # (env must be set before the numpy import). setdefault → the shell wins.
    for _var in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ.setdefault(_var, "1")

    import uvicorn

    from ._bootstrap import load_default_state

    app = create_app(load_default_state())
    uvicorn.run(app, host=host, port=port)
