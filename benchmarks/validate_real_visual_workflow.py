import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from langgraph_v2 import LangGraphMediaAgentEngine  # noqa: E402
from langgraph_v2.settings import V2Settings  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_env() -> None:
    for key, value in dotenv_values(PROJECT_ROOT / ".env").items():
        if value is not None and key not in os.environ:
            os.environ[key] = value


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    load_env()
    os.environ["LLM_MOCK"] = "false"
    os.environ["CHECKPOINTER_MOCK"] = "false"
    os.environ["IMAGE_MOCK"] = "false"

    settings = V2Settings.from_env()
    checks: List[Dict[str, Any]] = []

    with LangGraphMediaAgentEngine(settings=settings) as engine:
        result = engine.run_workflow(
            brief="写一篇公众号文章，主题是“信息越多，为什么真正有判断力的人反而更少了”。要求带一点趋势观察和个人思考，适合公众号深度表达。",
            platform="公众号",
            style="经验总结",
            approval_decision="approve",
            approval_note="real-visual-check",
            reviewer_threshold=21,
            max_revisions=1,
            run_id="realvisual001",
            thread_id="realvisual001",
            request_id="real-visual-001",
            runtime_overrides={"image_mock": False},
        )

    state = result["state"]
    image_plan = state.get("image_plan", {})
    image_asset = state.get("image_asset", {})
    local_path = Path(image_asset.get("local_path", "")) if image_asset.get("local_path") else None

    checks.extend(
        [
            {
                "name": "run_completed",
                "actual": state.get("status"),
                "expected": "completed",
                "pass": state.get("status") == "completed",
            },
            {
                "name": "image_plan_present",
                "actual": bool(image_plan),
                "expected": True,
                "pass": bool(image_plan),
            },
            {
                "name": "image_asset_generated",
                "actual": image_asset.get("status"),
                "expected": "generated",
                "pass": image_asset.get("status") == "generated",
            },
            {
                "name": "image_provider_stepfun",
                "actual": image_asset.get("provider"),
                "expected": "stepfun_images",
                "pass": image_asset.get("provider") == "stepfun_images",
            },
            {
                "name": "image_file_exists",
                "actual": bool(local_path and local_path.exists()),
                "expected": True,
                "pass": bool(local_path and local_path.exists()),
            },
            {
                "name": "visual_trace_present",
                "actual": state.get("trace", []),
                "expected": "contains plan_cover, generate_cover, review_cover_visual",
                "pass": "plan_cover" in state.get("trace", [])
                and "generate_cover" in state.get("trace", [])
                and "review_cover_visual" in state.get("trace", []),
            },
        ]
    )

    payload = {
        "generated_at": utc_now(),
        "run_id": result["run_id"],
        "request_id": result.get("request_id"),
        "status": state.get("status"),
        "image_plan": image_plan,
        "image_asset": image_asset,
        "content_package": state.get("content_package", {}),
        "trace": state.get("trace", []),
        "checks": checks,
        "all_passed": all(item["pass"] for item in checks),
    }

    out_path = PROJECT_ROOT / "benchmarks" / "latest_real_visual_workflow_report.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if not payload["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
