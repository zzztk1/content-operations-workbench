import json
import os
import sys
from datetime import datetime, timezone

from fastapi.testclient import TestClient


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from api_v2 import create_app  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    os.environ["IMAGE_MOCK"] = "true"
    app = create_app()
    with TestClient(app) as client:
        run = client.post(
            "/v2/run",
            headers={"X-Request-ID": "visual-pipeline-001"},
            json={
                "brief": "写一篇公众号文章，主题是“信息越来越多，为什么真正有判断力的人反而更少了”。要求带一点趋势观察和个人思考，适合公众号深度表达。",
                "platform": "公众号",
                "style": "经验总结",
                "approval_decision": "approve",
                "approval_note": "visual-pipeline-check",
                "reviewer_threshold": 21,
                "max_revisions": 1,
                "run_id": "visualpipeline001",
            },
        )
        payload = run.json()
        state = payload.get("state", {})
        image_asset = state.get("image_asset", {})
        image_web_path = image_asset.get("web_path", "")
        image_http_status = None
        if image_web_path:
            image_resp = client.get(image_web_path)
            image_http_status = image_resp.status_code

    checks = [
        {
            "name": "run_completed",
            "actual": state.get("status"),
            "expected": "completed",
            "pass": state.get("status") == "completed",
        },
        {
            "name": "image_plan_present",
            "actual": bool(state.get("image_plan")),
            "expected": True,
            "pass": bool(state.get("image_plan")),
        },
        {
            "name": "image_asset_present",
            "actual": bool(image_asset),
            "expected": True,
            "pass": bool(image_asset),
        },
        {
            "name": "image_asset_has_web_path",
            "actual": image_web_path,
            "expected": "non-empty",
            "pass": bool(image_web_path),
        },
        {
            "name": "image_file_exists",
            "actual": os.path.exists(image_asset.get("local_path", "")),
            "expected": True,
            "pass": os.path.exists(image_asset.get("local_path", "")),
        },
        {
            "name": "image_static_served",
            "actual": image_http_status,
            "expected": 200,
            "pass": image_http_status == 200,
        },
        {
            "name": "visual_subgraph_in_trace",
            "actual": state.get("trace", []),
            "expected": "contains plan_cover, generate_cover, review_cover_visual",
            "pass": "plan_cover" in state.get("trace", [])
            and "generate_cover" in state.get("trace", [])
            and "review_cover_visual" in state.get("trace", []),
        },
    ]

    tic = state.get("text_image_consistency") or (state.get("content_package") or {}).get(
        "text_image_consistency"
    )
    tic_ok = isinstance(tic, dict) and tic.get("status") in {"ok", "weak", "poor", "unknown"}
    tic_score_ok = isinstance(tic, dict) and isinstance(tic.get("score"), (int, float))
    checks.extend(
        [
            {
                "name": "text_image_consistency_present",
                "actual": bool(tic),
                "expected": True,
                "pass": bool(tic),
            },
            {
                "name": "text_image_consistency_status_shape",
                "actual": tic.get("status") if isinstance(tic, dict) else None,
                "expected": "ok|weak|poor|unknown",
                "pass": tic_ok,
            },
            {
                "name": "text_image_consistency_score_numeric",
                "actual": tic.get("score") if isinstance(tic, dict) else None,
                "expected": "0..1",
                "pass": tic_score_ok and 0 <= float(tic["score"]) <= 1,
            },
        ]
    )

    result = {
        "generated_at": utc_now(),
        "run_id": payload.get("run_id"),
        "status": state.get("status"),
        "image_plan": state.get("image_plan", {}),
        "image_asset": image_asset,
        "checks": checks,
        "all_passed": all(item["pass"] for item in checks),
    }

    out_path = os.path.join(PROJECT_ROOT, "benchmarks", "latest_visual_pipeline_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
