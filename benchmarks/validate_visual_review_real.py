"""Run one minimal real vision review against an existing PNG asset."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from langgraph_v2.engine import LangGraphMediaAgentEngine  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_existing_png() -> Path | None:
    image_dir = PROJECT_ROOT / "outputs" / "images"
    if not image_dir.exists():
        return None
    candidates = sorted(image_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    has_key = bool(os.getenv("STEPFUN_VISION_API_KEY") or os.getenv("STEPFUN_API_KEY"))
    png_path = find_existing_png()

    if not has_key:
        result = {
            "generated_at": utc_now(),
            "skipped": True,
            "reason": "missing vision api key",
            "checks": [{"name": "vision_key_present", "pass": False}],
            "all_passed": False,
        }
        out_path = PROJECT_ROOT / "benchmarks" / "latest_visual_review_real_report.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if not png_path:
        result = {
            "generated_at": utc_now(),
            "skipped": True,
            "reason": "no existing png asset found for low-cost real vision validation",
            "checks": [{"name": "png_fixture_present", "pass": False}],
            "all_passed": False,
        }
        out_path = PROJECT_ROOT / "benchmarks" / "latest_visual_review_real_report.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    os.environ["LLM_MOCK"] = "true"
    os.environ["IMAGE_MOCK"] = "true"
    os.environ["CHECKPOINTER_MOCK"] = "true"
    os.environ["VISION_REVIEW_MOCK"] = "false"

    state = {
        "run_id": "visrevreal001",
        "request_id": "visual-review-real-001",
        "thread_id": "visrevreal001",
        "graph_version": "v2",
        "brief": "为公众号文章生成封面图，主题聚焦信息过载与判断力下降。",
        "platform": "公众号",
        "style": "经验总结",
        "draft": {
            "title": "信息越多，为什么判断力反而更少了",
            "content": "信息过载会挤占真正思考的空间，判断力来自筛选、停顿和建立标准，而不是继续接收更多信息。",
            "tags": ["#信息过载", "#判断力", "#公众号"],
            "platform": "公众号",
        },
        "adapted": {
            "title": "信息越多，为什么判断力反而更少了",
            "content": "信息过载会挤占真正思考的空间，判断力来自筛选、停顿和建立标准，而不是继续接收更多信息。",
            "tags": ["#信息过载", "#判断力", "#公众号"],
            "platform": "公众号",
        },
        "image_plan": {
            "prompt": "A cover illustration about information overload and declining judgment. Editorial style. Calm but sharp. Suitable for a Chinese WeChat article cover.",
            "negative_prompt": "blurry, low quality, messy layout",
            "overlay_text": "判断力",
            "visual_style": "editorial minimalism",
            "aspect_ratio": "4:3",
        },
        "image_asset": {
            "status": "generated",
            "provider": "stepfun_images",
            "model": "step-2x-large",
            "requested_size": "1024x1024",
            "prompt": "existing png asset reuse for real vision validation",
            "negative_prompt": "",
            "image_url": "",
            "local_path": str(png_path),
            "web_path": f"/outputs/images/{png_path.name}",
            "mime_type": "image/png",
            "retry_count": 0,
            "latency_ms": 0.0,
        },
        "runtime_flags": {
            "llm_mock": True,
            "image_mock": True,
            "vision_review_mock": False,
            "checkpointer_mock": True,
            "enable_sse": False,
            "enable_slowapi": False,
            "enable_json_mode": True,
        },
        "events": [],
        "trace": [],
        "metrics": {"totals": {}, "node_metrics": []},
        "errors": [],
    }

    with LangGraphMediaAgentEngine() as engine:
        updates = engine.node_review_cover_visual(state)

    review = updates.get("cover_visual_review") or {}
    checks = [
        {"name": "review_mode_real", "pass": review.get("review_mode") == "real", "actual": review.get("review_mode")},
        {"name": "overall_score_present", "pass": isinstance(review.get("overall_score"), int), "actual": review.get("overall_score")},
        {"name": "vision_model_present", "pass": review.get("vision_model") == "step-1o-turbo-vision", "actual": review.get("vision_model")},
    ]

    result = {
        "generated_at": utc_now(),
        "skipped": False,
        "fixture_png": str(png_path),
        "cover_visual_review": review,
        "checks": checks,
        "all_passed": all(item["pass"] for item in checks),
    }
    out_path = PROJECT_ROOT / "benchmarks" / "latest_visual_review_real_report.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
