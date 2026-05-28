"""
Low-cost validation: reads committed image benchmark JSON artifacts only (no API / no image generation).

Includes `latest_image_performance_baseline.json` (step-2x-large single-run latency evidence).

Use after other benchmarks have populated latest_*.json files, or to verify repo state in CI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = PROJECT_ROOT / "benchmarks"


def ensure_stdout_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def checks_all_pass(data: Dict[str, Any]) -> Tuple[bool, str]:
    if not data:
        return False, "missing_or_empty"
    if data.get("all_passed") is True:
        return True, "all_passed"
    checks = data.get("checks")
    if isinstance(checks, list) and checks:
        ok = all(bool(c.get("pass")) for c in checks)
        return ok, "checks_list"
    return False, "no_checks"


def eval_multicover(data: Dict[str, Any]) -> Tuple[bool, str]:
    ok, reason = checks_all_pass(data)
    if not ok:
        return False, reason
    cands = data.get("cover_candidates") or []
    if len(cands) < 2:
        return False, "need_at_least_2_candidates"
    if data.get("status") != "completed":
        return False, "status_not_completed"
    return True, reason


def eval_quality(data: Dict[str, Any]) -> Tuple[bool, str]:
    ok, reason = checks_all_pass(data)
    if not ok:
        return False, reason
    return True, reason


def eval_batch_compare(data: Dict[str, Any]) -> Tuple[bool, str]:
    ok, reason = checks_all_pass(data)
    if ok:
        return True, reason
    seq = data.get("sequential") or {}
    conc = data.get("concurrent") or {}
    if seq.get("success_count", 0) < 1 or conc.get("success_count", 0) < 1:
        return False, "success_counts"
    if not data.get("comparison"):
        return False, "no_comparison"
    return True, "legacy_shape"


def eval_model_switch(data: Dict[str, Any]) -> Tuple[bool, str]:
    if not data:
        return False, "missing"
    if data.get("all_passed") is True:
        return True, "all_passed"
    return False, "all_passed_false"


def eval_performance_baseline(data: Dict[str, Any]) -> Tuple[bool, str]:
    if not data:
        return False, "missing"
    if data.get("canonical_image_model") != "step-2x-large":
        return False, "wrong_model"
    if data.get("all_passed") is not True:
        return False, "all_passed_false"
    metrics = data.get("metrics") or {}
    if float(metrics.get("generate_cover_latency_ms") or 0) <= 0:
        return False, "no_latency"
    return True, "ok"


def eval_text_image_from_visual_pipeline(data: Dict[str, Any]) -> Tuple[bool, str]:
    ok, reason = checks_all_pass(data)
    if not ok:
        return False, reason
    checks_list: List[Dict[str, Any]] = data.get("checks") or []
    tic_checks = [c for c in checks_list if str(c.get("name", "")).startswith("text_image_consistency")]
    if not tic_checks:
        return False, "no_tic_checks"
    if not all(c.get("pass") for c in tic_checks):
        return False, "tic_failed"
    return True, reason


def eval_visual_review(data: Dict[str, Any], expected_mode: str | None = None) -> Tuple[bool, str]:
    ok, reason = checks_all_pass(data)
    if not ok:
        return False, reason
    review = data.get("cover_visual_review") or {}
    required = {
        "theme_match_score",
        "readability_score",
        "composition_score",
        "overall_score",
        "passed",
        "risk_flags",
        "feedback",
        "review_mode",
        "vision_model",
    }
    if not required.issubset(set(review.keys())):
        return False, "missing_visual_review_keys"
    if expected_mode and review.get("review_mode") != expected_mode:
        return False, f"wrong_review_mode:{review.get('review_mode')}"
    return True, reason


def evaluate_image_artifacts(benchmark_dir: Path | None = None) -> Dict[str, Any]:
    base = benchmark_dir or BENCHMARK_DIR
    paths = {
        "visual_multicover": base / "latest_visual_multicover_pipeline_report.json",
        "image_asset_quality": base / "latest_image_asset_quality_report.json",
        "image_batch_compare": base / "latest_image_batch_compare_report.json",
        "visual_pipeline": base / "latest_visual_pipeline_report.json",
        "image_model_switch": base / "latest_image_model_switch_report.json",
        "image_performance_baseline": base / "latest_image_performance_baseline.json",
        "visual_review_mock": base / "latest_visual_review_mock_report.json",
        "visual_review_real": base / "latest_visual_review_real_report.json",
        "visual_review_badcase": base / "latest_visual_review_badcase_report.json",
    }
    loaded = {k: load_json(p) for k, p in paths.items()}

    multicover_ok, multicover_reason = eval_multicover(loaded["visual_multicover"])
    quality_ok, quality_reason = eval_quality(loaded["image_asset_quality"])
    batch_ok, batch_reason = eval_batch_compare(loaded["image_batch_compare"])
    tic_ok, tic_reason = eval_text_image_from_visual_pipeline(loaded["visual_pipeline"])
    switch_ok, switch_reason = eval_model_switch(loaded["image_model_switch"])
    baseline_ok, baseline_reason = eval_performance_baseline(loaded["image_performance_baseline"])
    vr_mock_ok, vr_mock_reason = eval_visual_review(loaded["visual_review_mock"], expected_mode="mock")
    vr_real_ok, vr_real_reason = eval_visual_review(loaded["visual_review_real"], expected_mode="real")
    vr_badcase_ok, vr_badcase_reason = checks_all_pass(loaded["visual_review_badcase"])

    artifact_status = {
        "visual_multicover": {
            "path": str(paths["visual_multicover"]),
            "pass": multicover_ok,
            "reason": multicover_reason,
        },
        "image_asset_quality": {
            "path": str(paths["image_asset_quality"]),
            "pass": quality_ok,
            "reason": quality_reason,
        },
        "image_batch_compare": {
            "path": str(paths["image_batch_compare"]),
            "pass": batch_ok,
            "reason": batch_reason,
        },
        "visual_pipeline_text_image": {
            "path": str(paths["visual_pipeline"]),
            "pass": tic_ok,
            "reason": tic_reason,
        },
        "image_model_switch": {
            "path": str(paths["image_model_switch"]),
            "pass": switch_ok,
            "reason": switch_reason,
        },
        "image_performance_baseline": {
            "path": str(paths["image_performance_baseline"]),
            "pass": baseline_ok,
            "reason": baseline_reason,
        },
        "visual_review_mock": {
            "path": str(paths["visual_review_mock"]),
            "pass": vr_mock_ok,
            "reason": vr_mock_reason,
        },
        "visual_review_real": {
            "path": str(paths["visual_review_real"]),
            "pass": vr_real_ok,
            "reason": vr_real_reason,
        },
        "visual_review_badcase": {
            "path": str(paths["visual_review_badcase"]),
            "pass": vr_badcase_ok,
            "reason": vr_badcase_reason,
        },
    }

    core_ok = multicover_ok and quality_ok and batch_ok and tic_ok and baseline_ok and vr_mock_ok and vr_real_ok and vr_badcase_ok
    all_ok = core_ok and switch_ok

    return {
        "benchmark_dir": str(base),
        "artifact_status": artifact_status,
        "core_artifacts_passed": core_ok,
        "all_artifacts_passed": all_ok,
    }


def main() -> None:
    ensure_stdout_utf8()
    payload = evaluate_image_artifacts()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.exit(0 if payload["core_artifacts_passed"] else 1)


if __name__ == "__main__":
    main()
