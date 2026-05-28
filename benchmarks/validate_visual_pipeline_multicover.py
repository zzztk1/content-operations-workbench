"""Mock pipeline check: workflow returns multiple cover candidates."""

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

    os.environ["LLM_MOCK"] = "true"
    os.environ["IMAGE_MOCK"] = "true"
    os.environ["CHECKPOINTER_MOCK"] = "true"

    app = create_app()
    with TestClient(app) as client:
        run = client.post(
            "/v2/run",
            headers={"X-Request-ID": "visual-multicover-001"},
            json={
                "brief": "写一篇公众号文章，主题是“信息越来越多，为什么真正有判断力的人反而更少了”。要求带一点趋势观察和个人思考，适合公众号深度表达。",
                "platform": "公众号",
                "style": "经验总结",
                "approval_decision": "approve",
                "approval_note": "visual-multicover-check",
                "reviewer_threshold": 21,
                "max_revisions": 1,
                "run_id": "visualmulticover001",
                "cover_candidate_count": 3,
            },
        )
        payload = run.json()
        state = payload.get("state", {})
        candidates = state.get("cover_candidates") or []
        primary = state.get("image_asset") or {}

    checks = [
        {
            "name": "run_completed",
            "actual": state.get("status"),
            "expected": "completed",
            "pass": state.get("status") == "completed",
        },
        {
            "name": "cover_candidates_count",
            "actual": len(candidates),
            "expected": 3,
            "pass": len(candidates) == 3,
        },
        {
            "name": "primary_matches_first_candidate",
            "actual": (primary.get("web_path"), candidates[0].get("web_path") if candidates else None),
            "expected": "same web_path",
            "pass": bool(candidates) and primary.get("web_path") == candidates[0].get("web_path"),
        },
        {
            "name": "all_candidates_have_web_path",
            "actual": [candidate.get("web_path") for candidate in candidates],
            "expected": "3 non-empty",
            "pass": len(candidates) == 3 and all(candidate.get("web_path") for candidate in candidates),
        },
        {
            "name": "export_lists_candidates",
            "actual": len(state.get("content_package", {}).get("cover_candidates_summary") or []),
            "expected": 3,
            "pass": len(state.get("content_package", {}).get("cover_candidates_summary") or []) == 3,
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

    result = {
        "generated_at": utc_now(),
        "run_id": payload.get("run_id"),
        "status": state.get("status"),
        "cover_candidate_count_requested": 3,
        "cover_candidates": candidates,
        "image_asset": primary,
        "content_package_excerpt": {
            "cover_candidate_count": state.get("content_package", {}).get("cover_candidate_count"),
            "cover_candidates_summary": state.get("content_package", {}).get("cover_candidates_summary"),
        },
        "checks": checks,
        "all_passed": all(item["pass"] for item in checks),
    }

    out_path = os.path.join(PROJECT_ROOT, "benchmarks", "latest_visual_multicover_pipeline_report.json")
    with open(out_path, "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
