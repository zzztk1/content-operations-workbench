from __future__ import annotations

from contextlib import asynccontextmanager
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.concurrency import run_in_threadpool

from langgraph_v2 import LangGraphMediaAgentEngine
from langgraph_v2.observability import get_struct_logger
from langgraph_v2.platform_rules import list_platform_rules
from langgraph_v2.settings import V2Settings


class WorkflowRunRequest(BaseModel):
    brief: str = Field(min_length=1)
    platform: str = "小红书"
    style: str = "种草推荐"
    run_mode: Optional[str] = Field(
        default=None,
        description="auto: full run; guided: pause after research for topic selection.",
    )
    export_formats: Optional[List[str]] = Field(
        default=None,
        description="Subset of json, md, txt, html (aliases: markdown, text). Default json+md.",
    )
    approval_decision: str = "approve"
    approval_note: str = ""
    reviewer_threshold: int = 21
    max_revisions: int = 2
    run_id: Optional[str] = None
    image_mock: Optional[bool] = None
    cover_candidate_count: Optional[int] = Field(
        default=None,
        ge=1,
        le=4,
        description="Generate 1-4 cover candidates in parallel; the first one becomes the primary image asset.",
    )
    vision_review_mock: Optional[bool] = Field(
        default=None,
        description="Override VISION_REVIEW_MOCK for this run (true=local mock, false=call vision model).",
    )


class WorkflowContinueRequest(BaseModel):
    """Continue a guided run after topic selection.

    Prefer ``run_id`` (loads checkpoint server-side). ``state`` is accepted for
    clients that already hold a snapshot (non-breaking).
    """

    run_id: Optional[str] = Field(default=None, min_length=1)
    state: Optional[Dict[str, Any]] = None
    selected_topic_index: int = Field(ge=0, le=10)
    approval_decision: str = "approve"
    approval_note: str = ""
    reviewer_threshold: Optional[int] = None
    max_revisions: Optional[int] = None
    image_mock: Optional[bool] = None
    cover_candidate_count: Optional[int] = Field(default=None, ge=1, le=4)
    vision_review_mock: Optional[bool] = None
    export_formats: Optional[List[str]] = None

    @model_validator(mode="after")
    def _require_run_or_state(self) -> "WorkflowContinueRequest":
        if not self.run_id and self.state is None:
            raise ValueError("Provide run_id (recommended) or state")
        return self


class WorkflowRewriteRequest(BaseModel):
    run_id: str = Field(min_length=1)
    instruction: str = Field(default="请根据当前内容重新生成一版。")
    approval_decision: str = "approve"
    approval_note: str = "rewrite"
    reviewer_threshold: Optional[int] = None
    max_revisions: Optional[int] = None
    image_mock: Optional[bool] = None
    cover_candidate_count: Optional[int] = Field(default=None, ge=1, le=4)
    vision_review_mock: Optional[bool] = None
    export_formats: Optional[List[str]] = None


class WorkflowNodeRerunRequest(BaseModel):
    instruction: str = Field(default="")
    approval_decision: str = "approve"
    approval_note: str = "node-rerun"
    reviewer_threshold: Optional[int] = None
    max_revisions: Optional[int] = None
    image_mock: Optional[bool] = None
    cover_candidate_count: Optional[int] = Field(default=None, ge=1, le=4)
    vision_review_mock: Optional[bool] = None
    export_formats: Optional[List[str]] = None


class PublishOverridesRequest(BaseModel):
    image_assets: Optional[List[Dict[str, Any]]] = None
    cover_asset: Optional[Dict[str, Any]] = None


def _short_text(value: Any, limit: int = 220) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[:limit]}..."


def _load_exported_run(outputs_dir: Path, run_id: str) -> Optional[Dict[str, Any]]:
    safe_run_id = Path(run_id).name
    if safe_run_id != run_id or not safe_run_id:
        return None
    path = outputs_dir / f"{safe_run_id}.v2.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    payload.setdefault("run_id", safe_run_id)
    payload.setdefault("status", "completed")
    return {
        "run_id": safe_run_id,
        "state": payload,
        "status": payload.get("status", "completed"),
        "source": "exported_json",
    }


def _node_detail_payload(state: Dict[str, Any]) -> Dict[str, Any]:
    trace = list(state.get("trace") or [])
    events = list(state.get("events") or [])
    errors = list(state.get("errors") or [])
    metrics_payload = state.get("metrics") or {}
    node_metrics = list(metrics_payload.get("node_metrics") or [])

    events_by_node: Dict[str, List[Dict[str, Any]]] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        node = str(event.get("node") or "")
        if node:
            events_by_node.setdefault(node, []).append(event)

    errors_by_node: Dict[str, List[Dict[str, Any]]] = {}
    for error in errors:
        if not isinstance(error, dict):
            continue
        node = str(error.get("node") or "")
        if node:
            errors_by_node.setdefault(node, []).append(error)

    metrics_by_node: Dict[str, Dict[str, Any]] = {}
    for metric in node_metrics:
        if not isinstance(metric, dict):
            continue
        node = str(metric.get("node") or "")
        if node:
            metrics_by_node[node] = metric

    known_nodes = list(dict.fromkeys(trace + list(metrics_by_node.keys()) + list(events_by_node.keys())))
    details = []
    for index, node in enumerate(known_nodes):
        metric = metrics_by_node.get(node, {})
        node_errors = errors_by_node.get(node, [])
        node_events = events_by_node.get(node, [])
        last_event = node_events[-1] if node_events else {}
        event_payload = last_event.get("payload") if isinstance(last_event, dict) else {}
        details.append(
            {
                "node": node,
                "index": index,
                "status": "error" if node_errors or metric.get("error") else "completed",
                "phase": last_event.get("phase", "completed") if isinstance(last_event, dict) else "completed",
                "latency_ms": metric.get("latency_ms"),
                "prompt_tokens": metric.get("prompt_tokens", 0),
                "completion_tokens": metric.get("completion_tokens", 0),
                "total_tokens": metric.get("total_tokens", 0),
                "error": metric.get("error") or (node_errors[-1].get("error") if node_errors else ""),
                "input_summary": _short_text(
                    {
                        "brief": state.get("brief"),
                        "platform": state.get("platform"),
                        "style": state.get("style"),
                        "selected_topic": state.get("selected_topic"),
                    }
                ),
                "output_summary": _short_text(event_payload or _node_output_fallback(state, node)),
                "events": node_events,
                "raw_metric": metric,
            }
        )

    return {
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "nodes": details,
        "metrics_summary": metrics_payload.get("totals", {}),
        "errors": errors,
    }


def _node_output_fallback(state: Dict[str, Any], node: str) -> Any:
    if node == "research_topic":
        return state.get("research")
    if node == "write_draft":
        return state.get("draft")
    if node == "adapt_platform":
        return state.get("adapted")
    if node in {"plan_cover", "generate_cover"}:
        return state.get("image_plans") or state.get("image_assets") or state.get("image_asset")
    if node == "review_structured":
        return state.get("review")
    if node == "export":
        return state.get("publish_package") or state.get("content_package")
    return {}


def _health_payload(app: FastAPI) -> Dict[str, Any]:
    engine: LangGraphMediaAgentEngine = app.state.engine
    settings: V2Settings = app.state.settings
    payload: Dict[str, Any] = {
        "status": "ok",
        "graph_version": engine.layout.version,
        "llm_mock": settings.llm_mock,
        "llm_api_base": settings.llm_api_base,
        "llm_model": settings.llm_model,
        "llm_provider_route": "step_plan" if engine.is_step_plan else "openai_compatible",
        "image_provider_route": "stepfun_images" if not settings.image_mock else "mock",
        "image_api_base": settings.image_api_base,
        "image_model": settings.image_model,
        "image_mock": settings.image_mock,
        "image_client_available": bool(engine.image_client),
        "image_runtime_override_supported": bool(engine.image_client),
        "vision_api_base": settings.vision_api_base,
        "vision_model": settings.vision_model,
        "vision_review_mock": settings.vision_review_mock,
        "vision_client_available": bool(engine.vision_client),
        "enable_json_mode_effective": settings.enable_json_mode and not engine.is_step_plan,
        "langsmith_tracing": settings.langsmith_tracing,
        "langsmith_tracing_v2": settings.langsmith_tracing_v2,
        "langsmith_endpoint": settings.langsmith_endpoint,
        "langsmith_workspace_id": settings.langsmith_workspace_id or None,
        "langsmith_project": settings.langsmith_project,
        "langsmith_configured": bool(os.getenv("LANGSMITH_API_KEY", "")),
        "checkpointer_mock": settings.checkpointer_mock,
        "checkpoint_backend": settings.checkpoint_backend,
        "rate_limit_per_minute": settings.rate_limit_per_minute,
        "shutting_down": app.state.shutting_down,
        "checks": {
            "llm_configured": bool(
                settings.llm_mock
                or (settings.llm_api_key and settings.llm_api_base and settings.llm_model)
            ),
            "image_configured": bool(
                settings.image_mock
                or (settings.image_api_key and settings.image_api_base and settings.image_model)
            ),
            "vision_configured": bool(
                settings.vision_review_mock
                or (
                    settings.vision_api_key
                    and settings.vision_api_base
                    and settings.vision_model
                )
            ),
            "postgres_connectivity": None,
        },
        "llm_circuit_breaker": engine.circuit_state(),
    }

    if settings.checkpoint_backend == "postgres" and not settings.checkpointer_mock:
        try:
            with psycopg.connect(settings.postgres_dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute("select 1;")
                    cur.fetchone()
            payload["checks"]["postgres_connectivity"] = True
        except Exception as exc:
            payload["status"] = "degraded"
            payload["checks"]["postgres_connectivity"] = False
            payload["postgres_error"] = str(exc)
    return payload


def _normalize_run_mode(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    v = raw.strip().lower()
    if v not in ("auto", "guided"):
        raise HTTPException(
            status_code=422,
            detail="run_mode must be 'auto' or 'guided' when provided",
        )
    return v


def create_app() -> FastAPI:
    settings = V2Settings.from_env()
    limiter = Limiter(key_func=get_remote_address, default_limits=[])
    limit_rule = (
        f"{settings.rate_limit_per_minute}/minute"
        if settings.enable_slowapi
        else "1000000/minute"
    )
    log_path = Path(__file__).resolve().parent.parent / "logs" / "api_v2.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    demo_path = Path(__file__).resolve().parent / "demo_v2.html"
    frontend_dist_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    frontend_assets_dir = frontend_dist_dir / "assets"
    frontend_index_path = frontend_dist_dir / "index.html"
    frontend_favicon_path = frontend_dist_dir / "favicon.svg"
    frontend_icons_path = frontend_dist_dir / "icons.svg"
    logger = get_struct_logger("api_v2", str(log_path))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.shutting_down = False
        app.state.engine = LangGraphMediaAgentEngine(settings=settings)
        app.state.engine.set_cancel_checker(
            lambda run_id: run_id in getattr(app.state, "cancelled_runs", set())
        )
        app.state.log_path = log_path
        app.state.logger = logger
        try:
            yield
        finally:
            app.state.shutting_down = True
            app.state.engine.close()

    app = FastAPI(
        title="Media Agent LangGraph v2 API",
        version="0.1.0",
        lifespan=lifespan,
    )
    outputs_dir = Path(__file__).resolve().parent.parent / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/outputs", StaticFiles(directory=str(outputs_dir)), name="outputs")
    if frontend_assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(frontend_assets_dir)), name="frontend-assets")
    app.state.limiter = limiter
    app.state.cancelled_runs = set()
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.middleware("http")
    async def request_context_guard(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started_at = time.perf_counter()
        if app.state.shutting_down and request.url.path != "/health":
            response = JSONResponse(
                status_code=503,
                content={"detail": "service is shutting down"},
            )
            response.headers["X-Request-ID"] = request_id
            app.state.logger.info(
                "http_request_completed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=503,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                detail="service is shutting down",
            )
            return response

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        app.state.logger.info(
            "http_request_completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
            llm_provider_route="step_plan" if app.state.engine.is_step_plan else "openai_compatible",
        )
        return response

    @app.get("/health")
    async def health(request: Request, response: Response) -> Dict[str, Any]:
        response.headers["X-Request-ID"] = request.state.request_id
        return _health_payload(app)

    @app.get("/", response_class=JSONResponse)
    async def root(request: Request, response: Response) -> Dict[str, Any]:
        response.headers["X-Request-ID"] = request.state.request_id
        return {
            "message": "media-agent v2 api is running",
            "docs": "/docs",
            "health": "/health",
            "demo": "/demo",
            "studio": "/studio",
            "limit_probe": "/v2/limit-probe",
            "workflow_capabilities": "/v2/workflow-capabilities",
            "platform_rules": "/v2/platform-rules",
            "runs": "/v2/runs",
            "admin_logs": "/v2/admin/logs",
            "v2_run": "/v2/run",
            "v2_run_stream": "/v2/run/stream",
            "v2_run_continue": "/v2/run/continue",
            "v2_runs": "/v2/runs/{run_id}",
        }

    def _frontend_response(request_id: str) -> HTMLResponse:
        if frontend_index_path.exists():
            html = frontend_index_path.read_text(encoding="utf-8")
            return HTMLResponse(content=html, headers={"X-Request-ID": request_id})
        if not demo_path.exists():
            raise HTTPException(status_code=500, detail="demo page not found")
        html = demo_path.read_text(encoding="utf-8")
        return HTMLResponse(content=html, headers={"X-Request-ID": request_id})

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon(request: Request) -> FileResponse:
        if frontend_favicon_path.exists():
            return FileResponse(frontend_favicon_path, media_type="image/svg+xml", headers={"X-Request-ID": request.state.request_id})
        raise HTTPException(status_code=404, detail="favicon not found")

    @app.get("/icons.svg", include_in_schema=False)
    async def icons(request: Request) -> FileResponse:
        if frontend_icons_path.exists():
            return FileResponse(frontend_icons_path, media_type="image/svg+xml", headers={"X-Request-ID": request.state.request_id})
        raise HTTPException(status_code=404, detail="icons not found")

    @app.get("/studio", response_class=HTMLResponse)
    async def studio(request: Request, response: Response) -> HTMLResponse:
        response.headers["X-Request-ID"] = request.state.request_id
        return _frontend_response(request.state.request_id)

    @app.get("/demo", response_class=HTMLResponse)
    async def demo(request: Request, response: Response) -> HTMLResponse:
        response.headers["X-Request-ID"] = request.state.request_id
        return _frontend_response(request.state.request_id)

    @app.get("/v2/limit-probe", response_class=JSONResponse)
    @limiter.limit(limit_rule)
    async def limit_probe(request: Request, response: Response) -> Dict[str, Any]:
        """Cheap endpoint for SlowAPI smoke tests (avoids long /v2/run work skewing per-minute windows)."""
        response.headers["X-Request-ID"] = request.state.request_id
        return {
            "ok": True,
            "endpoint": "/v2/limit-probe",
            "rate_limit_rule": limit_rule,
            "rate_limit_per_minute": settings.rate_limit_per_minute,
            "slowapi_enabled": settings.enable_slowapi,
        }

    @app.get("/v2/stream-probe")
    async def stream_probe(request: Request) -> StreamingResponse:
        """Cheap SSE sanity check for audits (no workflow / LLM / image work)."""
        if not settings.enable_sse:
            raise HTTPException(status_code=404, detail="sse disabled")

        def encode_sse(event_name: str, data: Dict[str, Any]) -> str:
            return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        def event_body():
            yield encode_sse("start", {"ok": True, "endpoint": "/v2/stream-probe"})
            yield encode_sse("final", {"ok": True, "endpoint": "/v2/stream-probe"})

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request.state.request_id,
        }
        return StreamingResponse(
            event_body(),
            media_type="text/event-stream",
            headers=headers,
        )

    @app.get("/v2/workflow-capabilities", response_class=JSONResponse)
    async def workflow_capabilities(request: Request, response: Response) -> Dict[str, Any]:
        """Static capability map for demo and integrators (no secrets)."""
        response.headers["X-Request-ID"] = request.state.request_id
        return {
            "run_modes": {
                "auto": {"supported": True, "description": "Full graph to export in one request."},
                "guided": {
                    "supported": True,
                    "description": "Pauses after research; use POST /v2/run/continue with run_id.",
                },
            },
            "export_formats": {
                "json": {"supported": True, "file_suffix": ".v2.json"},
                "md": {"supported": True, "aliases": ["markdown"], "file_suffix": ".v2.md"},
                "txt": {"supported": True, "aliases": ["text"], "file_suffix": ".v2.txt"},
                "html": {"supported": True, "file_suffix": ".v2.html"},
                "docx": {"supported": False, "note": "reserved"},
                "pdf": {"supported": False, "note": "reserved"},
            },
            "endpoints": {
                "run": "POST /v2/run",
                "run_stream": "POST /v2/run/stream",
                "run_continue": "POST /v2/run/continue",
                "get_run": "GET /v2/runs/{run_id}",
                "list_runs": "GET /v2/runs",
                "stop_run": "POST /v2/runs/{run_id}/stop",
                "rewrite_run": "POST /v2/run/rewrite",
                "node_details": "GET /v2/runs/{run_id}/nodes",
                "node_rerun": "POST /v2/runs/{run_id}/nodes/{node}/rerun",
                "platform_rules": "GET /v2/platform-rules",
                "admin_logs": "GET /v2/admin/logs",
            },
            "platform_rules": list_platform_rules(),
        }

    @app.get("/v2/platform-rules", response_class=JSONResponse)
    async def platform_rules(request: Request, response: Response) -> Dict[str, Any]:
        response.headers["X-Request-ID"] = request.state.request_id
        return {"platforms": list_platform_rules()}

    @app.get("/v2/runs", response_class=JSONResponse)
    async def list_runs(request: Request, response: Response, limit: int = 20) -> Dict[str, Any]:
        response.headers["X-Request-ID"] = request.state.request_id
        safe_limit = max(1, min(100, int(limit or 20)))
        items: List[Dict[str, Any]] = []
        for path in sorted(outputs_dir.glob("*.v2.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if len(items) >= safe_limit:
                break
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            items.append(
                {
                    "run_id": payload.get("run_id") or path.name.replace(".v2.json", ""),
                    "request_id": payload.get("request_id", ""),
                    "title": payload.get("title", ""),
                    "platform": payload.get("platform", ""),
                    "style": payload.get("style", ""),
                    "status": "completed",
                    "created_at": payload.get("created_at", ""),
                    "json_path": str(path),
                    "image_count": len(payload.get("image_assets") or []),
                    "publish_ready": bool(payload.get("publish_package")),
                }
            )
        return {"items": items, "count": len(items)}

    @app.get("/v2/admin/logs", response_class=JSONResponse)
    async def admin_logs(request: Request, response: Response, limit: int = 80) -> Dict[str, Any]:
        response.headers["X-Request-ID"] = request.state.request_id
        safe_limit = max(1, min(200, int(limit or 80)))
        entries: List[Dict[str, Any]] = []
        for log_file in [log_path, Path(__file__).resolve().parent.parent / "logs" / "engine_v2.jsonl"]:
            if not log_file.exists():
                continue
            lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()[-safe_limit:]
            for line in lines:
                try:
                    parsed = json.loads(line)
                except Exception:
                    parsed = {"message": line[:500]}
                parsed["_source"] = log_file.name
                entries.append(parsed)
        entries = entries[-safe_limit:]
        return {"items": entries, "count": len(entries)}

    @app.post("/v2/run")
    @limiter.limit(limit_rule)
    async def run_workflow(request: Request, payload: WorkflowRunRequest, response: Response) -> Dict[str, Any]:
        engine: LangGraphMediaAgentEngine = app.state.engine
        run_id = payload.run_id or uuid.uuid4().hex[:12]
        app.state.cancelled_runs.discard(run_id)
        runtime_overrides: Dict[str, Any] = {"image_mock": payload.image_mock}
        if payload.cover_candidate_count is not None:
            runtime_overrides["cover_candidate_count"] = payload.cover_candidate_count
        if payload.vision_review_mock is not None:
            runtime_overrides["vision_review_mock"] = payload.vision_review_mock
        rm = _normalize_run_mode(payload.run_mode)
        if rm is not None:
            runtime_overrides["run_mode"] = rm
        if payload.export_formats is not None:
            runtime_overrides["export_formats"] = payload.export_formats
        result = await run_in_threadpool(
            engine.run_workflow,
            payload.brief,
            payload.platform,
            payload.style,
            payload.approval_decision,
            payload.approval_note,
            payload.reviewer_threshold,
            payload.max_revisions,
            run_id,
            run_id,
            request.state.request_id,
            runtime_overrides,
        )
        app.state.cancelled_runs.discard(run_id)
        response.headers["X-Request-ID"] = request.state.request_id
        app.state.logger.info(
            "workflow_run_completed",
            request_id=request.state.request_id,
            run_id=result.get("run_id"),
            status=result.get("state", {}).get("status"),
        )
        return result

    @app.post("/v2/run/stream")
    @limiter.limit(limit_rule)
    async def run_workflow_stream(request: Request, payload: WorkflowRunRequest) -> StreamingResponse:
        if not settings.enable_sse:
            raise HTTPException(status_code=404, detail="sse disabled")
        engine: LangGraphMediaAgentEngine = app.state.engine
        run_id = payload.run_id or uuid.uuid4().hex[:12]
        app.state.cancelled_runs.discard(run_id)

        def encode_sse(event_name: str, data: Dict[str, Any]) -> str:
            return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        def event_stream():
            try:
                stream_overrides: Dict[str, Any] = {"image_mock": payload.image_mock}
                if payload.cover_candidate_count is not None:
                    stream_overrides["cover_candidate_count"] = payload.cover_candidate_count
                if payload.vision_review_mock is not None:
                    stream_overrides["vision_review_mock"] = payload.vision_review_mock
                rm = _normalize_run_mode(payload.run_mode)
                if rm is not None:
                    stream_overrides["run_mode"] = rm
                if payload.export_formats is not None:
                    stream_overrides["export_formats"] = payload.export_formats
                for event in engine.stream_workflow(
                    brief=payload.brief,
                    platform=payload.platform,
                    style=payload.style,
                    approval_decision=payload.approval_decision,
                    approval_note=payload.approval_note,
                    reviewer_threshold=payload.reviewer_threshold,
                    max_revisions=payload.max_revisions,
                    run_id=run_id,
                    thread_id=run_id,
                    request_id=request.state.request_id,
                    runtime_overrides=stream_overrides,
                ):
                    yield encode_sse(event["event"], event["data"])
            except Exception as exc:
                yield encode_sse("error", {"detail": str(exc)})

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request.state.request_id,
        }
        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers=headers,
        )

    @app.get("/v2/runs/{run_id}")
    async def get_run(run_id: str, request: Request, response: Response) -> Dict[str, Any]:
        engine: LangGraphMediaAgentEngine = app.state.engine
        result = await run_in_threadpool(engine.get_run, run_id, run_id)
        if not result:
            result = _load_exported_run(outputs_dir, run_id)
        if not result:
            raise HTTPException(status_code=404, detail="run not found")
        response.headers["X-Request-ID"] = request.state.request_id
        return result

    @app.get("/v2/runs/{run_id}/nodes", response_class=JSONResponse)
    async def get_run_nodes(run_id: str, request: Request, response: Response) -> Dict[str, Any]:
        engine: LangGraphMediaAgentEngine = app.state.engine
        result = await run_in_threadpool(engine.get_run, run_id, run_id)
        if not result:
            result = _load_exported_run(outputs_dir, run_id)
        if not result:
            raise HTTPException(status_code=404, detail="run not found")
        response.headers["X-Request-ID"] = request.state.request_id
        return _node_detail_payload(result["state"])

    @app.patch("/v2/runs/{run_id}/publish-overrides", response_class=JSONResponse)
    async def update_publish_overrides(
        run_id: str,
        payload: PublishOverridesRequest,
        request: Request,
        response: Response,
    ) -> Dict[str, Any]:
        engine: LangGraphMediaAgentEngine = app.state.engine
        result = await run_in_threadpool(
            engine.update_publish_overrides,
            run_id,
            payload.image_assets,
            payload.cover_asset,
        )
        if not result:
            raise HTTPException(status_code=404, detail="run not found")
        response.headers["X-Request-ID"] = request.state.request_id
        return result

    @app.post("/v2/runs/{run_id}/nodes/{node}/rerun")
    @limiter.limit(limit_rule)
    async def rerun_node(
        run_id: str,
        node: str,
        request: Request,
        payload: WorkflowNodeRerunRequest,
        response: Response,
    ) -> Dict[str, Any]:
        engine: LangGraphMediaAgentEngine = app.state.engine
        snap = await run_in_threadpool(engine.get_run, run_id, run_id)
        if not snap:
            raise HTTPException(status_code=404, detail="run not found")
        state = snap["state"]
        extra = payload.instruction.strip() or f"请重点重跑并改进节点：{node}"
        brief = (
            f"{state.get('brief', '')}\n\n节点重跑要求：{node}\n{extra}"
        ).strip()
        runtime_overrides: Dict[str, Any] = {
            "image_mock": payload.image_mock,
            "vision_review_mock": payload.vision_review_mock,
        }
        if payload.cover_candidate_count is not None:
            runtime_overrides["cover_candidate_count"] = payload.cover_candidate_count
        if payload.export_formats is not None:
            runtime_overrides["export_formats"] = payload.export_formats
        result = await run_in_threadpool(
            engine.run_workflow,
            brief,
            state.get("platform", "小红书"),
            state.get("style", "经验总结"),
            payload.approval_decision,
            payload.approval_note,
            payload.reviewer_threshold or int(state.get("reviewer_threshold", 21)),
            payload.max_revisions if payload.max_revisions is not None else int(state.get("max_revisions", 1)),
            f"{run_id}-{node}-rerun-{uuid.uuid4().hex[:4]}",
            None,
            request.state.request_id,
            runtime_overrides,
        )
        response.headers["X-Request-ID"] = request.state.request_id
        return result

    @app.post("/v2/run/continue")
    @limiter.limit(limit_rule)
    async def run_workflow_continue(
        request: Request, payload: WorkflowContinueRequest, response: Response
    ) -> Dict[str, Any]:
        engine: LangGraphMediaAgentEngine = app.state.engine
        cont_overrides: Dict[str, Any] = {}
        if payload.image_mock is not None:
            cont_overrides["image_mock"] = payload.image_mock
        if payload.cover_candidate_count is not None:
            cont_overrides["cover_candidate_count"] = payload.cover_candidate_count
        if payload.vision_review_mock is not None:
            cont_overrides["vision_review_mock"] = payload.vision_review_mock
        if payload.export_formats is not None:
            cont_overrides["export_formats"] = payload.export_formats
        base_state: Dict[str, Any]
        if payload.run_id:
            snap = await run_in_threadpool(engine.get_run, payload.run_id, payload.run_id)
            if not snap:
                raise HTTPException(status_code=404, detail="run not found")
            base_state = snap["state"]
        elif payload.state is not None:
            base_state = payload.state
        else:
            raise HTTPException(status_code=422, detail="Provide run_id or state")
        if base_state.get("status") != "awaiting_topic_selection":
            raise HTTPException(
                status_code=400,
                detail="Run is not awaiting topic selection; inspect GET /v2/runs/{run_id}",
            )
        try:
            result = await run_in_threadpool(
                engine.run_workflow_continue,
                base_state,
                payload.selected_topic_index,
                payload.approval_decision,
                payload.approval_note,
                payload.reviewer_threshold,
                payload.max_revisions,
                request.state.request_id,
                cont_overrides,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response.headers["X-Request-ID"] = request.state.request_id
        app.state.logger.info(
            "workflow_continue_completed",
            request_id=request.state.request_id,
            run_id=result.get("run_id"),
            status=result.get("state", {}).get("status"),
        )
        return result

    @app.post("/v2/runs/{run_id}/stop", response_class=JSONResponse)
    async def stop_run(run_id: str, request: Request, response: Response) -> Dict[str, Any]:
        app.state.cancelled_runs.add(run_id)
        response.headers["X-Request-ID"] = request.state.request_id
        return {
            "run_id": run_id,
            "status": "stop_requested",
            "note": "已请求停止；当前节点会尽量完成，后续节点会在边界处合作式取消。",
        }

    @app.post("/v2/run/rewrite")
    @limiter.limit(limit_rule)
    async def rewrite_run(
        request: Request, payload: WorkflowRewriteRequest, response: Response
    ) -> Dict[str, Any]:
        engine: LangGraphMediaAgentEngine = app.state.engine
        snap = await run_in_threadpool(engine.get_run, payload.run_id, payload.run_id)
        if not snap:
            raise HTTPException(status_code=404, detail="run not found")
        state = snap["state"]
        brief = (
            f"{state.get('brief', '')}\n\n重写要求：{payload.instruction.strip()}"
        ).strip()
        runtime_overrides: Dict[str, Any] = {
            "image_mock": payload.image_mock,
            "vision_review_mock": payload.vision_review_mock,
        }
        if payload.cover_candidate_count is not None:
            runtime_overrides["cover_candidate_count"] = payload.cover_candidate_count
        if payload.export_formats is not None:
            runtime_overrides["export_formats"] = payload.export_formats
        result = await run_in_threadpool(
            engine.run_workflow,
            brief,
            state.get("platform", "小红书"),
            state.get("style", "经验总结"),
            payload.approval_decision,
            payload.approval_note,
            payload.reviewer_threshold or int(state.get("reviewer_threshold", 21)),
            payload.max_revisions if payload.max_revisions is not None else int(state.get("max_revisions", 1)),
            f"{payload.run_id}-rewrite-{uuid.uuid4().hex[:4]}",
            None,
            request.state.request_id,
            runtime_overrides,
        )
        response.headers["X-Request-ID"] = request.state.request_id
        return result

    return app


app = create_app()
