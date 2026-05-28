"""Low-cost badcase check: fixture must exhibit low scores and multiple risk categories (no API)."""

import json
import os
import sys

from pydantic import ValidationError

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from langgraph_v2.schemas import CoverVisualReviewPayloadModel  # noqa: E402


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    fixture_path = os.path.join(
        PROJECT_ROOT, "benchmarks", "fixtures", "cover_visual_review_badcase_fixture.json"
    )
    with open(fixture_path, encoding="utf-8") as f:
        raw = json.load(f)

    try:
        model = CoverVisualReviewPayloadModel.model_validate(raw)
        payload = model.model_dump()
    except ValidationError as exc:
        payload = {}
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        raise

    low_scores = payload["overall_score"] < 50
    failed = payload["passed"] is False
    risks = payload["risk_flags"]
    theme_risk = any("theme" in str(x).lower() or "偏题" in str(x) for x in risks)
    title_risk = any("title" in str(x).lower() or "read" in str(x).lower() for x in risks)
    comp_risk = any("composition" in str(x).lower() or "构图" in str(x) or "chaotic" in str(x).lower() for x in risks)
    categories = sum([theme_risk, title_risk, comp_risk])

    checks = [
        {"name": "overall_low", "pass": low_scores, "actual": payload["overall_score"]},
        {"name": "not_passed", "pass": failed, "actual": payload["passed"]},
        {
            "name": "multiple_risk_categories",
            "pass": categories >= 2,
            "actual": risks,
            "expected": ">=2 of theme / title-readability / composition",
        },
    ]

    result = {
        "fixture_path": fixture_path,
        "normalized": payload,
        "checks": checks,
        "all_passed": all(c["pass"] for c in checks),
    }
    out_path = os.path.join(PROJECT_ROOT, "benchmarks", "latest_visual_review_badcase_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
