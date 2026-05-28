import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from langgraph_v2 import LangGraphMediaAgentEngine  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_case(engine: LangGraphMediaAgentEngine, case: dict) -> dict:
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
    checks = []

    checks.append(
        {
            "name": "expected_status",
            "actual": state["status"],
            "expected": case["expected_status"],
            "pass": state["status"] == case["expected_status"],
        }
    )

    if case["expected_status"] == "completed":
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

    trace = state.get("trace", [])
    checks.append(
        {
            "name": "trace_has_subgraph_nodes",
            "actual": trace,
            "expected": [
                "brief_intake",
                "research_topic",
                "write_draft",
                "review_structured",
                "approval_gate_or_export",
            ],
            "pass": all(
                node in trace
                for node in ["brief_intake", "research_topic", "write_draft", "review_structured"]
            ),
        }
    )
    checks.append(
        {
            "name": "rewrite_loop_supported",
            "actual": state.get("revision_count", 0),
            "expected": ">= 1 in mock mode default path",
            "pass": state.get("revision_count", 0) >= 1,
        }
    )
    checks.append(
        {
            "name": "metrics_generated",
            "actual": metrics,
            "expected": "latency_ms and total_tokens exist",
            "pass": "latency_ms" in metrics and "total_tokens" in metrics,
        }
    )

    passed = all(check["pass"] for check in checks)
    return {
        "case_name": case["name"],
        "run_id": result["run_id"],
        "status": state["status"],
        "passed": passed,
        "checks": checks,
        "metrics_totals": metrics,
        "revision_count": state.get("revision_count", 0),
        "graph_version": state.get("graph_version", ""),
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    os.environ["LLM_MOCK"] = "true"
    os.environ["CHECKPOINTER_MOCK"] = "true"
    os.environ["CHECKPOINT_BACKEND"] = "postgres"

    cases = [
        {
            "name": "approve_path",
            "brief": "AI产品经理求职内容选题与发布建议",
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

    with LangGraphMediaAgentEngine() as engine:
        results = [run_case(engine, case) for case in cases]

    summary = {
        "generated_at": utc_now(),
        "graph_version": "v2-draft",
        "total_cases": len(results),
        "passed_cases": sum(1 for item in results if item["passed"]),
        "all_passed": all(item["passed"] for item in results),
        "results": results,
    }

    out_path = os.path.join(PROJECT_ROOT, "benchmarks", "latest_validation_report_v2.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
