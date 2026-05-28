import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from statistics import mean
from typing import Any, Dict, List


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
BENCHMARK_DIR = os.path.join(PROJECT_ROOT, "benchmarks")
V1_SCRIPT = os.path.join(BENCHMARK_DIR, "validate_workflow.py")
V2_SCRIPT = os.path.join(BENCHMARK_DIR, "validate_workflow_v2.py")
V1_REPORT = os.path.join(BENCHMARK_DIR, "latest_validation_report.json")
V2_REPORT = os.path.join(BENCHMARK_DIR, "latest_validation_report_v2.json")
COMPARE_REPORT = os.path.join(BENCHMARK_DIR, "latest_compare_report.json")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_report(script_path: str) -> None:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    subprocess.run(
        [sys.executable, script_path],
        cwd=PROJECT_ROOT,
        check=True,
        env=env,
    )


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def summarize_report(label: str, report: Dict[str, Any]) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = report.get("results", [])
    latencies = [item.get("metrics_totals", {}).get("latency_ms", 0.0) for item in results]
    total_tokens = [item.get("metrics_totals", {}).get("total_tokens", 0) for item in results]
    revision_counts = [item.get("revision_count", 0) for item in results]
    export_success = 0
    for item in results:
        for check in item.get("checks", []):
            if check.get("name") in {"json_export_exists", "md_export_exists"} and check.get("pass"):
                export_success += 1
    return {
        "label": label,
        "generated_at": report.get("generated_at"),
        "all_passed": report.get("all_passed", False),
        "total_cases": report.get("total_cases", len(results)),
        "passed_cases": report.get("passed_cases", 0),
        "avg_latency_ms": round(mean(latencies), 2) if latencies else 0.0,
        "avg_total_tokens": round(mean(total_tokens), 2) if total_tokens else 0.0,
        "avg_revision_count": round(mean(revision_counts), 2) if revision_counts else 0.0,
        "export_check_passes": export_success,
    }


def compare_cases(v1: Dict[str, Any], v2: Dict[str, Any]) -> List[Dict[str, Any]]:
    v1_map = {item["case_name"]: item for item in v1.get("results", [])}
    v2_map = {item["case_name"]: item for item in v2.get("results", [])}
    case_names = sorted(set(v1_map) | set(v2_map))
    comparisons: List[Dict[str, Any]] = []
    for case_name in case_names:
        left = v1_map.get(case_name, {})
        right = v2_map.get(case_name, {})
        left_metrics = left.get("metrics_totals", {})
        right_metrics = right.get("metrics_totals", {})
        comparisons.append(
            {
                "case_name": case_name,
                "v1_status": left.get("status"),
                "v2_status": right.get("status"),
                "status_aligned": left.get("status") == right.get("status"),
                "v1_latency_ms": left_metrics.get("latency_ms", 0.0),
                "v2_latency_ms": right_metrics.get("latency_ms", 0.0),
                "latency_delta_ms": round(
                    float(right_metrics.get("latency_ms", 0.0)) - float(left_metrics.get("latency_ms", 0.0)),
                    2,
                ),
                "v1_total_tokens": left_metrics.get("total_tokens", 0),
                "v2_total_tokens": right_metrics.get("total_tokens", 0),
                "token_delta": int(right_metrics.get("total_tokens", 0)) - int(left_metrics.get("total_tokens", 0)),
                "v1_revision_count": left.get("revision_count", 0),
                "v2_revision_count": right.get("revision_count", 0),
            }
        )
    return comparisons


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    run_report(V1_SCRIPT)
    run_report(V2_SCRIPT)

    v1_report = load_json(V1_REPORT)
    v2_report = load_json(V2_REPORT)
    payload = {
        "generated_at": utc_now(),
        "baseline_v1": summarize_report("state_machine_sqlite", v1_report),
        "candidate_v2": summarize_report("langgraph_postgres", v2_report),
        "case_comparisons": compare_cases(v1_report, v2_report),
    }

    with open(COMPARE_REPORT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
