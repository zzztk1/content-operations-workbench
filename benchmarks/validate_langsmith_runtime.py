import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from langsmith import Client


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from langgraph_v2 import LangGraphMediaAgentEngine  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def serialize_payload(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    os.environ["PYTHONUTF8"] = "1"
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_TRACING_V2", "true")

    api_key = os.getenv("LANGSMITH_API_KEY", "")
    endpoint = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    workspace_id = os.getenv("LANGSMITH_WORKSPACE_ID", "")
    project = os.getenv("LANGSMITH_PROJECT", "media-agent-v2")

    required_env = {
        "LANGSMITH_API_KEY": bool(api_key),
        "LANGSMITH_ENDPOINT": bool(endpoint),
        "LANGSMITH_PROJECT": bool(project),
    }
    if not all(required_env.values()):
        raise RuntimeError(f"LangSmith 环境变量不完整：{required_env}")

    run_id = f"ls{uuid.uuid4().hex[:10]}"
    request_id = f"langsmith-{run_id}"
    started_at = datetime.now(timezone.utc)

    with LangGraphMediaAgentEngine() as engine:
        result = engine.run_workflow(
            brief="AI Agent 在内容运营中的真实应用场景",
            platform="小红书",
            style="种草推荐",
            approval_decision="approve",
            run_id=run_id,
            thread_id=run_id,
            request_id=request_id,
        )

    client = Client(
        api_url=endpoint,
        api_key=api_key,
        workspace_id=workspace_id or None,
    )
    matched_runs: List[Dict[str, Any]] = []
    latest_candidates: List[Dict[str, Any]] = []
    query_error = ""

    try:
        for _ in range(4):
            matched_runs = []
            latest_candidates = []
            runs = list(
                client.list_runs(
                    project_name=project,
                    is_root=True,
                    start_time=started_at - timedelta(seconds=5),
                    limit=20,
                )
            )
            for run in runs:
                inputs_blob = serialize_payload(getattr(run, "inputs", {}) or {})
                outputs_blob = serialize_payload(getattr(run, "outputs", {}) or {})
                candidate = {
                    "id": str(getattr(run, "id", "")),
                    "name": getattr(run, "name", ""),
                    "run_type": getattr(run, "run_type", ""),
                    "start_time": str(getattr(run, "start_time", "")),
                    "end_time": str(getattr(run, "end_time", "")),
                    "status": getattr(run, "status", ""),
                    "url": getattr(run, "url", ""),
                    "has_run_id": run_id in inputs_blob or run_id in outputs_blob,
                    "has_request_id": request_id in inputs_blob or request_id in outputs_blob,
                }
                latest_candidates.append(candidate)
                if candidate["name"] == "media_agent_v2_invoke" and (
                    candidate["has_run_id"] or candidate["has_request_id"]
                ):
                    matched_runs.append(candidate)
            if matched_runs:
                break
            time.sleep(3)
    except Exception as exc:
        query_error = str(exc)

    checks = [
        {
            "name": "langsmith_env_ready",
            "actual": required_env,
            "expected": True,
            "pass": all(required_env.values()),
        },
        {
            "name": "local_run_completed",
            "actual": result.get("state", {}).get("status"),
            "expected": "completed",
            "pass": result.get("state", {}).get("status") == "completed",
        },
        {
            "name": "langsmith_trace_found",
            "actual": {"matched_count": len(matched_runs), "query_error": query_error},
            "expected": "> 0",
            "pass": len(matched_runs) > 0,
        },
    ]

    payload = {
        "generated_at": utc_now(),
        "project": project,
        "endpoint": endpoint,
        "workspace_id": workspace_id or None,
        "run_id": run_id,
        "request_id": request_id,
        "checks": checks,
        "all_passed": all(item["pass"] for item in checks),
        "query_error": query_error,
        "blocker_hint": (
            "当前 LangSmith key 很可能是 org-scoped / full-organization 类型，"
            "需要额外配置 LANGSMITH_WORKSPACE_ID，或改用 workspace-scoped key。"
            if query_error and "403" in query_error
            else ""
        ),
        "local_result": {
            "run_id": result.get("run_id"),
            "status": result.get("state", {}).get("status"),
            "trace": result.get("state", {}).get("trace", []),
        },
        "matched_runs": matched_runs,
        "latest_candidates": latest_candidates[:5],
    }

    out_path = os.path.join(
        PROJECT_ROOT,
        "benchmarks",
        "latest_langsmith_runtime_report.json",
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if not payload["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
