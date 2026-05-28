import asyncio
import json
import os
import sys
import time
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


def plans() -> List[Dict[str, Any]]:
    return [
        {
            "prompt": (
                "A cover illustration about information overload and declining judgment. "
                "A central human silhouette is surrounded by chaotic data streams, news cards, "
                "and algorithm arrows. Editorial tech style, high contrast, suitable for a "
                "Chinese long-form公众号头图."
            ),
            "negative_prompt": "cartoon, anime, low quality, watermark, text errors, blurry",
            "overlay_text": "信息越多，判断越难",
            "visual_style": "editorial tech illustration",
            "aspect_ratio": "16:9",
        },
        {
            "prompt": (
                "A cover illustration about adult energy management. "
                "A calm figure stands beside a glowing battery icon while fragmented notifications "
                "and unfinished tasks swirl around. Clean editorial style, modern business magazine feeling."
            ),
            "negative_prompt": "cartoon, childish, overly colorful, cluttered, blurry",
            "overlay_text": "真正的恢复力",
            "visual_style": "business editorial illustration",
            "aspect_ratio": "16:9",
        },
        {
            "prompt": (
                "A cover illustration about stability and uncertainty. "
                "A person walks on a narrow bridge between a calm city and a stormy digital landscape. "
                "Symbolic composition, deep blue-gray palette, suitable for Chinese long-form content."
            ),
            "negative_prompt": "watermark, logo, cartoon, low resolution, messy layout",
            "overlay_text": "重新理解稳定",
            "visual_style": "conceptual long-form cover",
            "aspect_ratio": "16:9",
        },
    ]


def _asset_ok(asset: Dict[str, Any]) -> bool:
    return asset.get("status") in {"generated", "mock_generated"}


def summarize_results(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    sum_per_item_wall_time_ms = round(sum(float(item["wall_time_ms"]) for item in items), 2)
    max_wall_time_ms = round(max(float(item["wall_time_ms"]) for item in items), 2)
    avg_asset_latency_ms = round(
        sum(float(item["asset"].get("latency_ms", 0.0)) for item in items) / max(1, len(items)),
        2,
    )
    total_retry_count = sum(int(item["asset"].get("retry_count", 0)) for item in items)
    successes = sum(1 for item in items if _asset_ok(item["asset"]))
    success_rate = round(successes / max(1, len(items)), 4)
    return {
        "count": len(items),
        "total_wall_time_ms": sum_per_item_wall_time_ms,
        "sum_per_item_wall_time_ms": sum_per_item_wall_time_ms,
        "avg_asset_latency_ms": avg_asset_latency_ms,
        "total_retry_count": total_retry_count,
        "success_count": successes,
        "success_rate": success_rate,
        "items": items,
    }


async def main_async() -> Dict[str, Any]:
    load_env()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    force_real = os.getenv("IMAGE_BENCHMARK_REAL", "true").strip().lower() in {"1", "true", "yes", "on"}
    image_mock = not force_real
    os.environ["LLM_MOCK"] = "true"
    os.environ["CHECKPOINTER_MOCK"] = "true"
    os.environ["IMAGE_MOCK"] = "false" if force_real else "true"

    settings = V2Settings.from_env()
    prompt_plans = plans()

    # Default 3 matches historical compare (one slot per plan). Set IMAGE_BATCH_COMPARE_CONCURRENCY=2
    # to measure capped fan-out for step-2x-large without changing engine defaults.
    batch_concurrency = max(
        1,
        min(
            len(prompt_plans),
            int(os.getenv("IMAGE_BATCH_COMPARE_CONCURRENCY", "3")),
        ),
    )

    with LangGraphMediaAgentEngine(settings=settings) as engine:
        sequential_started = time.perf_counter()
        sequential_items: List[Dict[str, Any]] = []
        for index, plan in enumerate(prompt_plans):
            run_id = f"imgseq-{index + 1:02d}"
            item_started = time.perf_counter()
            asset = engine._generate_cover_asset(run_id=run_id, plan=plan, image_mock=image_mock)  # noqa: SLF001
            sequential_items.append(
                {
                    "index": index,
                    "run_id": run_id,
                    "asset": asset,
                    "wall_time_ms": round((time.perf_counter() - item_started) * 1000, 2),
                }
            )
        sequential_total_ms = round((time.perf_counter() - sequential_started) * 1000, 2)

        concurrent_started = time.perf_counter()
        concurrent_items = await engine.generate_cover_assets_batch(
            prompt_plans,
            run_prefix="imgcon",
            image_mock=image_mock,
            concurrency=batch_concurrency,
        )
        concurrent_total_ms = round((time.perf_counter() - concurrent_started) * 1000, 2)

    sequential_summary = summarize_results(sequential_items)
    concurrent_summary = summarize_results(concurrent_items)

    speedup_ratio = round(sequential_total_ms / concurrent_total_ms, 3) if concurrent_total_ms > 0 else 0.0
    reduction_pct = (
        round(((sequential_total_ms - concurrent_total_ms) / sequential_total_ms) * 100, 2)
        if sequential_total_ms > 0
        else 0.0
    )

    payload = {
        "generated_at": utc_now(),
        "mode": "real" if force_real else "mock",
        "image_model": settings.image_model,
        "image_api_base": settings.image_api_base,
        "image_mock_effective": image_mock,
        "sequential": {
            **sequential_summary,
            "total_elapsed_ms": sequential_total_ms,
            "batch_wall_clock_ms": sequential_total_ms,
        },
        "concurrent": {
            **concurrent_summary,
            "total_elapsed_ms": concurrent_total_ms,
            "batch_wall_clock_ms": concurrent_total_ms,
            "concurrency": batch_concurrency,
            "compare_notes": (
                "Primary latency metric is total_elapsed_ms / batch_wall_clock_ms (wall clock for the batch). "
                "sum_per_item_wall_time_ms sums per-task durations and can exceed wall clock when tasks overlap."
            ),
        },
        "benchmark_settings": {
            "batch_concurrency": batch_concurrency,
            "image_batch_compare_concurrency_env": os.getenv("IMAGE_BATCH_COMPARE_CONCURRENCY", "3"),
        },
        "comparison": {
            "speedup_ratio": speedup_ratio,
            "elapsed_reduction_pct": reduction_pct,
            "sequential_elapsed_ms": sequential_total_ms,
            "concurrent_elapsed_ms": concurrent_total_ms,
            "sequential_success_rate": sequential_summary["success_rate"],
            "concurrent_success_rate": concurrent_summary["success_rate"],
            "avg_asset_latency_ms_sequential": sequential_summary["avg_asset_latency_ms"],
            "avg_asset_latency_ms_concurrent": concurrent_summary["avg_asset_latency_ms"],
            "retry_count_sequential": sequential_summary["total_retry_count"],
            "retry_count_concurrent": concurrent_summary["total_retry_count"],
        },
        "all_passed": (
            len(sequential_items) == len(prompt_plans)
            and len(concurrent_items) == len(prompt_plans)
            and all(_asset_ok(item["asset"]) for item in sequential_items + concurrent_items)
        ),
    }
    return payload


def main() -> None:
    payload = asyncio.run(main_async())
    out_path = PROJECT_ROOT / "benchmarks" / "latest_image_batch_compare_report.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
