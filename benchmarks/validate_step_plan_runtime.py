import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi.testclient import TestClient


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from api_v2 import create_app  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_sse_events(body: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    event_name = "message"
    data_lines: List[str] = []
    for line in body.splitlines():
        if line.startswith("event: "):
            event_name = line[len("event: ") :].strip()
            continue
        if line.startswith("data: "):
            data_lines.append(line[len("data: ") :])
            continue
        if not line.strip() and data_lines:
            raw_data = "\n".join(data_lines)
            try:
                parsed_data: Any = json.loads(raw_data)
            except json.JSONDecodeError:
                parsed_data = raw_data
            events.append({"event": event_name, "data": parsed_data})
            event_name = "message"
            data_lines = []
    if data_lines:
        raw_data = "\n".join(data_lines)
        try:
            parsed_data = json.loads(raw_data)
        except json.JSONDecodeError:
            parsed_data = raw_data
        events.append({"event": event_name, "data": parsed_data})
    return events


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    os.environ["PYTHONUTF8"] = "1"
    app = create_app()
    with TestClient(app) as client:
        health = client.get("/health")
        docs = client.get("/docs")
        run = client.post(
            "/v2/run",
            headers={"X-Request-ID": "step-plan-smoke-001"},
            json={
                "brief": "AI产品经理求职内容运营选题",
                "platform": "小红书",
                "style": "种草推荐",
            },
        )
        run_payload = run.json()
        run_detail = client.get(f"/v2/runs/{run_payload.get('run_id')}")
        stream = client.post(
            "/v2/run/stream",
            headers={"X-Request-ID": "step-plan-stream-001"},
            json={
                "brief": "AI产品经理求职内容运营选题",
                "platform": "小红书",
                "style": "种草推荐",
            },
        )

    health_payload = health.json()
    state = run_payload.get("state", {})
    package = state.get("content_package", {})
    events = state.get("events", [])
    node_payloads = {
        event.get("node"): event.get("payload", {})
        for event in events
        if event.get("node")
    }

    sse_events = parse_sse_events(stream.text)
    token_events = [item for item in sse_events if item.get("event") == "token"]
    token_summary_events = [
        item for item in sse_events if item.get("event") == "token_summary"
    ]
    first_token_event = token_events[0] if token_events else {}
    first_token_data = first_token_event.get("data", {}) if isinstance(first_token_event.get("data"), dict) else {}

    checks = [
        {
            "name": "swagger_docs_available",
            "actual": docs.status_code,
            "expected": 200,
            "pass": docs.status_code == 200,
        },
        {
            "name": "health_ok",
            "actual": health.status_code,
            "expected": 200,
            "pass": health.status_code == 200,
        },
        {
            "name": "provider_is_step_plan",
            "actual": health_payload.get("llm_provider_route"),
            "expected": "step_plan",
            "pass": health_payload.get("llm_provider_route") == "step_plan",
        },
        {
            "name": "langsmith_tracing_enabled",
            "actual": {
                "configured": health_payload.get("langsmith_configured"),
                "tracing": health_payload.get("langsmith_tracing"),
                "tracing_v2": health_payload.get("langsmith_tracing_v2"),
            },
            "expected": True,
            "pass": health_payload.get("langsmith_configured") is True
            and health_payload.get("langsmith_tracing") is True
            and health_payload.get("langsmith_tracing_v2") is True,
        },
        {
            "name": "postgres_connectivity",
            "actual": health_payload.get("checks", {}).get("postgres_connectivity"),
            "expected": True,
            "pass": health_payload.get("checks", {}).get("postgres_connectivity") is True,
        },
        {
            "name": "run_completed",
            "actual": state.get("status"),
            "expected": "completed",
            "pass": state.get("status") == "completed",
        },
        {
            "name": "run_detail_available",
            "actual": run_detail.status_code,
            "expected": 200,
            "pass": run_detail.status_code == 200
            and run_detail.json().get("status") == "completed",
        },
        {
            "name": "request_id_roundtrip",
            "actual": {
                "header": run.headers.get("x-request-id"),
                "state": state.get("request_id"),
            },
            "expected": "step-plan-smoke-001",
            "pass": run.headers.get("x-request-id") == "step-plan-smoke-001"
            and state.get("request_id") == "step-plan-smoke-001",
        },
        {
            "name": "research_not_fallback",
            "actual": node_payloads.get("research_topic", {}).get("parse_strategy"),
            "expected": "not fallback",
            "pass": "fallback"
            not in str(node_payloads.get("research_topic", {}).get("parse_strategy", "")),
        },
        {
            "name": "writer_not_fallback",
            "actual": node_payloads.get("write_draft", {}).get("parse_strategy"),
            "expected": "not fallback",
            "pass": "fallback"
            not in str(node_payloads.get("write_draft", {}).get("parse_strategy", "")),
        },
        {
            "name": "review_not_fallback",
            "actual": node_payloads.get("review_structured", {}).get("parse_strategy"),
            "expected": "not fallback",
            "pass": "fallback"
            not in str(node_payloads.get("review_structured", {}).get("parse_strategy", "")),
        },
        {
            "name": "json_export_exists",
            "actual": os.path.exists(package.get("json_path", "")),
            "expected": True,
            "pass": os.path.exists(package.get("json_path", "")),
        },
        {
            "name": "md_export_exists",
            "actual": os.path.exists(package.get("markdown_path", "")),
            "expected": True,
            "pass": os.path.exists(package.get("markdown_path", "")),
        },
        {
            "name": "sse_stream_available",
            "actual": {
                "status_code": stream.status_code,
                "header": stream.headers.get("content-type", ""),
                "body_prefix": stream.text[:80],
            },
            "expected": "200 + text/event-stream + start event",
            "pass": stream.status_code == 200
            and "text/event-stream" in stream.headers.get("content-type", "")
            and "event: start" in stream.text,
        },
        {
            "name": "token_stream_available",
            "actual": len(token_events),
            "expected": "> 0",
            "pass": len(token_events) > 0,
        },
        {
            "name": "token_summary_available",
            "actual": len(token_summary_events),
            "expected": "> 0",
            "pass": len(token_summary_events) > 0,
        },
        {
            "name": "ttft_captured",
            "actual": first_token_data.get("ttft_ms"),
            "expected": "positive number",
            "pass": isinstance(first_token_data.get("ttft_ms"), (int, float))
            and float(first_token_data.get("ttft_ms")) > 0,
        },
    ]

    payload = {
        "generated_at": utc_now(),
        "health": health_payload,
        "docs_status": docs.status_code,
        "run_id": run_payload.get("run_id"),
        "status": state.get("status"),
        "checks": checks,
        "all_passed": all(item["pass"] for item in checks),
        "metrics_totals": run_payload.get("metrics", {}).get("totals", {}),
        "parse_strategies": {
            "research_topic": node_payloads.get("research_topic", {}).get("parse_strategy"),
            "write_draft": node_payloads.get("write_draft", {}).get("parse_strategy"),
            "review_structured": node_payloads.get("review_structured", {}).get("parse_strategy"),
        },
        "streaming": {
            "event_count": len(sse_events),
            "token_event_count": len(token_events),
            "token_summary_event_count": len(token_summary_events),
            "first_token_ttft_ms": first_token_data.get("ttft_ms"),
            "first_token_node": first_token_data.get("node"),
            "first_token_preview": str(first_token_data.get("delta", ""))[:30],
        },
        "content_package": package,
    }

    out_path = os.path.join(
        os.path.join(PROJECT_ROOT, "benchmarks"),
        "latest_step_plan_runtime_report.json",
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
