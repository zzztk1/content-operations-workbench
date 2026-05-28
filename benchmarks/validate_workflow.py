import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from agent_graph import MediaAgentGraph  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_case(engine: MediaAgentGraph, case: dict) -> dict:
    result = engine.run_workflow(
        brief=case["brief"],
        platform=case["platform"],
        style=case["style"],
        approval_decision=case["approval"],
        reviewer_threshold=case["reviewer_threshold"],
        max_revisions=case["max_revisions"],
    )
    state = result["state"]
    metrics = result["metrics"]["totals"]
    package = state.get("content_package", {})
    passed = True
    checks = []

    expected_status = case["expected_status"]
    checks.append(
        {
            "name": "expected_status",
            "actual": state["status"],
            "expected": expected_status,
            "pass": state["status"] == expected_status,
        }
    )

    if expected_status == "completed":
        json_path = package.get("json_path", "")
        md_path = package.get("markdown_path", "")
        checks.append(
            {
                "name": "json_export_exists",
                "actual": os.path.exists(json_path),
                "expected": True,
                "pass": os.path.exists(json_path),
            }
        )
        checks.append(
            {
                "name": "md_export_exists",
                "actual": os.path.exists(md_path),
                "expected": True,
                "pass": os.path.exists(md_path),
            }
        )
    else:
        checks.append(
            {
                "name": "no_export_required",
                "actual": True,
                "expected": True,
                "pass": True,
            }
        )

    checks.append(
        {
            "name": "trace_has_core_nodes",
            "actual": state.get("trace", []),
            "expected": ["research", "writer", "reviewer", "approval"],
            "pass": all(
                node in state.get("trace", [])
                for node in ["research", "writer", "reviewer", "approval"]
            ),
        }
    )

    checks.append(
        {
            "name": "metrics_generated",
            "actual": metrics,
            "expected": "latency_ms and token stats exist",
            "pass": "latency_ms" in metrics and "total_tokens" in metrics,
        }
    )

    for check in checks:
        if not check["pass"]:
            passed = False

    return {
        "case_name": case["name"],
        "run_id": result["run_id"],
        "status": state["status"],
        "passed": passed,
        "checks": checks,
        "metrics_totals": metrics,
        "revision_count": state.get("revision_count", 0),
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    os.environ["LLM_MOCK"] = "true"
    engine = MediaAgentGraph()

    cases = [
        {
            "name": "approve_path",
            "brief": "AI Agent 内容运营选题与发布建议",
            "platform": "小红书",
            "style": "种草推荐",
            "approval": "approve",
            "reviewer_threshold": 21,
            "max_revisions": 2,
            "expected_status": "completed",
        },
        {
            "name": "needs_edit_path",
            "brief": "B2B SaaS 运营复盘内容框架",
            "platform": "微信公众号",
            "style": "知识科普",
            "approval": "needs_edit",
            "reviewer_threshold": 21,
            "max_revisions": 2,
            "expected_status": "needs_manual_edit",
        },
        {
            "name": "reject_path",
            "brief": "抖音短视频选题测试",
            "platform": "抖音",
            "style": "测评对比",
            "approval": "reject",
            "reviewer_threshold": 21,
            "max_revisions": 2,
            "expected_status": "rejected",
        },
    ]

    results = [run_case(engine, case) for case in cases]
    summary = {
        "generated_at": utc_now(),
        "total_cases": len(results),
        "passed_cases": sum(1 for r in results if r["passed"]),
        "all_passed": all(r["passed"] for r in results),
        "results": results,
    }

    out_path = os.path.join(PROJECT_ROOT, "benchmarks", "latest_validation_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
