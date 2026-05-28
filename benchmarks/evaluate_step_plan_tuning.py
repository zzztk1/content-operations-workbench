import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from langgraph_v2.engine import LangGraphMediaAgentEngine  # noqa: E402


SCENARIOS: List[Dict[str, Any]] = [
    {
        "name": "content_strategy_packaging",
        "brief": "AI Agent 在内容运营工作台中的价值如何讲清楚",
        "platform": "小红书",
        "style": "种草推荐",
    },
    {
        "name": "project_storytelling",
        "brief": "LangGraph 内容工作流项目怎么讲出工程化亮点",
        "platform": "小红书",
        "style": "经验总结",
    },
    {
        "name": "operator_guidance",
        "brief": "内容运营团队如何把 Agent 工作流讲成系统能力而不是功能堆砌",
        "platform": "小红书",
        "style": "干货拆解",
    },
]

STRUCTURED_NODES = ["research_topic", "write_draft", "review_structured"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_parse_strategy(strategy: str) -> str:
    value = (strategy or "").lower()
    if not value:
        return "unknown"
    if "fallback" in value:
        return "fallback"
    if value.startswith("repair:direct") or value == "direct":
        return "direct"
    if "salvage" in value:
        return "salvage"
    return "other"


def latest_node_payloads(events: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    payloads: Dict[str, Dict[str, Any]] = {}
    for event in events:
        node = event.get("node")
        if node:
            payloads[node] = event.get("payload", {}) or {}
    return payloads


def run_case(engine: LangGraphMediaAgentEngine, scenario: Dict[str, Any], seq: int) -> Dict[str, Any]:
    request_id = f"tuning-{seq:03d}"
    run_id = ""
    first_token_ttft_ms = None
    token_event_count = 0
    final_payload: Dict[str, Any] = {}

    for event in engine.stream_workflow(
        brief=scenario["brief"],
        platform=scenario["platform"],
        style=scenario["style"],
        approval_decision="approve",
        approval_note="tuning-benchmark",
        reviewer_threshold=15,
        max_revisions=0,
        request_id=request_id,
    ):
        event_name = event.get("event")
        data = event.get("data", {})
        if event_name == "start":
            run_id = data.get("run_id", "")
        elif event_name == "token":
            token_event_count += 1
            if first_token_ttft_ms is None:
                first_token_ttft_ms = data.get("ttft_ms")
        elif event_name == "final":
            final_payload = data

    if not run_id:
        raise RuntimeError(f"Missing run_id for scenario {scenario['name']}")

    snapshot = engine.get_run(run_id, thread_id=run_id)
    if not snapshot:
        raise RuntimeError(f"Missing snapshot for run {run_id}")

    state = snapshot["state"]
    node_payloads = latest_node_payloads(state.get("events", []))
    structured = {}
    fallback_nodes = 0
    direct_nodes = 0
    salvage_nodes = 0
    for node in STRUCTURED_NODES:
        strategy = str(node_payloads.get(node, {}).get("parse_strategy", ""))
        bucket = classify_parse_strategy(strategy)
        if bucket == "fallback":
            fallback_nodes += 1
        elif bucket == "direct":
            direct_nodes += 1
        elif bucket == "salvage":
            salvage_nodes += 1
        structured[node] = {
            "parse_strategy": strategy,
            "bucket": bucket,
            "retry_count": int(node_payloads.get(node, {}).get("retry_count", 0) or 0),
            "ttft_ms": node_payloads.get(node, {}).get("ttft_ms"),
            "streamed_chunks": int(node_payloads.get(node, {}).get("streamed_chunks", 0) or 0),
        }

    return {
        "scenario": scenario["name"],
        "brief": scenario["brief"],
        "run_id": run_id,
        "request_id": request_id,
        "status": state.get("status"),
        "trace": state.get("trace", []),
        "revision_count": int(state.get("revision_count", 0) or 0),
        "metrics_totals": state.get("metrics", {}).get("totals", {}),
        "streaming": {
            "token_event_count": token_event_count,
            "first_token_ttft_ms": first_token_ttft_ms,
            "final_status": final_payload.get("status"),
        },
        "structured_nodes": structured,
        "structured_summary": {
            "direct_nodes": direct_nodes,
            "salvage_nodes": salvage_nodes,
            "fallback_nodes": fallback_nodes,
        },
        "content_package": state.get("content_package", {}),
    }


def aggregate(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    totals = [item["metrics_totals"] for item in results]
    ttfts = [
        float(item["streaming"]["first_token_ttft_ms"])
        for item in results
        if isinstance(item["streaming"].get("first_token_ttft_ms"), (int, float))
    ]
    token_events = [item["streaming"]["token_event_count"] for item in results]
    breakdown: Dict[str, Dict[str, int]] = {
        node: {"direct": 0, "salvage": 0, "fallback": 0, "other": 0, "unknown": 0}
        for node in STRUCTURED_NODES
    }
    for item in results:
        for node in STRUCTURED_NODES:
            bucket = item["structured_nodes"][node]["bucket"]
            breakdown[node][bucket] = breakdown[node].get(bucket, 0) + 1

    total_structured_nodes = len(results) * len(STRUCTURED_NODES)
    direct_count = sum(item["structured_summary"]["direct_nodes"] for item in results)
    salvage_count = sum(item["structured_summary"]["salvage_nodes"] for item in results)
    fallback_count = sum(item["structured_summary"]["fallback_nodes"] for item in results)

    return {
        "scenario_count": len(results),
        "avg_latency_ms": round(mean(float(item.get("latency_ms", 0.0)) for item in totals), 2),
        "avg_prompt_tokens": round(mean(int(item.get("prompt_tokens", 0)) for item in totals), 2),
        "avg_completion_tokens": round(mean(int(item.get("completion_tokens", 0)) for item in totals), 2),
        "avg_total_tokens": round(mean(int(item.get("total_tokens", 0)) for item in totals), 2),
        "avg_ttft_ms": round(mean(ttfts), 2) if ttfts else None,
        "avg_token_event_count": round(mean(token_events), 2) if token_events else 0.0,
        "structured_output": {
            "node_count": total_structured_nodes,
            "direct_count": direct_count,
            "salvage_count": salvage_count,
            "fallback_count": fallback_count,
            "direct_rate": round(direct_count / total_structured_nodes, 4) if total_structured_nodes else 0.0,
            "salvage_rate": round(salvage_count / total_structured_nodes, 4) if total_structured_nodes else 0.0,
            "fallback_rate": round(fallback_count / total_structured_nodes, 4) if total_structured_nodes else 0.0,
        },
        "parse_breakdown": breakdown,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    os.environ["PYTHONUTF8"] = "1"

    results: List[Dict[str, Any]] = []
    with LangGraphMediaAgentEngine() as engine:
        for index, scenario in enumerate(SCENARIOS, start=1):
            results.append(run_case(engine, scenario, index))

    payload = {
        "generated_at": utc_now(),
        "label": args.label,
        "mode": "real_step_plan_streaming",
        "scenarios": SCENARIOS,
        "results": results,
        "summary": aggregate(results),
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
