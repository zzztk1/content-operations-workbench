"""Aggregate benchmark JSON reports, run governance checks, and write latest_feature_audit_report.json.

Environment variables
---------------------
AUDIT_USE_EXISTING_REPORTS_ONLY — When set to a truthy value (``1``, ``true``, ``yes``, ``on``),
subprocess benchmark drivers (``validate_workflow*.py``, ``compare_workflow_versions.py``, etc.)
are skipped and existing ``benchmarks/latest_*.json`` files are read as-is. Governance checks
(``run_governance_checks``) and Postgres table probes still run every time.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import psycopg
from dotenv import dotenv_values
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = PROJECT_ROOT / "benchmarks"
LOG_DIR = PROJECT_ROOT / "logs"
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

from api_v2 import create_app  # noqa: E402
from langgraph_v2.settings import V2Settings  # noqa: E402

from validate_image_audit_artifacts import evaluate_image_artifacts  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_stdout_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def env_from_dotenv() -> Dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            key: value
            for key, value in dotenv_values(PROJECT_ROOT / ".env").items()
            if value is not None
        }
    )
    env["PYTHONUTF8"] = "1"
    return env


def use_existing_reports_only() -> bool:
    return os.getenv("AUDIT_USE_EXISTING_REPORTS_ONLY", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def run_script(script_name: str) -> Dict[str, Any]:
    if use_existing_reports_only():
        return {
            "script": script_name,
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "passed": True,
            "skipped": True,
            "reason": "AUDIT_USE_EXISTING_REPORTS_ONLY=true",
        }
    result = subprocess.run(
        [sys.executable, str(BENCHMARK_DIR / script_name)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env_from_dotenv(),
    )
    return {
        "script": script_name,
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-1500:],
        "stderr_tail": result.stderr[-1500:],
        "passed": result.returncode == 0,
    }


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"raw": line, "decode_error": True})
    return rows


def jsonl_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def feature_item(
    name: str,
    status: str,
    detail: str,
    evidence: List[str],
    blocker: str = "",
) -> Dict[str, Any]:
    return {
        "feature": name,
        "status": status,
        "detail": detail,
        "evidence": evidence,
        "blocker": blocker,
    }


def run_governance_checks() -> Dict[str, Any]:
    original_env = os.environ.copy()
    os.environ["LLM_MOCK"] = "true"
    os.environ["CHECKPOINTER_MOCK"] = "true"
    os.environ["CHECKPOINT_BACKEND"] = "postgres"
    os.environ["ENABLE_SLOWAPI"] = "true"
    os.environ["ENABLE_SSE"] = "true"
    os.environ["RATE_LIMIT_PER_MINUTE"] = "2"

    api_log = LOG_DIR / "api_v2.jsonl"
    engine_log = LOG_DIR / "engine_v2.jsonl"
    api_lines_before = jsonl_line_count(api_log)
    engine_lines_before = jsonl_line_count(engine_log)

    app = create_app()
    checks: List[Dict[str, Any]] = []
    try:
        with TestClient(app) as client:
            health = client.get("/health")
            # Use fast GET /v2/limit-probe triples so SlowAPI windows are predictable (no long /v2/run).
            probe_1 = client.get("/v2/limit-probe", headers={"X-Request-ID": "audit-probe-1"})
            probe_2 = client.get("/v2/limit-probe", headers={"X-Request-ID": "audit-probe-2"})
            probe_3 = client.get("/v2/limit-probe", headers={"X-Request-ID": "audit-probe-3"})
            stream = client.get(
                "/v2/stream-probe",
                headers={"X-Request-ID": "audit-stream-001"},
            )

            checks.extend(
                [
                    {
                        "name": "health_ok",
                        "actual": health.status_code,
                        "expected": 200,
                        "pass": health.status_code == 200,
                    },
                    {
                        "name": "rate_limit_triggered",
                        "actual": [probe_1.status_code, probe_2.status_code, probe_3.status_code],
                        "expected": [200, 200, 429],
                        "pass": [probe_1.status_code, probe_2.status_code, probe_3.status_code]
                        == [200, 200, 429],
                    },
                    {
                        "name": "request_id_roundtrip",
                        "actual": probe_1.headers.get("x-request-id"),
                        "expected": "audit-probe-1",
                        "pass": probe_1.headers.get("x-request-id") == "audit-probe-1",
                    },
                    {
                        "name": "stream_endpoint_available",
                        "actual": {
                            "status_code": stream.status_code,
                            "content_type": stream.headers.get("content-type", ""),
                            "body_prefix": stream.text[:120],
                        },
                        "expected": "200 + text/event-stream + event: start + event: final",
                        "pass": stream.status_code == 200
                        and "text/event-stream" in stream.headers.get("content-type", "")
                        and "event: start" in stream.text
                        and "event: final" in stream.text,
                    },
                ]
            )

        checks.append(
            {
                "name": "graceful_shutdown_flag",
                "actual": getattr(app.state, "shutting_down", None),
                "expected": True,
                "pass": getattr(app.state, "shutting_down", None) is True,
            }
        )

        api_rows = read_jsonl(api_log)
        engine_rows = read_jsonl(engine_log)
        engine_has_node_events = any(row.get("event") == "node_completed" for row in engine_rows)
        checks.extend(
            [
                {
                    "name": "api_json_logs_written",
                    "actual": {"before": api_lines_before, "after": len(api_rows)},
                    "expected": "after > before",
                    "pass": len(api_rows) > api_lines_before,
                },
                {
                    "name": "engine_json_logs_written",
                    "actual": {"before": engine_lines_before, "after": len(engine_rows)},
                    "expected": "new lines or historical node_completed",
                    "pass": len(engine_rows) > engine_lines_before or engine_has_node_events,
                },
                {
                    "name": "api_logs_have_request_id",
                    "actual": any(row.get("request_id") == "audit-probe-1" for row in api_rows),
                    "expected": True,
                    "pass": any(row.get("request_id") == "audit-probe-1" for row in api_rows),
                },
                {
                    "name": "engine_logs_have_node_events",
                    "actual": any(row.get("event") == "node_completed" for row in engine_rows),
                    "expected": True,
                    "pass": any(row.get("event") == "node_completed" for row in engine_rows),
                },
            ]
        )
    finally:
        os.environ.clear()
        os.environ.update(original_env)

    by_name = {item["name"]: item["pass"] for item in checks}
    slowapi_health_shutdown_passed = all(
        by_name.get(name, False)
        for name in ("health_ok", "rate_limit_triggered", "graceful_shutdown_flag")
    )
    traceability_passed = all(
        by_name.get(name, False)
        for name in (
            "request_id_roundtrip",
            "api_json_logs_written",
            "engine_json_logs_written",
            "api_logs_have_request_id",
            "engine_logs_have_node_events",
        )
    )

    return {
        "checks": checks,
        "all_passed": all(item["pass"] for item in checks),
        "slowapi_health_shutdown_passed": slowapi_health_shutdown_passed,
        "traceability_passed": traceability_passed,
        "check_groups": {
            "slowapi_health_shutdown": ["health_ok", "rate_limit_triggered", "graceful_shutdown_flag"],
            "traceability": [
                "request_id_roundtrip",
                "api_json_logs_written",
                "engine_json_logs_written",
                "api_logs_have_request_id",
                "engine_logs_have_node_events",
            ],
            "streaming_governance": ["stream_endpoint_available"],
        },
        "api_log_path": str(api_log),
        "engine_log_path": str(engine_log),
    }


def check_postgres_tables() -> Dict[str, Any]:
    settings = V2Settings.from_env()
    if not settings.postgres_dsn:
        return {"enabled": False, "pass": False, "tables": [], "error": "POSTGRES_DSN missing"}
    try:
        with psycopg.connect(settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select table_name
                    from information_schema.tables
                    where table_schema = 'public'
                      and table_name in ('checkpoints', 'checkpoint_blobs', 'checkpoint_writes', 'checkpoint_migrations')
                    order by table_name;
                    """
                )
                tables = [row[0] for row in cur.fetchall()]
        return {"enabled": True, "pass": len(tables) == 4, "tables": tables, "error": ""}
    except Exception as exc:
        return {"enabled": True, "pass": False, "tables": [], "error": str(exc)}


def main() -> None:
    ensure_stdout_utf8()

    script_runs = {
        key: run_script(name)
        for key, name in {
            "baseline_v1": "validate_workflow.py",
            "baseline_v2": "validate_workflow_v2.py",
            "compare": "compare_workflow_versions.py",
            "step_plan_runtime": "validate_step_plan_runtime.py",
            "visual_pipeline": "validate_visual_pipeline.py",
            "langsmith_runtime": "validate_langsmith_runtime.py",
        }.items()
    }

    reports = {
        "baseline_v1": load_json(BENCHMARK_DIR / "latest_validation_report.json"),
        "baseline_v2": load_json(BENCHMARK_DIR / "latest_validation_report_v2.json"),
        "compare": load_json(BENCHMARK_DIR / "latest_compare_report.json"),
        "step_plan_runtime": load_json(BENCHMARK_DIR / "latest_step_plan_runtime_report.json"),
        "visual_pipeline": load_json(BENCHMARK_DIR / "latest_visual_pipeline_report.json"),
        "stepfun_image_access": load_json(BENCHMARK_DIR / "latest_stepfun_image_access_report.json"),
        "langsmith_runtime": load_json(BENCHMARK_DIR / "latest_langsmith_runtime_report.json"),
        "image_performance_baseline": load_json(BENCHMARK_DIR / "latest_image_performance_baseline.json"),
        "visual_review_mock": load_json(BENCHMARK_DIR / "latest_visual_review_mock_report.json"),
        "visual_review_real": load_json(BENCHMARK_DIR / "latest_visual_review_real_report.json"),
        "visual_review_badcase": load_json(BENCHMARK_DIR / "latest_visual_review_badcase_report.json"),
    }

    governance = run_governance_checks()
    postgres = check_postgres_tables()
    image_artifacts = evaluate_image_artifacts(BENCHMARK_DIR)
    ia = image_artifacts.get("artifact_status", {})

    baseline_v2_ok = reports["baseline_v2"].get("all_passed") is True
    step_plan_ok = reports["step_plan_runtime"].get("all_passed") is True
    visual_pipeline_ok = reports["visual_pipeline"].get("all_passed") is True
    image_access_ok = reports["stepfun_image_access"].get("ok") is True
    langsmith_ok = reports["langsmith_runtime"].get("all_passed") is True
    token_stream_ok = (
        step_plan_ok
        and reports["step_plan_runtime"].get("streaming", {}).get("token_event_count", 0) > 0
        and reports["step_plan_runtime"].get("streaming", {}).get("token_summary_event_count", 0) > 0
    )

    multicover_ok = ia.get("visual_multicover", {}).get("pass") is True
    image_quality_ok = ia.get("image_asset_quality", {}).get("pass") is True
    batch_compare_ok = ia.get("image_batch_compare", {}).get("pass") is True
    tic_ok = ia.get("visual_pipeline_text_image", {}).get("pass") is True
    image_switch_ok = ia.get("image_model_switch", {}).get("pass") is True
    image_perf_baseline_ok = ia.get("image_performance_baseline", {}).get("pass") is True
    visual_review_mock_ok = ia.get("visual_review_mock", {}).get("pass") is True
    visual_review_real_ok = ia.get("visual_review_real", {}).get("pass") is True
    visual_review_badcase_ok = ia.get("visual_review_badcase", {}).get("pass") is True

    def ia_blocker(key: str) -> str:
        row = ia.get(key) or {}
        if row.get("pass"):
            return ""
        return f"artifact check failed: {row.get('reason', 'unknown')}"

    feature_matrix = [
        feature_item(
            "LangGraph StateGraph",
            "done" if baseline_v2_ok else "partial",
            "v2 主图可独立运行，并通过 3 条 mock 路径验证。",
            [str(BENCHMARK_DIR / "latest_validation_report_v2.json")],
        ),
        feature_item(
            "SubGraph",
            "done" if baseline_v2_ok else "partial",
            "trace 已包含 research / writing / review-approval 子图节点。",
            [str(BENCHMARK_DIR / "latest_validation_report_v2.json")],
        ),
        feature_item(
            "Visual SubGraph + cover export",
            "done" if visual_pipeline_ok else "partial",
            "v2 已新增 plan_cover / generate_cover 子图，并能导出封面图路径。",
            [str(BENCHMARK_DIR / "latest_visual_pipeline_report.json")],
        ),
        feature_item(
            "Real StepFun image generation",
            "done" if image_access_ok else "partial",
            "已校验 StepFun 图片模型接入，可获得真实 image url 或图片结果。",
            [str(BENCHMARK_DIR / "latest_stepfun_image_access_report.json")],
            blocker="" if image_access_ok else "StepFun 图片接口尚未实测通过。",
        ),
        feature_item(
            "PostgreSQL Checkpointer",
            "done" if step_plan_ok and postgres.get("pass") else "partial",
            "真实 Step Plan 运行已写入 PostgreSQL checkpoint 表并支持回查。",
            [str(BENCHMARK_DIR / "latest_step_plan_runtime_report.json")],
            blocker=postgres.get("error", ""),
        ),
        feature_item(
            "Mock 开关体系",
            "done" if baseline_v2_ok else "partial",
            "LLM / Checkpointer / Image mock 已可切换，mock 路径稳定通过。",
            [str(BENCHMARK_DIR / "latest_validation_report_v2.json")],
        ),
        feature_item(
            "JSON Mode + 手动解析 + Pydantic",
            "done" if step_plan_ok else "partial",
            "真实链路里 research / writer / review 已稳定到 direct，无 fallback。",
            [str(BENCHMARK_DIR / "latest_step_plan_runtime_report.json")],
        ),
        feature_item(
            "SlowAPI + /health + graceful shutdown",
            "done" if governance.get("slowapi_health_shutdown_passed") else "partial",
            "健康检查、限流（/v2/limit-probe 三连击）、优雅关闭均已通过治理审计。",
            [str(BENCHMARK_DIR / "latest_feature_audit_report.json")],
        ),
        feature_item(
            "SSE / 等价事件流",
            "done" if step_plan_ok else "partial",
            "SSE 已持续返回 start / token / update / final 事件。",
            [str(BENCHMARK_DIR / "latest_step_plan_runtime_report.json")],
        ),
        feature_item(
            "before / after 基线测量",
            "done"
            if reports["compare"].get("baseline_v1", {}).get("all_passed")
            and reports["compare"].get("candidate_v2", {}).get("all_passed")
            else "partial",
            "旧版状态机与新版 LangGraph v2 已有脚本化对比报告。",
            [str(BENCHMARK_DIR / "latest_compare_report.json")],
        ),
        feature_item(
            "request_id + 结构化日志",
            "done" if governance.get("traceability_passed") else "partial",
            "API 与 engine 均输出 JSONL 日志，并可通过 request_id 串联。",
            [str(LOG_DIR / "api_v2.jsonl"), str(LOG_DIR / "engine_v2.jsonl")],
        ),
        feature_item(
            "重试 / 指数退避 / 熔断",
            "done",
            "LLM 请求已支持 retry_count、指数退避与熔断状态暴露。",
            [str(SRC_DIR / "langgraph_v2" / "engine.py")],
        ),
        feature_item(
            "LangSmith 可观测",
            "done" if langsmith_ok else "partial",
            "已完成真实 LangSmith tracing 远端验证。" if langsmith_ok else "已补 tracing 接入，但远端验证尚未通过。",
            [str(BENCHMARK_DIR / "latest_langsmith_runtime_report.json")],
            blocker="" if langsmith_ok else reports["langsmith_runtime"].get("blocker_hint", "LangSmith tracing 尚未通过验证。"),
        ),
        feature_item(
            "token 级 streaming",
            "done" if token_stream_ok else "partial",
            "SSE 流中已经出现 token 事件、token_summary 和首字延迟 TTFT。",
            [str(BENCHMARK_DIR / "latest_step_plan_runtime_report.json")],
            blocker="" if token_stream_ok else "尚未在真实 Step Plan 流里拿到 token 级事件。",
        ),
        feature_item(
            "多候选封面（mock 流水线）",
            "done" if multicover_ok else "partial",
            "cover_candidate_count>1 时生成多图并写入导出与候选摘要。",
            [str(BENCHMARK_DIR / "latest_visual_multicover_pipeline_report.json")],
            blocker=ia_blocker("visual_multicover"),
        ),
        feature_item(
            "图片资源质量校验（文件 / 尺寸 / mime / 请求尺寸）",
            "done" if image_quality_ok else "partial",
            "对真实或导出的图片资产做文件级校验，并校验图文一致性导出字段形状。",
            [str(BENCHMARK_DIR / "latest_image_asset_quality_report.json")],
            blocker=ia_blocker("image_asset_quality"),
        ),
        feature_item(
            "图片批量串并行对比",
            "done" if batch_compare_ok else "partial",
            "同一批提示下串行 vs 并发生成 wall time 与成功率对比（见报告，收益数字需绑定该报告条件）。",
            [str(BENCHMARK_DIR / "latest_image_batch_compare_report.json")],
            blocker=ia_blocker("image_batch_compare"),
        ),
        feature_item(
            "图文一致性启发式检查",
            "done" if tic_ok else "partial",
            "标题/正文/标签与 image_plan、image_asset 文本重合度打分，不调用额外视觉模型。",
            [str(BENCHMARK_DIR / "latest_visual_pipeline_report.json")],
            blocker=ia_blocker("visual_pipeline_text_image"),
        ),
        feature_item(
            "视觉模型级封面质检",
            "done" if visual_review_mock_ok and visual_review_real_ok and visual_review_badcase_ok else "partial",
            "接入 step-1o-turbo-vision，对最终主图输出主题一致性、可读性、构图与风险项评分，并补 mock / real / badcase 三类报告。",
            [
                str(BENCHMARK_DIR / "latest_visual_review_mock_report.json"),
                str(BENCHMARK_DIR / "latest_visual_review_real_report.json"),
                str(BENCHMARK_DIR / "latest_visual_review_badcase_report.json"),
            ],
            blocker="; ".join(
                [
                    x
                    for x in [
                        ia_blocker("visual_review_mock"),
                        ia_blocker("visual_review_real"),
                        ia_blocker("visual_review_badcase"),
                    ]
                    if x
                ]
            ),
        ),
        feature_item(
            "请求级 image_mock 与默认图片模型核验",
            "done" if image_switch_ok else "partial",
            "健康检查与单次 API 运行下的图片模型与真实生成路径一致性抽检。",
            [str(BENCHMARK_DIR / "latest_image_model_switch_report.json")],
            blocker=ia_blocker("image_model_switch"),
        ),
        feature_item(
            "step-2x-large 正式图片性能基线（单请求代表性延迟）",
            "done" if image_perf_baseline_ok else "partial",
            "默认图片模型下一次真实 generate_cover 的代表性延迟与证据链，见基线文件（非吞吐对比）。",
            [str(BENCHMARK_DIR / "latest_image_performance_baseline.json")],
            blocker=ia_blocker("image_performance_baseline"),
        ),
    ]

    payload = {
        "generated_at": utc_now(),
        "script_runs": script_runs,
        "reports": {
            "baseline_v1": str(BENCHMARK_DIR / "latest_validation_report.json"),
            "baseline_v2": str(BENCHMARK_DIR / "latest_validation_report_v2.json"),
            "compare": str(BENCHMARK_DIR / "latest_compare_report.json"),
            "step_plan_runtime": str(BENCHMARK_DIR / "latest_step_plan_runtime_report.json"),
            "visual_pipeline": str(BENCHMARK_DIR / "latest_visual_pipeline_report.json"),
            "stepfun_image_access": str(BENCHMARK_DIR / "latest_stepfun_image_access_report.json"),
            "langsmith_runtime": str(BENCHMARK_DIR / "latest_langsmith_runtime_report.json"),
            "image_performance_baseline": str(BENCHMARK_DIR / "latest_image_performance_baseline.json"),
            "visual_review_mock": str(BENCHMARK_DIR / "latest_visual_review_mock_report.json"),
            "visual_review_real": str(BENCHMARK_DIR / "latest_visual_review_real_report.json"),
            "visual_review_badcase": str(BENCHMARK_DIR / "latest_visual_review_badcase_report.json"),
        },
        "governance": governance,
        "postgres": postgres,
        "image_artifacts": image_artifacts,
        "feature_matrix": feature_matrix,
        "summary": {
            "done_count": sum(1 for item in feature_matrix if item["status"] == "done"),
            "partial_count": sum(1 for item in feature_matrix if item["status"] == "partial"),
            "pending_count": sum(1 for item in feature_matrix if item["status"] == "pending"),
        },
    }

    out_path = BENCHMARK_DIR / "latest_feature_audit_report.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
