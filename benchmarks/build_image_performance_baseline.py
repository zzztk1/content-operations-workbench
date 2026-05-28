"""
Build formal image performance baseline for the default model (step-2x-large) from committed artifacts.

Does not call image APIs. Re-run after refreshing source JSON exports (e.g. new model-switch verification run).

Usage:
  python benchmarks/build_image_performance_baseline.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = PROJECT_ROOT / "benchmarks"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_stdout_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def rel_to_project(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def main() -> None:
    ensure_stdout_utf8()

    switch_path = BENCHMARK_DIR / "latest_image_model_switch_report.json"
    switch = load_json(switch_path)
    run_id = switch.get("api_run_id") or ""
    export_name = f"{run_id}.v2.json" if run_id else ""
    export_path = OUTPUTS_DIR / export_name if export_name else Path()

    if not export_path.exists():
        print(
            json.dumps(
                {
                    "error": "missing_workflow_export",
                    "expected": str(export_path),
                    "hint": "Ensure latest_image_model_switch_report.api_run_id matches a outputs/*.v2.json export.",
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)

    export = load_json(export_path)
    asset = export.get("image_asset") or {}
    model = str(asset.get("model") or "")
    health_model = str(switch.get("api_image_model") or switch.get("health_image_model") or "")

    if model != "step-2x-large" or health_model != "step-2x-large":
        print(
            json.dumps(
                {
                    "error": "model_mismatch",
                    "export_model": model,
                    "switch_health_model": health_model,
                    "expected": "step-2x-large",
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)

    latency = float(asset.get("latency_ms") or 0.0)
    batch_path = BENCHMARK_DIR / "latest_image_batch_compare_report.json"
    quality_path = BENCHMARK_DIR / "latest_image_asset_quality_report.json"
    batch = load_json(batch_path) if batch_path.exists() else {}
    quality = load_json(quality_path) if quality_path.exists() else {}

    payload: Dict[str, Any] = {
        "generated_at": utc_now(),
        "canonical_image_model": "step-2x-large",
        "baseline_kind": "single_full_workflow_cover_generation",
        "purpose": (
            "Representative generate_cover latency for the default image model on one real API run "
            "(bind resume claims to this file; not a throughput benchmark)."
        ),
        "sources": {
            "image_model_switch_report": rel_to_project(switch_path),
            "workflow_export": rel_to_project(export_path),
        },
        "metrics": {
            "run_id": run_id,
            "generate_cover_latency_ms": round(latency, 2),
            "recorded_image_model": model,
            "web_path": asset.get("web_path"),
        },
        "related_reports": {
            "batch_compare": {
                "path": rel_to_project(batch_path),
                "image_model_in_report": batch.get("image_model"),
                "note": (
                    "Serial vs parallel wall-time compare; may reflect an older STEPFUN_IMAGE_MODEL "
                    "unless refreshed. Re-run benchmarks/compare_image_batch_modes.py with real API when budget allows."
                ),
            },
            "image_asset_quality": {
                "path": rel_to_project(quality_path),
                "image_model_in_report": (quality.get("image_asset") or {}).get("model"),
                "note": (
                    "File-level checks on a real workflow export; model follows the run that produced "
                    "latest_real_visual_workflow_report / source_report."
                ),
            },
        },
        "all_passed": True,
    }

    out_path = BENCHMARK_DIR / "latest_image_performance_baseline.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
