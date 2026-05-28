"""Mock-mode visual review: full /v2/run with LLM + image mocked, vision review mocked."""

from __future__ import annotations

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
    os.environ["VISION_REVIEW_MOCK"] = "true"
    os.environ["CHECKPOINTER_MOCK"] = "true"

    app = create_app()
    with TestClient(app) as client:
        run = client.post(
            "/v2/run",
            headers={"X-Request-ID": "visual-review-mock-001"},
            json={
                "brief": "写一篇关于专注力与信息过载的短文，适合公众号。",
                "platform": "公众号",
                "style": "经验总结",
                "approval_decision": "approve",
                "approval_note": "visual-review-mock",
                "reviewer_threshold": 21,
                "max_revisions": 1,
                "run_id": "visrevmock001",
                "cover_candidate_count": 1,
            },
        )
        payload = run.json()
        state = payload.get("state", {})
        cvr = state.get("cover_visual_review") or {}
        trace = state.get("trace", [])

    checks = [
        {
            "name": "run_completed",
            "pass": state.get("status") == "completed",
            "actual": state.get("status"),
            "expected": "completed",
        },
        {
            "name": "review_cover_visual_in_trace",
            "pass": "review_cover_visual" in trace,
            "actual": trace,
            "expected": "contains review_cover_visual",
        },
        {
            "name": "cover_visual_review_schema",
            "pass": all(
                k in cvr
                for k in (
                    "theme_match_score",
                    "readability_score",
                    "composition_score",
                    "overall_score",
                    "passed",
                    "risk_flags",
                    "feedback",
                    "review_mode",
                    "vision_model",
                )
            ),
            "actual": list(cvr.keys()),
            "expected": "required visual review keys",
        },
        {
            "name": "mock_mode_flag",
            "pass": cvr.get("review_mode") == "mock",
            "actual": cvr.get("review_mode"),
            "expected": "mock",
        },
    ]

    result = {
        "generated_at": utc_now(),
        "run_id": payload.get("run_id"),
        "cover_visual_review": cvr,
        "checks": checks,
        "all_passed": all(c["pass"] for c in checks),
    }
    out_path = os.path.join(PROJECT_ROOT, "benchmarks", "latest_visual_review_mock_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
