import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = PROJECT_ROOT / "benchmarks"
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from langgraph_v2.image_text_consistency import validate_consistency_shape  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_size(size: str) -> Dict[str, int]:
    width, height = size.split("x", 1)
    return {"width": int(width), "height": int(height)}


def _mime_from_path(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }.get(ext, "")


def validate_one_asset(
    image_asset: Dict[str, Any],
    *,
    label: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    local_path = Path(image_asset.get("local_path", ""))
    requested_size = image_asset.get("requested_size", "")
    declared_mime = str(image_asset.get("mime_type") or "")

    width = height = 0
    if local_path.exists():
        if local_path.suffix.lower() == ".svg":
            raw = local_path.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'viewBox="0\s+0\s+(\d+)\s+(\d+)"', raw)
            if m:
                width, height = int(m.group(1)), int(m.group(2))
        else:
            try:
                with Image.open(local_path) as img:
                    width, height = img.size
            except Exception:
                width = height = 0

    file_size_bytes = local_path.stat().st_size if local_path.exists() else 0
    sniff_mime = _mime_from_path(local_path)
    aspect_ratio = round(width / height, 4) if width and height else 0.0

    checks.append(
        {
            "name": f"{label}_file_exists",
            "actual": local_path.exists(),
            "expected": True,
            "pass": local_path.exists(),
        }
    )
    checks.append(
        {
            "name": f"{label}_file_size_bytes",
            "actual": file_size_bytes,
            "expected": "> 0",
            "pass": file_size_bytes > 0,
        }
    )
    checks.append(
        {
            "name": f"{label}_mime_type_declared",
            "actual": declared_mime,
            "expected": "non-empty",
            "pass": bool(declared_mime),
        }
    )
    checks.append(
        {
            "name": f"{label}_mime_consistent_with_extension",
            "actual": {"declared": declared_mime, "from_extension": sniff_mime},
            "expected": "match when both known",
            "pass": not sniff_mime or not declared_mime or declared_mime.split(";")[0].strip() == sniff_mime,
        }
    )
    checks.append(
        {
            "name": f"{label}_dimensions_readable",
            "actual": {"width": width, "height": height},
            "expected": "positive integers",
            "pass": width > 0 and height > 0,
        }
    )
    checks.append(
        {
            "name": f"{label}_aspect_ratio",
            "actual": aspect_ratio,
            "expected": "> 0",
            "pass": aspect_ratio > 0,
        }
    )

    skip_raster_match = image_asset.get("status") in {"mock_generated", "fallback_mock_generated"}
    if requested_size and not skip_raster_match:
        expected = parse_size(requested_size)
        checks.append(
            {
                "name": f"{label}_requested_size_matched",
                "actual": {"width": width, "height": height},
                "expected": expected,
                "pass": width == expected["width"] and height == expected["height"],
            }
        )
        checks.append(
            {
                "name": f"{label}_aspect_ratio_matches_request",
                "actual": aspect_ratio,
                "expected": round(expected["width"] / expected["height"], 4),
                "pass": abs((width / height) - (expected["width"] / expected["height"])) < 0.02
                if width and height
                else False,
            }
        )

    summary = {
        "label": label,
        "local_path": str(local_path),
        "dimensions": {"width": width, "height": height},
        "aspect_ratio": aspect_ratio,
        "mime_type": declared_mime or sniff_mime,
        "file_size_bytes": file_size_bytes,
    }
    return checks, summary


def _load_text_image_consistency_from_export(
    payload: Dict[str, Any], project_root: Path
) -> Dict[str, Any]:
    """Read heuristic consistency block from exported .v2.json (offline, no image gen)."""
    run_id = str(payload.get("run_id") or "")
    content_package = payload.get("content_package") or {}
    candidates: List[Path] = []
    jp = content_package.get("json_path") or ""
    if jp:
        candidates.append(Path(jp))
    if run_id:
        candidates.append(project_root / "outputs" / f"{run_id}.v2.json")
    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            tic = data.get("text_image_consistency")
            if isinstance(tic, dict):
                return tic
    return {}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    default_report = BENCHMARK_DIR / "latest_real_visual_workflow_report.json"
    report_path = Path(os.environ.get("IMAGE_QUALITY_SOURCE", str(default_report)))
    if len(sys.argv) > 1:
        report_path = Path(sys.argv[1])

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    cands = payload.get("cover_candidates")
    if cands:
        assets = list(cands)
    else:
        assets = [payload.get("image_asset", {})]

    all_checks: List[Dict[str, Any]] = []
    summaries: List[Dict[str, Any]] = []
    for i, asset in enumerate(assets):
        if not asset:
            continue
        label = f"asset_{i}" if len(assets) > 1 else "image"
        ch, summ = validate_one_asset(asset, label=label)
        all_checks.extend(ch)
        summaries.append(summ)

    text_image_consistency = _load_text_image_consistency_from_export(payload, PROJECT_ROOT)
    shape_ok, shape_reason = validate_consistency_shape(text_image_consistency)
    all_checks.append(
        {
            "name": "text_image_consistency_export_present",
            "actual": bool(text_image_consistency),
            "expected": True,
            "pass": bool(text_image_consistency),
        }
    )
    all_checks.append(
        {
            "name": "text_image_consistency_shape",
            "actual": shape_reason,
            "expected": "ok",
            "pass": shape_ok,
        }
    )

    out = {
        "generated_at": utc_now(),
        "source_report": str(report_path),
        "image_asset": payload.get("image_asset", assets[0] if assets else {}),
        "cover_candidates_validated": len(summaries),
        "per_asset": summaries,
        "checks": all_checks,
        "text_image_consistency": text_image_consistency or None,
        "all_passed": all(item["pass"] for item in all_checks) if all_checks else False,
    }

    out_path = BENCHMARK_DIR / "latest_image_asset_quality_report.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))

    if not out["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
