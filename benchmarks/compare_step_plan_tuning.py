import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def diff(after_value: float | int | None, before_value: float | int | None) -> float | None:
    if after_value is None or before_value is None:
        return None
    return round(float(after_value) - float(before_value), 2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    before = load_json(args.before)
    after = load_json(args.after)
    before_summary = before.get("summary", {})
    after_summary = after.get("summary", {})
    before_structured = before_summary.get("structured_output", {})
    after_structured = after_summary.get("structured_output", {})

    payload = {
        "generated_at": utc_now(),
        "before_file": args.before,
        "after_file": args.after,
        "before_label": before.get("label"),
        "after_label": after.get("label"),
        "metrics_compare": {
            "avg_latency_ms": {
                "before": before_summary.get("avg_latency_ms"),
                "after": after_summary.get("avg_latency_ms"),
                "delta": diff(after_summary.get("avg_latency_ms"), before_summary.get("avg_latency_ms")),
            },
            "avg_prompt_tokens": {
                "before": before_summary.get("avg_prompt_tokens"),
                "after": after_summary.get("avg_prompt_tokens"),
                "delta": diff(after_summary.get("avg_prompt_tokens"), before_summary.get("avg_prompt_tokens")),
            },
            "avg_completion_tokens": {
                "before": before_summary.get("avg_completion_tokens"),
                "after": after_summary.get("avg_completion_tokens"),
                "delta": diff(after_summary.get("avg_completion_tokens"), before_summary.get("avg_completion_tokens")),
            },
            "avg_total_tokens": {
                "before": before_summary.get("avg_total_tokens"),
                "after": after_summary.get("avg_total_tokens"),
                "delta": diff(after_summary.get("avg_total_tokens"), before_summary.get("avg_total_tokens")),
            },
            "avg_ttft_ms": {
                "before": before_summary.get("avg_ttft_ms"),
                "after": after_summary.get("avg_ttft_ms"),
                "delta": diff(after_summary.get("avg_ttft_ms"), before_summary.get("avg_ttft_ms")),
            },
        },
        "structured_compare": {
            "direct_rate": {
                "before": before_structured.get("direct_rate"),
                "after": after_structured.get("direct_rate"),
                "delta": diff(after_structured.get("direct_rate"), before_structured.get("direct_rate")),
            },
            "salvage_rate": {
                "before": before_structured.get("salvage_rate"),
                "after": after_structured.get("salvage_rate"),
                "delta": diff(after_structured.get("salvage_rate"), before_structured.get("salvage_rate")),
            },
            "fallback_rate": {
                "before": before_structured.get("fallback_rate"),
                "after": after_structured.get("fallback_rate"),
                "delta": diff(after_structured.get("fallback_rate"), before_structured.get("fallback_rate")),
            },
        },
        "before_parse_breakdown": before_summary.get("parse_breakdown", {}),
        "after_parse_breakdown": after_summary.get("parse_breakdown", {}),
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
