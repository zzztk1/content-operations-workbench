from __future__ import annotations

import asyncio
import copy
import html
import json
import mimetypes
import os
import re
import time
import uuid
from base64 import b64decode, b64encode
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from threading import Thread, local
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from openai import OpenAI

from agent_graph import KnowledgeBase

from .image_text_consistency import compute_text_image_consistency
from .layout import DEFAULT_GRAPH_LAYOUT
from .metrics_context import MetricsContext
from .observability import get_struct_logger, traceable
from .parsers import parse_and_validate_schema
from .platform_rules import get_platform_rule
from .schemas import (
    ApprovalPayloadModel,
    DraftPayloadModel,
    ExportPackageModel,
    CoverVisualReviewPayloadModel,
    ImageAssetModel,
    ImagePlanModel,
    ResearchPayloadModel,
    ResearchTopicModel,
    ReviewPayloadModel,
)
from .settings import V2Settings
from .state import MediaAgentState

load_dotenv()


def _normalize_export_formats(raw: Any) -> List[str]:
    if not raw:
        return ["json", "md"]
    order: List[str] = []
    for item in raw:
        key = str(item).lower().strip()
        if key in ("markdown",):
            key = "md"
        if key in ("text",):
            key = "txt"
        if key not in ("json", "md", "txt", "html"):
            continue
        if key not in order:
            order.append(key)
    return order if order else ["json", "md"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_file_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return stem[:80] or uuid.uuid4().hex[:12]


def _default_metrics() -> Dict[str, Any]:
    return MetricsContext.empty().to_dict()


def _copy_metrics(metrics: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return MetricsContext.from_payload(metrics or _default_metrics()).to_dict()


class LangGraphMediaAgentEngine:
    def __init__(self, settings: Optional[V2Settings] = None) -> None:
        self.settings = settings or V2Settings.from_env()
        self.layout = DEFAULT_GRAPH_LAYOUT
        self.kb = KnowledgeBase()
        self._stack = ExitStack()
        self.logger = get_struct_logger(
            "engine_v2",
            str(Path(__file__).resolve().parents[2] / "logs" / "engine_v2.jsonl"),
        ).bind(graph_version=self.layout.version)
        self.client = self._build_client()
        self.image_client = self._build_image_client()
        self.vision_client = self._build_vision_client()
        self.checkpointer = self._build_checkpointer()
        self._llm_failure_count = 0
        self._circuit_open_until = 0.0
        self._thread_local = local()
        self._image_output_dir_cache: Optional[Path] = None
        self._cancel_checker: Optional[Callable[[str], bool]] = None
        self._run_cache: Dict[str, Dict[str, Any]] = {}
        self.graph = self._build_graph()
        self._continuation_graph = self._build_continuation_graph()

    @property
    def is_step_plan(self) -> bool:
        return "step_plan" in (self.settings.llm_api_base or "").lower()

    def close(self) -> None:
        self._stack.close()

    def __enter__(self) -> "LangGraphMediaAgentEngine":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def set_cancel_checker(self, checker: Optional[Callable[[str], bool]]) -> None:
        self._cancel_checker = checker

    def _remember_run(self, state: Dict[str, Any]) -> None:
        run_id = str(state.get("run_id") or "")
        if run_id:
            self._run_cache[run_id] = copy.deepcopy(state)

    def update_publish_overrides(
        self,
        run_id: str,
        image_assets: Optional[List[Dict[str, Any]]] = None,
        cover_asset: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        current = self.get_run(run_id, run_id)
        if not current:
            return None
        state = copy.deepcopy(current["state"])
        if image_assets is not None:
            state["image_assets"] = [dict(asset) for asset in image_assets]
            if state["image_assets"]:
                state["image_asset"] = dict(state["image_assets"][0])
        if cover_asset is not None:
            state["image_asset"] = dict(cover_asset)
            assets = list(state.get("image_assets") or [])
            if assets:
                assets[0] = {**dict(assets[0]), **dict(cover_asset)}
            else:
                assets = [dict(cover_asset)]
            state["image_assets"] = assets
        publish_package = dict(state.get("publish_package") or {})
        if state.get("image_assets") is not None:
            publish_package["image_assets"] = copy.deepcopy(state.get("image_assets") or [])
        state["publish_package"] = publish_package
        self._remember_run(state)
        return {
            "run_id": run_id,
            "state": copy.deepcopy(state),
            "status": state.get("status", "unknown"),
        }

    def _is_cancelled(self, state: MediaAgentState) -> bool:
        run_id = str(state.get("run_id") or "")
        return bool(run_id and self._cancel_checker and self._cancel_checker(run_id))

    def _cancel_updates(self, state: MediaAgentState, node_name: str) -> Dict[str, Any]:
        started = time.perf_counter()
        updates = {"status": "cancelled"}
        updates.update(
            self._record_node(
                state,
                node_name,
                started,
                error="cancelled_by_user",
                event_payload={"reason": "stop_requested"},
            )
        )
        return updates

    def _cancel_aware(self, node_name: str, fn: Callable[[MediaAgentState], Dict[str, Any]]):
        def wrapped(state: MediaAgentState) -> Dict[str, Any]:
            if self._is_cancelled(state):
                return self._cancel_updates(state, node_name)
            return fn(state)

        return wrapped

    def _build_client(self) -> Optional[OpenAI]:
        if self.settings.llm_mock:
            return None
        missing = []
        if not self.settings.llm_api_key:
            missing.append("STEPFUN_API_KEY")
        if not self.settings.llm_api_base:
            missing.append("STEPFUN_API_BASE")
        if not self.settings.llm_model:
            missing.append("STEPFUN_MODEL")
        if missing:
            raise RuntimeError(
                "真实阶跃星辰模型链路缺少环境变量："
                + ", ".join(missing)
                + "。如果只是本地调试，请先设置 LLM_MOCK=true。"
            )
        return OpenAI(
            api_key=self.settings.llm_api_key,
            base_url=self.settings.llm_api_base,
        )

    def _build_image_client(self) -> Optional[OpenAI]:
        if not self.settings.image_api_key:
            self.logger.info("image_client_disabled", reason="missing_image_api_key")
            return None
        return OpenAI(
            api_key=self.settings.image_api_key,
            base_url=self.settings.image_api_base,
        )

    def _build_vision_client(self) -> Optional[OpenAI]:
        if not self.settings.vision_api_key:
            self.logger.info("vision_client_disabled", reason="missing_vision_api_key")
            return None
        return OpenAI(
            api_key=self.settings.vision_api_key,
            base_url=self.settings.vision_api_base,
        )

    def _build_checkpointer(self):
        if self.settings.checkpointer_mock or self.settings.checkpoint_backend != "postgres":
            return InMemorySaver()
        if not self.settings.postgres_dsn:
            raise RuntimeError(
                "当前配置要求真实 PostgreSQL Checkpointer，但 POSTGRES_DSN 为空。"
            )
        saver = self._stack.enter_context(
            PostgresSaver.from_conn_string(self.settings.postgres_dsn)
        )
        saver.setup()
        return saver

    def _estimate_cost(self, total_tokens: int) -> float:
        return round((total_tokens / 1000.0) * self.settings.model_price_per_1k_usd, 6)

    def _cost_payload(self, total_tokens: int) -> Dict[str, Any]:
        price = float(self.settings.model_price_per_1k_usd or 0.0)
        if self.is_step_plan:
            return {
                "estimated_cost_usd": 0.0,
                "estimated_cost_available": False,
                "cost_estimation_basis": "step_plan_subscription_not_token_billed",
                "price_per_1k_usd": 0.0,
            }
        if price <= 0:
            return {
                "estimated_cost_usd": 0.0,
                "estimated_cost_available": False,
                "cost_estimation_basis": "missing_token_price_env",
                "price_per_1k_usd": 0.0,
            }
        return {
            "estimated_cost_usd": self._estimate_cost(total_tokens),
            "estimated_cost_available": True,
            "cost_estimation_basis": "token_estimate_from_env_price",
            "price_per_1k_usd": price,
        }

    def _set_stream_emitter(
        self,
        emitter: Optional[Callable[[str, Dict[str, Any]], None]],
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._thread_local.stream_emitter = emitter
        self._thread_local.stream_context = dict(context or {})

    def _clear_stream_emitter(self) -> None:
        self._thread_local.stream_emitter = None
        self._thread_local.stream_context = {}

    def _get_stream_emitter(self) -> Optional[Callable[[str, Dict[str, Any]], None]]:
        return getattr(self._thread_local, "stream_emitter", None)

    def _get_stream_context(self) -> Dict[str, Any]:
        return dict(getattr(self._thread_local, "stream_context", {}) or {})

    def _emit_stream_event(self, event_name: str, data: Dict[str, Any]) -> None:
        emitter = self._get_stream_emitter()
        if not emitter:
            return
        payload = self._get_stream_context()
        payload.update(data)
        emitter(event_name, payload)

    def _usage_to_dict(self, usage: Any) -> Dict[str, int]:
        return {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        }

    def _base_usage(self) -> Dict[str, int]:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def _default_flags(self) -> Dict[str, Any]:
        return {
            "llm_mock": self.settings.llm_mock,
            "image_mock": self.settings.image_mock,
            "vision_review_mock": self.settings.vision_review_mock,
            "checkpointer_mock": self.settings.checkpointer_mock,
            "enable_sse": self.settings.enable_sse,
            "enable_slowapi": self.settings.enable_slowapi,
            "enable_json_mode": self.settings.enable_json_mode,
        }

    def _log_node_event(
        self,
        state: MediaAgentState,
        node_name: str,
        latency_ms: float,
        usage: Dict[str, int],
        error: str,
        event_payload: Dict[str, Any],
    ) -> None:
        self.logger.info(
            "node_completed",
            run_id=state.get("run_id"),
            request_id=state.get("request_id"),
            node=node_name,
            latency_ms=latency_ms,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
            error=error,
            event_payload=event_payload,
        )

    def _record_node(
        self,
        state: MediaAgentState,
        node_name: str,
        started_at: float,
        usage: Optional[Dict[str, int]] = None,
        error: str = "",
        event_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        usage = usage or self._base_usage()
        metrics_context = MetricsContext.from_payload(state.get("metrics"))
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        cost_payload = self._cost_payload(int(usage.get("total_tokens", 0)))
        metrics_context.add_node_metric(
            node=node_name,
            latency_ms=latency_ms,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
            estimated_cost_usd=float(cost_payload["estimated_cost_usd"]),
            estimated_cost_available=bool(cost_payload["estimated_cost_available"]),
            cost_estimation_basis=str(cost_payload["cost_estimation_basis"]),
            price_per_1k_usd=float(cost_payload["price_per_1k_usd"]),
            error=error,
            ts=_utc_now(),
        )

        event_payload = event_payload or {}
        events = list(state.get("events", []))
        events.append(
            {
                "node": node_name,
                "phase": "completed" if not error else "fallback",
                "ts": _utc_now(),
                "payload": event_payload,
            }
        )
        self._log_node_event(
            state,
            node_name,
            latency_ms,
            usage,
            error,
            event_payload,
        )

        updates: Dict[str, Any] = {
            "metrics": metrics_context.to_dict(),
            "events": events,
            "trace": list(state.get("trace", [])) + [node_name],
        }
        if error:
            updates["errors"] = list(state.get("errors", [])) + [
                {"node": node_name, "error": error, "ts": _utc_now()}
            ]
        return updates

    def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 1800,
        stream_node: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.client:
            raise RuntimeError("LLM client unavailable in mock mode.")
        if self.is_circuit_open():
            raise RuntimeError(
                "LLM circuit breaker is open; workflow switched to degraded fallback mode."
            )
        token_stream_enabled = bool(stream_node and self._get_stream_emitter())
        request: Dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        self.logger.info(
            "llm_request_started",
            model=self.settings.llm_model,
            provider_route="step_plan" if self.is_step_plan else "openai_compatible",
            enable_json_mode=self.settings.enable_json_mode and not self.is_step_plan,
            stream_enabled=token_stream_enabled,
            stream_node=stream_node or "",
        )
        if not self.is_step_plan:
            request["max_tokens"] = max_tokens
        if self.settings.enable_json_mode and not self.is_step_plan:
            request["response_format"] = {"type": "json_object"}
        if token_stream_enabled:
            request["stream"] = True
            request["stream_options"] = {"include_usage": True}
        last_error: Optional[Exception] = None
        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                if token_stream_enabled:
                    started_at = time.perf_counter()
                    response = self.client.chat.completions.create(**request)
                    text_parts: List[str] = []
                    usage_payload = self._base_usage()
                    ttft_ms: Optional[float] = None
                    chunk_index = 0
                    for chunk in response:
                        if getattr(chunk, "usage", None):
                            usage_payload = self._usage_to_dict(chunk.usage)
                        for choice in getattr(chunk, "choices", []) or []:
                            delta = getattr(choice.delta, "content", None) or ""
                            if not delta:
                                continue
                            text_parts.append(delta)
                            if ttft_ms is None:
                                ttft_ms = round((time.perf_counter() - started_at) * 1000, 2)
                            self._emit_stream_event(
                                "token",
                                {
                                    "node": stream_node,
                                    "delta": delta,
                                    "chunk_index": chunk_index,
                                    "ttft_ms": ttft_ms if chunk_index == 0 else None,
                                },
                            )
                            chunk_index += 1
                    text = "".join(text_parts)
                    if not text.strip():
                        raise RuntimeError("LLM returned empty content.")
                    self._reset_llm_failure_count()
                    self.logger.info(
                        "llm_request_succeeded",
                        model=self.settings.llm_model,
                        retry_count=attempt,
                        prompt_tokens=usage_payload["prompt_tokens"],
                        completion_tokens=usage_payload["completion_tokens"],
                        total_tokens=usage_payload["total_tokens"],
                        stream_node=stream_node or "",
                        streamed_chunks=chunk_index,
                        ttft_ms=ttft_ms,
                    )
                    self._emit_stream_event(
                        "token_summary",
                        {
                            "node": stream_node,
                            "chunk_count": chunk_index,
                            "ttft_ms": ttft_ms,
                            **usage_payload,
                        },
                    )
                    return {
                        "text": text,
                        "usage": usage_payload,
                        "retry_count": attempt,
                        "ttft_ms": ttft_ms,
                        "streamed_chunks": chunk_index,
                    }

                response = self.client.chat.completions.create(**request)
                text = response.choices[0].message.content or ""
                if not text.strip():
                    raise RuntimeError("LLM returned empty content.")
                self._reset_llm_failure_count()
                usage_payload = self._usage_to_dict(response.usage)
                self.logger.info(
                    "llm_request_succeeded",
                    model=self.settings.llm_model,
                    retry_count=attempt,
                    prompt_tokens=usage_payload["prompt_tokens"],
                    completion_tokens=usage_payload["completion_tokens"],
                    total_tokens=usage_payload["total_tokens"],
                )
                return {
                    "text": text,
                    "usage": usage_payload,
                    "retry_count": attempt,
                }
            except Exception as exc:
                last_error = exc
                self._record_llm_failure()
                self.logger.info(
                    "llm_request_failed",
                    model=self.settings.llm_model,
                    retry_count=attempt,
                    error=str(exc),
                    circuit_state=self.circuit_state(),
                )
                if attempt >= self.settings.llm_max_retries:
                    break
                backoff = round(
                    self.settings.llm_retry_backoff_base_sec * (2**attempt),
                    2,
                )
                time.sleep(backoff)
        raise RuntimeError(str(last_error) if last_error else "LLM request failed.")

    def _record_llm_failure(self) -> None:
        self._llm_failure_count += 1
        if self._llm_failure_count >= self.settings.circuit_breaker_threshold:
            self._circuit_open_until = time.time() + self.settings.circuit_breaker_cooldown_sec

    def _reset_llm_failure_count(self) -> None:
        self._llm_failure_count = 0
        self._circuit_open_until = 0.0

    def is_circuit_open(self) -> bool:
        return self._circuit_open_until > time.time()

    def circuit_state(self) -> Dict[str, Any]:
        return {
            "open": self.is_circuit_open(),
            "failure_count": self._llm_failure_count,
            "threshold": self.settings.circuit_breaker_threshold,
            "cooldown_sec": self.settings.circuit_breaker_cooldown_sec,
            "open_until_ts": self._circuit_open_until,
        }

    def _merge_usage(self, *usages: Optional[Dict[str, int]]) -> Dict[str, int]:
        merged = self._base_usage()
        for usage in usages:
            if not usage:
                continue
            merged["prompt_tokens"] += int(usage.get("prompt_tokens", 0))
            merged["completion_tokens"] += int(usage.get("completion_tokens", 0))
            merged["total_tokens"] += int(usage.get("total_tokens", 0))
        return merged

    def _validate_with_repair(
        self,
        *,
        raw: str,
        schema: type[Any],
        fallback_model: Any,
        usage: Dict[str, int],
        repair_requirements: str,
        repair_max_tokens: int,
    ) -> tuple[Dict[str, Any], Dict[str, int], str]:
        validated = parse_and_validate_schema(raw, schema, fallback_model)
        if "fallback" not in validated.parse_strategy or not self.client:
            return validated.value.model_dump(), usage, validated.parse_strategy

        repair = self._call_llm(
            (
                "You repair broken JSON for downstream workflow systems. "
                "Return only valid JSON matching the requested schema. "
                "Do not add markdown, code fences, or commentary."
            ),
            (
                f"schema={schema.__name__}\n"
                f"requirements={repair_requirements}\n"
                f"invalid_output={raw[:1800]}"
            ),
            temperature=0.0,
            max_tokens=repair_max_tokens,
        )
        repaired = parse_and_validate_schema(repair["text"], schema, fallback_model)
        merged_usage = self._merge_usage(usage, repair["usage"])
        if "fallback" not in repaired.parse_strategy:
            return repaired.value.model_dump(), merged_usage, f"repair:{repaired.parse_strategy}"
        return validated.value.model_dump(), merged_usage, validated.parse_strategy

    def _build_style_features(self, docs: List[str]) -> List[str]:
        features: List[str] = []
        for doc in docs:
            text = doc.strip()
            if not text:
                continue
            headline = next((line.strip() for line in text.splitlines() if line.strip()), "")
            if headline:
                features.append(f"标题风格参考：{headline[:18]}")
            if any(token in text for token in ["先说结果", "先说结论", "先说"]):
                features.append("开头先给结果或结论")
            if any(token in text for token in ["第一步", "第二步", "周一", "步骤", "安排"]):
                features.append("正文按步骤或分段展开")
            if any(token in text for token in ["我", "姐妹们", "真的", "终于"]):
                features.append("语气口语化，使用第一人称")
            if any(token in text for token in ["建议", "坚持", "最后", "总结"]):
                features.append("结尾给行动建议或总结")
            if "#" in text:
                features.append("结尾保留 3 到 5 个标签")

        defaults = [
            "开头先给结果或结论",
            "正文按 4 到 6 段短段落展开",
            "语气口语化，使用第一人称",
            "结尾给行动建议或总结",
            "结尾保留 3 到 5 个标签",
        ]
        merged = []
        for item in features + defaults:
            if item not in merged:
                merged.append(item)
        return merged[:6]

    def _compress_style_features(self, features: List[str], limit: int = 2) -> str:
        selected = [item.strip() for item in features if item.strip()][:limit]
        return "；".join(selected)[:70]

    def _platform_style_hint(
        self,
        platform: str,
        style: str,
        style_features: List[str],
    ) -> str:
        rule = get_platform_rule(platform)
        if rule.get("tone_hint"):
            return str(rule["tone_hint"])
        if platform == "公众号":
            return "先抛出核心观点；正文按5到7段自然展开；加入趋势观察、案例或个人思考；结尾做总结升华。"
        if platform == "知乎":
            return "先明确问题，再做层层分析；正文按4到6段展开；兼顾观点、论据和结论。"
        compressed = self._compress_style_features(style_features)
        if compressed:
            return compressed
        return "开头先给结果；正文分段清楚；结尾给行动建议。"

    def _draft_plan(self, platform: str, style: str) -> Dict[str, Any]:
        rule = get_platform_rule(platform)
        if rule:
            return {
                "length": rule["length_hint"],
                "paragraphs": rule["paragraph_hint"],
                "tone": rule["tone_hint"],
                "hook": "标题和开头必须符合平台阅读场景，避免夸大和标题党",
                "tag_rule": f"tags 保持 {rule['tag_count']} 个中文标签，必须和主题相关",
            }
        if platform == "公众号":
            return {
                "length": "700到1200字",
                "paragraphs": "5到7段自然段",
                "tone": "适合公众号深度表达，允许趋势观察、案例分析和个人思考",
                "hook": "标题和开头要明确观点，但不要标题党",
                "tag_rule": "tags 保持 2 到 3 个中文标签，避免过度营销",
            }
        if platform == "知乎":
            return {
                "length": "450到800字",
                "paragraphs": "4到6段",
                "tone": "偏分析和解释，逻辑清楚，兼顾观点与论据",
                "hook": "开头先回答问题，再展开论证",
                "tag_rule": "tags 保持 2 到 3 个中文标签",
            }
        return {
            "length": "180到260字",
            "paragraphs": "2到3段短段落",
            "tone": "口语化、节奏快、适合快速阅读",
            "hook": "开头先给结果或强钩子",
            "tag_rule": "tags 保持 3 个中文标签并带 #",
        }

    def _generic_fallback_tags(self, platform: str, style: str) -> List[str]:
        if platform == "小红书":
            return [f"#{platform}", f"#{style}", "#内容创作", "#实用干货", "#收藏"]
        return [f"#{platform}", f"#{style}", "#内容创作"]

    def _image_output_dir(self) -> Path:
        if self._image_output_dir_cache is not None:
            return self._image_output_dir_cache
        out_dir = Path(__file__).resolve().parents[2] / "outputs" / "images"
        out_dir.mkdir(parents=True, exist_ok=True)
        self._image_output_dir_cache = out_dir
        return out_dir

    def _mock_cover_asset(
        self,
        *,
        run_id: str,
        plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        overlay = str(plan.get("overlay_text") or "Media Agent 封面").strip()[:28]
        prompt = str(plan.get("prompt") or "")
        file_name = f"{_safe_file_stem(run_id)}.mock-cover.svg"
        local_path = self._image_output_dir() / file_name
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="960" viewBox="0 0 1280 960">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#113826"/>
      <stop offset="100%" stop-color="#91d4ae"/>
    </linearGradient>
  </defs>
    <rect width="1280" height="960" fill="url(#bg)"/>
    <circle cx="1080" cy="180" r="220" fill="rgba(255,255,255,0.12)"/>
    <circle cx="160" cy="820" r="260" fill="rgba(255,239,200,0.18)"/>
    <text x="96" y="180" fill="#f7fff8" font-size="66" font-family="Microsoft YaHei, PingFang SC, sans-serif" font-weight="700">{overlay}</text>
    <rect x="96" y="244" rx="26" ry="26" width="1088" height="360" fill="rgba(255,255,255,0.08)" stroke="rgba(255,255,255,0.18)"/>
    <text x="96" y="320" fill="#f7fff8" font-size="34" font-family="Microsoft YaHei, PingFang SC, sans-serif" font-weight="700">Mock Cover Preview</text>
    <text x="96" y="376" fill="#eef8f0" font-size="26" font-family="Microsoft YaHei, PingFang SC, sans-serif">This is a placeholder image for low-cost UI and flow verification.</text>
    <text x="96" y="428" fill="#eef8f0" font-size="24" font-family="Microsoft YaHei, PingFang SC, sans-serif">Switch the demo to real image generation to inspect the actual visual result.</text>
    <text x="96" y="504" fill="#f7fff8" font-size="28" font-family="Microsoft YaHei, PingFang SC, sans-serif">Prompt length: {len(prompt)} chars</text>
    <text x="96" y="560" fill="#f7fff8" font-size="24" font-family="Microsoft YaHei, PingFang SC, sans-serif">Mode: mock / not billed</text>
  </svg>"""
        local_path.write_text(svg, encoding="utf-8")
        return ImageAssetModel(
            status="mock_generated",
            provider="mock",
            model="mock-svg-cover",
            asset_type=str(plan.get("asset_type") or "cover"),
            usage=str(plan.get("usage") or "封面"),
            requested_size=self._resolve_image_size(plan),
            prompt=prompt,
            negative_prompt=str(plan.get("negative_prompt") or ""),
            local_path=str(local_path),
            web_path=f"/outputs/images/{file_name}",
            mime_type="image/svg+xml",
            retry_count=0,
            latency_ms=0.0,
        ).model_dump()

    def _download_image_url(self, run_id: str, image_url: str, mime_type: str = "") -> Dict[str, str]:
        suffix = Path(urlparse(image_url).path).suffix or mimetypes.guess_extension(mime_type or "") or ".png"
        file_name = f"{_safe_file_stem(run_id)}{suffix}"
        local_path = self._image_output_dir() / file_name
        timeout = max(5, int(self.settings.image_download_timeout_sec or 45))
        request = Request(image_url, headers={"User-Agent": "media-agent/2"})
        with urlopen(request, timeout=timeout) as resp:
            local_path.write_bytes(resp.read())
        return {
            "local_path": str(local_path),
            "web_path": f"/outputs/images/{file_name}",
            "mime_type": mime_type or mimetypes.guess_type(str(local_path))[0] or "image/png",
        }

    def _save_b64_image(self, run_id: str, image_b64: str) -> Dict[str, str]:
        file_name = f"{_safe_file_stem(run_id)}.png"
        local_path = self._image_output_dir() / file_name
        local_path.write_bytes(b64decode(image_b64))
        return {
            "local_path": str(local_path),
            "web_path": f"/outputs/images/{file_name}",
            "mime_type": "image/png",
        }

    def _resolve_image_size(self, plan: Dict[str, Any]) -> str:
        aspect_ratio = str(plan.get("aspect_ratio") or "").strip()
        if ":" in aspect_ratio:
            try:
                left, right = aspect_ratio.split(":", 1)
                ratio_value = float(left) / float(right)
            except (TypeError, ValueError, ZeroDivisionError):
                ratio_value = 1.0
        else:
            try:
                ratio_value = float(aspect_ratio)
            except (TypeError, ValueError):
                ratio_value = 1.0

        if ratio_value >= 1.45:
            return "1280x800"
        if ratio_value <= 0.8:
            return "800x1280"
        return self.settings.image_size

    def _generate_cover_asset(
        self,
        *,
        run_id: str,
        plan: Dict[str, Any],
        image_mock: Optional[bool] = None,
    ) -> Dict[str, Any]:
        started = time.perf_counter()
        use_image_mock = self.settings.image_mock if image_mock is None else image_mock
        if use_image_mock or not self.image_client:
            asset = self._mock_cover_asset(run_id=run_id, plan=plan)
            asset["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
            return asset
        requested_size = self._resolve_image_size(plan)
        last_error: Optional[Exception] = None
        for attempt in range(self.settings.image_max_retries + 1):
            try:
                response = self.image_client.images.generate(
                    model=self.settings.image_model,
                    prompt=plan.get("prompt", ""),
                    size=requested_size,
                )
                if not getattr(response, "data", None):
                    raise RuntimeError("Image model returned empty data.")
                first = response.data[0]
                image_url = getattr(first, "url", "") or ""
                b64_json = getattr(first, "b64_json", "") or ""
                if image_url:
                    stored = self._download_image_url(run_id, image_url)
                    return ImageAssetModel(
                        status="generated",
                        provider="stepfun_images",
                        model=self.settings.image_model,
                        asset_type=str(plan.get("asset_type") or "cover"),
                        usage=str(plan.get("usage") or "封面"),
                        requested_size=requested_size,
                        prompt=plan.get("prompt", ""),
                        negative_prompt=plan.get("negative_prompt", ""),
                        image_url=image_url,
                        local_path=stored["local_path"],
                        web_path=stored["web_path"],
                        mime_type=stored["mime_type"],
                        retry_count=attempt,
                        latency_ms=round((time.perf_counter() - started) * 1000, 2),
                    ).model_dump()
                if b64_json:
                    stored = self._save_b64_image(run_id, b64_json)
                    return ImageAssetModel(
                        status="generated",
                        provider="stepfun_images",
                        model=self.settings.image_model,
                        asset_type=str(plan.get("asset_type") or "cover"),
                        usage=str(plan.get("usage") or "封面"),
                        requested_size=requested_size,
                        prompt=plan.get("prompt", ""),
                        negative_prompt=plan.get("negative_prompt", ""),
                        local_path=stored["local_path"],
                        web_path=stored["web_path"],
                        mime_type=stored["mime_type"],
                        retry_count=attempt,
                        latency_ms=round((time.perf_counter() - started) * 1000, 2),
                    ).model_dump()
                raise RuntimeError("Image response missing url and b64_json.")
            except Exception as exc:
                last_error = exc
                self.logger.info(
                    "image_generation_failed",
                    run_id=run_id,
                    model=self.settings.image_model,
                    retry_count=attempt,
                    error=str(exc),
                )
                if attempt >= self.settings.image_max_retries:
                    break
                backoff = round(
                    self.settings.image_retry_backoff_base_sec * (2**attempt),
                    2,
                )
                time.sleep(backoff)
        raise RuntimeError(str(last_error) if last_error else "Image generation failed.")

    async def generate_cover_assets_batch(
        self,
        plans: List[Dict[str, Any]],
        *,
        run_prefix: str,
        image_mock: Optional[bool] = None,
        concurrency: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        loop = asyncio.get_running_loop()
        limit = max(1, concurrency or len(plans) or 1)
        semaphore = asyncio.Semaphore(limit)

        async def generate_one(
            index: int,
            plan: Dict[str, Any],
            pool: ThreadPoolExecutor,
        ) -> Dict[str, Any]:
            async with semaphore:
                run_id = f"{run_prefix}-{index + 1:02d}"
                started = time.perf_counter()

                def _run() -> Dict[str, Any]:
                    return self._generate_cover_asset(
                        run_id=run_id,
                        plan=plan,
                        image_mock=image_mock,
                    )

                asset = await loop.run_in_executor(pool, _run)
                return {
                    "index": index,
                    "run_id": run_id,
                    "asset": asset,
                    "wall_time_ms": round((time.perf_counter() - started) * 1000, 2),
                }

        with ThreadPoolExecutor(max_workers=limit) as pool:
            tasks = [generate_one(index, plan, pool) for index, plan in enumerate(plans)]
            return await asyncio.gather(*tasks)

    async def _generate_cover_assets_batch_resilient(
        self,
        plans: List[Dict[str, Any]],
        *,
        run_prefix: str,
        image_mock: Optional[bool] = None,
        concurrency: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Generate multiple covers concurrently; failed items are skipped instead of failing the batch."""
        loop = asyncio.get_running_loop()
        limit = max(1, concurrency or len(plans) or 1)
        semaphore = asyncio.Semaphore(limit)

        async def generate_one(
            index: int,
            plan: Dict[str, Any],
            pool: ThreadPoolExecutor,
        ) -> Dict[str, Any]:
            async with semaphore:
                run_id = f"{run_prefix}-{index + 1:02d}"
                started = time.perf_counter()

                def _run() -> Dict[str, Any]:
                    return self._generate_cover_asset(
                        run_id=run_id,
                        plan=plan,
                        image_mock=image_mock,
                    )

                asset = await loop.run_in_executor(pool, _run)
                return {
                    "index": index,
                    "run_id": run_id,
                    "asset": asset,
                    "wall_time_ms": round((time.perf_counter() - started) * 1000, 2),
                }

        with ThreadPoolExecutor(max_workers=limit) as pool:
            tasks = [generate_one(index, plan, pool) for index, plan in enumerate(plans)]
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        ok: List[Dict[str, Any]] = []
        for idx, outcome in enumerate(outcomes):
            if isinstance(outcome, Exception):
                self.logger.info(
                    "cover_batch_item_failed",
                    run_prefix=run_prefix,
                    index=idx,
                    error=str(outcome),
                )
                continue
            ok.append(outcome)
        ok.sort(key=lambda item: item["index"])
        return ok

    def _initial_state(
        self,
        brief: str,
        platform: str,
        style: str,
        approval_decision: str,
        approval_note: str,
        reviewer_threshold: int,
        max_revisions: int,
        run_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        request_id: Optional[str] = None,
        runtime_overrides: Optional[Dict[str, Any]] = None,
    ) -> MediaAgentState:
        resolved_run_id = run_id or uuid.uuid4().hex[:12]
        runtime_flags = self._default_flags()
        for key, value in (runtime_overrides or {}).items():
            if value is not None and key in runtime_flags:
                runtime_flags[key] = value
        cover_n = 1
        raw_cc = (runtime_overrides or {}).get("cover_candidate_count")
        if raw_cc is not None:
            try:
                cover_n = int(raw_cc)
            except (TypeError, ValueError):
                cover_n = 1
        cover_n = max(1, min(4, cover_n))
        run_mode_raw = (runtime_overrides or {}).get("run_mode") or "auto"
        if isinstance(run_mode_raw, str):
            run_mode_raw = run_mode_raw.strip().lower()
        run_mode = run_mode_raw if run_mode_raw in ("auto", "guided") else "auto"
        export_formats = _normalize_export_formats((runtime_overrides or {}).get("export_formats"))
        guided_locked = True
        if run_mode == "guided":
            guided_locked = bool((runtime_overrides or {}).get("guided_topic_locked"))
        return {
            "run_id": resolved_run_id,
            "request_id": request_id or resolved_run_id,
            "thread_id": thread_id or resolved_run_id,
            "graph_version": self.layout.version,
            "status": "pending",
            "run_mode": run_mode,
            "guided_topic_locked": guided_locked,
            "export_formats": export_formats,
            "brief": brief.strip(),
            "platform": platform,
            "style": style,
            "selected_topic": {"title": brief.strip() or "Untitled topic"},
            "research": {},
            "draft": {},
            "adapted": {},
            "image_plan": {},
            "image_plans": [],
            "image_asset": {},
            "image_assets": [],
            "cover_candidates": [],
            "cover_candidate_count": cover_n,
            "review": {},
            "approval": {},
            "approval_decision": approval_decision,  # type: ignore[typeddict-item]
            "approval_note": approval_note,
            "reviewer_threshold": reviewer_threshold,
            "max_revisions": max_revisions,
            "revision_count": 0,
            "review_feedback": "",
            "trace": [],
            "events": [],
            "metrics": _default_metrics(),
            "errors": [],
            "content_package": {},
            "platform_rule": get_platform_rule(platform),
            "publish_package": {},
            "runtime_flags": runtime_flags,
        }

    def node_brief_intake(self, state: MediaAgentState) -> Dict[str, Any]:
        started = time.perf_counter()
        updates = {
            "status": "running",
            "graph_version": self.layout.version,
            "runtime_flags": dict(state.get("runtime_flags") or self._default_flags()),
        }
        updates.update(
            self._record_node(
                state,
                "brief_intake",
                started,
                event_payload={"platform": state.get("platform"), "style": state.get("style")},
            )
        )
        return updates

    def node_topic_selection_stop(self, state: MediaAgentState) -> Dict[str, Any]:
        started = time.perf_counter()
        topics = (state.get("research") or {}).get("topics") or []
        updates: Dict[str, Any] = {"status": "awaiting_topic_selection"}
        updates.update(
            self._record_node(
                state,
                "topic_selection_stop",
                started,
                event_payload={"topics_count": len(topics)},
            )
        )
        return updates

    def node_research_topic(self, state: MediaAgentState) -> Dict[str, Any]:
        started = time.perf_counter()
        fallback = ResearchPayloadModel(
            topics=[
                ResearchTopicModel(
                    title=state["brief"],
                    reason="工作流兜底选题",
                    heat_score=6,
                    target_audience=f"{state['platform']}读者",
                    content_angle="观点拆解",
                )
            ]
        )
        usage = self._base_usage()
        error = ""
        parse_strategy = "mock"
        retry_count = 0
        ttft_ms: Optional[float] = None
        streamed_chunks = 0
        try:
            if self.settings.llm_mock:
                raw = fallback.model_dump_json(ensure_ascii=False)
                usage = {"prompt_tokens": 48, "completion_tokens": 92, "total_tokens": 140}
                payload = fallback.model_dump()
            else:
                repair_requirements = (
                    "Return JSON object with key topics. topics must be an array of exactly 2 objects. "
                    "Each object must contain title, reason, heat_score, target_audience, content_angle. "
                    "All values must stay in Chinese. heat_score must be an integer from 1 to 10. "
                    "Keep every string short, concrete, and aligned with the user brief and target platform."
                )
                llm = self._call_llm(
                    (
                        "Return raw JSON only. The first character must be { and the last character must be }. "
                        "Never use markdown, code fences, bullet points, or explanation text. "
                        "Top-level key must be topics. "
                        "topics must be an array of exactly 2 objects. "
                        "Each object needs title, reason, heat_score, target_audience, content_angle. "
                        "Language of all values must be Chinese. "
                        "title <= 14 Chinese chars, reason <= 16 Chinese chars, "
                        "target_audience <= 8 Chinese chars, content_angle <= 8 Chinese chars. "
                        "heat_score must be an integer from 1 to 10."
                    ),
                    (
                        f"brief={state['brief']}\n"
                        f"platform={state['platform']}\n"
                        f"style={state['style']}\n"
                        "Generate 2 topic candidates that stay strictly on the given brief. "
                        "Do not inject unrelated domains, jobs, resume, interview, or AI product manager angles unless the brief explicitly asks for them."
                    ),
                    temperature=0.0,
                    max_tokens=1000,
                    stream_node="research_topic",
                )
                raw = llm["text"]
                usage = llm["usage"]
                retry_count = int(llm.get("retry_count", 0))
                ttft_ms = llm.get("ttft_ms")
                streamed_chunks = int(llm.get("streamed_chunks", 0))
                payload, usage, parse_strategy = self._validate_with_repair(
                    raw=raw,
                    schema=ResearchPayloadModel,
                    fallback_model=fallback,
                    usage=usage,
                    repair_requirements=repair_requirements,
                    repair_max_tokens=1000,
                )
        except Exception as exc:
            error = str(exc)
            payload = fallback.model_dump()
            parse_strategy = "exception-fallback"

        topics = payload.get("topics", [])
        guided = state.get("run_mode") == "guided"
        locked = bool(state.get("guided_topic_locked"))
        if guided and not locked:
            selected_topic: Dict[str, Any] = {}
        else:
            selected_topic = topics[0] if topics else fallback.topics[0].model_dump()
        updates = {
            "research": payload,
            "selected_topic": selected_topic,
        }
        updates.update(
            self._record_node(
                state,
                "research_topic",
                started,
                usage=usage,
                error=error,
                event_payload={
                    "topics_count": len(topics),
                    "parse_strategy": parse_strategy,
                    "retry_count": retry_count,
                    "ttft_ms": ttft_ms,
                    "streamed_chunks": streamed_chunks,
                },
            )
        )
        return updates

    def node_research_evidence_merge(self, state: MediaAgentState) -> Dict[str, Any]:
        started = time.perf_counter()
        docs = self.kb.search(state.get("platform", ""), top_k=3)
        style_features = self._build_style_features(docs)
        evidence = [
            {
                "source": f"sample_posts[{idx}]",
                "headline": next((line.strip() for line in doc.splitlines() if line.strip()), "")[:36],
                "style_signal": style_features[min(idx - 1, len(style_features) - 1)],
            }
            for idx, doc in enumerate(docs, start=1)
        ]
        research = dict(state.get("research", {}))
        research["evidence"] = evidence
        research["style_features"] = style_features
        updates = {"research": research}
        updates.update(
            self._record_node(
                state,
                "research_evidence_merge",
                started,
                event_payload={
                    "evidence_count": len(evidence),
                    "style_feature_count": len(style_features),
                },
            )
        )
        return updates
    def node_write_draft(self, state: MediaAgentState) -> Dict[str, Any]:
        started = time.perf_counter()
        topic = state.get("selected_topic", {}).get("title") or state["brief"]
        selected_topic = state.get("selected_topic", {})
        style_features = state.get("research", {}).get("style_features", [])
        style_hint_text = self._platform_style_hint(
            state["platform"],
            state["style"],
            style_features,
        )
        draft_plan = self._draft_plan(state["platform"], state["style"])
        feedback = str(state.get("review_feedback", "")).strip()[:200]
        fallback = DraftPayloadModel(
            title=f"{topic} | {state['platform']}",
            content=(
                f"围绕“{topic}”生成的内容草稿。\n\n"
                f"目标平台：{state['platform']}\n"
                f"内容风格：{state['style']}\n"
                f"当前第 {state.get('revision_count', 0) + 1} 次写作。"
            ),
            tags=self._generic_fallback_tags(state["platform"], state["style"]),
            platform=state["platform"],
        )
        usage = self._base_usage()
        error = ""
        parse_strategy = "mock"
        retry_count = 0
        ttft_ms: Optional[float] = None
        streamed_chunks = 0
        try:
            if self.settings.llm_mock:
                raw = fallback.model_dump_json(ensure_ascii=False)
                usage = {"prompt_tokens": 110, "completion_tokens": 260, "total_tokens": 370}
                payload = fallback.model_dump()
            else:
                repair_requirements = (
                    "Return JSON object with title, content, tags, platform. "
                    "Language must be Chinese. title and content must stay strictly on the brief and selected topic. "
                    f"content should be around {draft_plan['length']} and use {draft_plan['paragraphs']}. "
                    f"Tone requirement: {draft_plan['tone']}. "
                    "Use a single JSON string for content and preserve paragraph breaks with \\n\\n. "
                    "Do not inject job-search, resume, interview, or AI product manager framing unless the brief explicitly asks for it. "
                    "tags must be 2 to 3 Chinese hashtags starting with # and relevant to the actual topic. "
                    "platform must equal the requested platform exactly."
                )
                writer_prompt_lines = [
                    f"brief={state['brief']}",
                    f"platform={state['platform']}",
                    f"topic={topic}",
                    f"target_audience={selected_topic.get('target_audience', '')}",
                    f"content_angle={selected_topic.get('content_angle', '')}",
                    f"style={state['style']}",
                    f"revision={state.get('revision_count', 0) + 1}",
                    f"style_hints={style_hint_text}",
                    f"length_target={draft_plan['length']}",
                    f"paragraph_target={draft_plan['paragraphs']}",
                    f"hook_rule={draft_plan['hook']}",
                    f"tone_rule={draft_plan['tone']}",
                    f"tag_rule={draft_plan['tag_rule']}",
                    "Goal: write a high-quality platform-native article that stays strictly on the brief.",
                ]
                if feedback:
                    writer_prompt_lines.insert(7, f"feedback={feedback}")
                llm = self._call_llm(
                    (
                        "Return raw JSON only with keys title, content, tags, platform. "
                        "First character {, last }. No markdown, fences, or extra keys. "
                        "One compact JSON line. Chinese. "
                        "platform must equal the user platform field. "
                        "Stay on brief/topic; follow length/paragraph/tone/hook rules in the user block. "
                        "Treat style_hints as guidance only, do not copy literally. "
                        "Use \\n\\n between paragraphs. "
                        "No resume/interview/job-search framing unless the brief asks. "
                        "tags: 2–3 Chinese hashtags starting with #."
                    ),
                    "\n".join(writer_prompt_lines),
                    temperature=0.0,
                    max_tokens=1800 if state["platform"] == "公众号" else 1200,
                    stream_node="write_draft",
                )
                raw = llm["text"]
                usage = llm["usage"]
                retry_count = int(llm.get("retry_count", 0))
                ttft_ms = llm.get("ttft_ms")
                streamed_chunks = int(llm.get("streamed_chunks", 0))
                payload, usage, parse_strategy = self._validate_with_repair(
                    raw=raw,
                    schema=DraftPayloadModel,
                    fallback_model=fallback,
                    usage=usage,
                    repair_requirements=repair_requirements,
                    repair_max_tokens=1800 if state["platform"] == "公众号" else 1200,
                )
        except Exception as exc:
            error = str(exc)
            payload = fallback.model_dump()
            parse_strategy = "exception-fallback"

        payload["platform"] = state["platform"]
        updates = {"draft": payload}
        updates.update(
            self._record_node(
                state,
                "write_draft",
                started,
                usage=usage,
                error=error,
                event_payload={
                    "parse_strategy": parse_strategy,
                    "title": payload.get("title", ""),
                    "retry_count": retry_count,
                    "ttft_ms": ttft_ms,
                    "streamed_chunks": streamed_chunks,
                },
            )
        )
        return updates

    def _platform_tag_pack(self, platform: str, current: Any) -> List[str]:
        base = [str(t).strip() for t in (current or []) if str(t).strip()]
        topic_tags = [t if t.startswith("#") else f"#{t}" for t in base]
        extras = {
            "公众号": ["#深度阅读", "#趋势观察", "#认知升级"],
            "小红书": ["#经验分享", "#干货收藏", "#成长思考", "#职场观察", "#生活灵感", "#自我提升", "#避坑指南", "#高效成长"],
            "知乎": ["#深度分析", "#理性讨论", "#认知方法", "#问题拆解"],
        }.get(platform, ["#内容运营", "#AI创作"])
        target = 8 if platform == "小红书" else 3
        merged = list(dict.fromkeys([*topic_tags, *extras]))
        return merged[:target]

    def _platform_body(self, platform: str, title: str, content: str, rule: Dict[str, Any]) -> str:
        clean = content.strip() or title
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", clean) if p.strip()]
        if platform == "小红书":
            hook = f"先说结论：{title}，真正重要的不是信息多少，而是筛选和判断。"
            bullets = paragraphs[:3] or [clean]
            return "\n\n".join([hook, *[f"• {p[:90]}" for p in bullets], "适合收藏后慢慢复盘。"])
        if platform == "知乎":
            answer = f"简短回答：{title}背后，本质是注意力、经验和验证机制的差异。"
            return "\n\n".join([answer, *paragraphs[:6], "所以，与其追更多信息，不如建立可复用的判断框架。"])
        intro = f"【公众号深度版】{rule.get('tone_hint', '')}"
        return "\n\n".join([intro, *paragraphs[:9]])

    def node_adapt_platform(self, state: MediaAgentState) -> Dict[str, Any]:
        started = time.perf_counter()
        draft = dict(state.get("draft", {}))
        adapted = dict(draft)
        adapted["platform"] = state["platform"]
        rule = get_platform_rule(state["platform"])
        title = str(adapted.get("title") or state.get("brief", "")).strip()
        adapted["title"] = title[:28] if state["platform"] == "小红书" else title[:42]
        adapted["content"] = self._platform_body(
            state["platform"],
            adapted["title"],
            str(adapted.get("content") or ""),
            rule,
        )
        adapted["tags"] = self._platform_tag_pack(state["platform"], adapted.get("tags"))
        updates = {"adapted": adapted, "platform_rule": rule}
        updates.update(
            self._record_node(
                state,
                "adapt_platform",
                started,
                event_payload={
                    "platform": state["platform"],
                    "content_shape": rule.get("content_shape", ""),
                    "image_targets": rule.get("image_targets", {}),
                },
            )
        )
        return updates

    def _asset_usage_label(self, asset_type: str, index: int) -> str:
        labels = {
            "cover": "封面图",
            "body": f"正文配图 {index}",
            "card": f"小红书卡片图 {index}",
            "summary": "总结卡/金句卡",
        }
        return labels.get(asset_type, f"图片素材 {index}")

    def _build_image_plans_from_rule(
        self,
        state: MediaAgentState,
        base_plan: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        rule = dict(state.get("platform_rule") or get_platform_rule(state["platform"]))
        targets = dict(rule.get("image_targets") or {})
        adapted = state.get("adapted", {}) or state.get("draft", {})
        title = str(adapted.get("title") or state.get("brief", ""))[:48]
        body = str(adapted.get("content") or "")[:420]
        plans: List[Dict[str, Any]] = []
        order = ["cover", "body", "card", "summary"]
        for asset_type in order:
            count = int(targets.get(asset_type, 0) or 0)
            for idx in range(1, count + 1):
                plan = dict(base_plan)
                plan["asset_type"] = asset_type
                plan["usage"] = self._asset_usage_label(asset_type, idx)
                if asset_type == "cover":
                    plan["overlay_text"] = plan.get("overlay_text") or title[:22]
                    plan["aspect_ratio"] = "4:3" if state["platform"] != "小红书" else "3:4"
                elif asset_type == "body":
                    plan["overlay_text"] = ""
                    plan["aspect_ratio"] = "4:3"
                    plan["prompt"] = (
                        f"为{state['platform']}文章生成正文配图第{idx}张。标题：{title}。"
                        f"正文摘要：{body}。画面应解释核心观点，少文字，真实、清晰、无水印。"
                    )
                elif asset_type == "card":
                    plan["overlay_text"] = f"{idx}. {title[:14]}"
                    plan["aspect_ratio"] = "3:4"
                    plan["prompt"] = (
                        f"为小红书笔记生成第{idx}张信息卡片图。主题：{title}。"
                        "移动端竖图，信息分层清楚，适合连续滑动阅读，中文标题区留白。"
                    )
                elif asset_type == "summary":
                    plan["overlay_text"] = title[:18]
                    plan["aspect_ratio"] = "1:1"
                    plan["prompt"] = (
                        f"为{state['platform']}内容生成总结卡/金句卡。主题：{title}。"
                        "画面简洁、可收藏，突出一句核心观点，避免水印和复杂小字。"
                    )
                plans.append(ImagePlanModel.model_validate(plan).model_dump())
        return plans

    def node_plan_cover(self, state: MediaAgentState) -> Dict[str, Any]:
        started = time.perf_counter()
        adapted = state.get("adapted", {}) or state.get("draft", {})
        title = adapted.get("title", state.get("brief", ""))[:48]
        fallback = ImagePlanModel(
            prompt=(
                f"为一篇{state['platform']}内容生成封面图。主题：{title}。"
                "画面风格简洁、专业、有层次，适合中文内容封面，保留标题展示区域。"
            ),
            negative_prompt="低清晰度、杂乱排版、过多文字、变形人物、水印、模糊",
            overlay_text=title[:22],
            visual_style="编辑部风格封面，信息感强，适合公众号头图",
            aspect_ratio="4:3",
            asset_type="cover",
            usage="封面图",
        )
        usage = self._base_usage()
        error = ""
        parse_strategy = "mock"
        retry_count = 0
        try:
            if self.settings.llm_mock:
                payload = fallback.model_dump()
            else:
                repair_requirements = (
                    "Return JSON object with prompt, negative_prompt, overlay_text, visual_style, aspect_ratio. "
                    "Stay strictly on the article brief and title. "
                    "Do not inject AI product manager, resume, or job-search framing unless the brief explicitly asks for it. "
                    "overlay_text must be short Chinese text suitable for a cover image."
                )
                llm = self._call_llm(
                    (
                        "You design cover-image plans for content workflows. "
                        "Return raw JSON only. "
                        "Top-level keys must be prompt, negative_prompt, overlay_text, visual_style, aspect_ratio. "
                        "Do not use markdown, code fences, or explanation text."
                    ),
                    (
                        f"brief={state['brief']}\n"
                        f"platform={state['platform']}\n"
                        f"style={state['style']}\n"
                        f"title={title}\n"
                        f"content_summary={str(adapted.get('content', ''))[:500]}\n"
                        "Goal: create a practical, platform-native cover image plan that can be sent to an image generation model."
                    ),
                    temperature=0.2,
                    max_tokens=420,
                )
                usage = llm["usage"]
                retry_count = int(llm.get("retry_count", 0))
                payload, usage, parse_strategy = self._validate_with_repair(
                    raw=llm["text"],
                    schema=ImagePlanModel,
                    fallback_model=fallback,
                    usage=usage,
                    repair_requirements=repair_requirements,
                    repair_max_tokens=280,
                )
        except Exception as exc:
            error = str(exc)
            payload = fallback.model_dump()
            parse_strategy = "exception-fallback"

        image_plans = self._build_image_plans_from_rule(state, payload)
        updates = {"image_plan": payload, "image_plans": image_plans}
        updates.update(
            self._record_node(
                state,
                "plan_cover",
                started,
                usage=usage,
                error=error,
                event_payload={
                    "parse_strategy": parse_strategy,
                    "overlay_text": payload.get("overlay_text", ""),
                    "retry_count": retry_count,
                    "image_plan_count": len(image_plans),
                },
            )
        )
        return updates

    def node_generate_cover(self, state: MediaAgentState) -> Dict[str, Any]:
        started = time.perf_counter()
        plan = dict(state.get("image_plan", {}))
        all_plans = list(state.get("image_plans") or [])
        if not all_plans and plan:
            all_plans = [plan]
        error = ""
        asset: Dict[str, Any]
        retry_count = 0
        cover_n = max(1, min(4, int(state.get("cover_candidate_count") or 1)))
        image_mock_eff = bool(
            (state.get("runtime_flags") or {}).get("image_mock", self.settings.image_mock)
        )
        candidates: List[Dict[str, Any]] = []
        image_assets: List[Dict[str, Any]] = []
        try:
            if cover_n <= 1:
                asset = self._generate_cover_asset(
                    run_id=state["run_id"],
                    plan=plan,
                    image_mock=image_mock_eff,
                )
                retry_count = int(asset.get("retry_count", 0))
                ca = dict(asset)
                ca["candidate_index"] = 0
                ca["is_primary"] = True
                candidates = [ca]
            else:
                plans = [dict(plan) for _ in range(cover_n)]
                batch = asyncio.run(
                    self._generate_cover_assets_batch_resilient(
                        plans,
                        run_prefix=state["run_id"],
                        image_mock=image_mock_eff,
                        concurrency=cover_n,
                    )
                )
                for item in batch:
                    ca = dict(item["asset"])
                    idx = int(item["index"])
                    ca["candidate_index"] = idx
                    ca["is_primary"] = idx == 0
                    ca["wall_time_ms"] = item.get("wall_time_ms")
                    ca["run_id"] = item.get("run_id", "")
                    candidates.append(ca)
                if not candidates:
                    raise RuntimeError("All cover candidates failed to generate.")
                asset = candidates[0]
                retry_count = max(int(c.get("retry_count", 0) or 0) for c in candidates)
            image_assets = [dict(asset)]
            extra_plans = [p for p in all_plans if str(p.get("asset_type") or "cover") != "cover"]
            for index, extra_plan in enumerate(extra_plans, start=1):
                extra_asset = self._generate_cover_asset(
                    run_id=f"{state['run_id']}-{extra_plan.get('asset_type', 'asset')}-{index:02d}",
                    plan=extra_plan,
                    image_mock=image_mock_eff,
                )
                extra_asset["asset_index"] = len(image_assets)
                image_assets.append(extra_asset)
        except Exception as exc:
            error = str(exc)
            retry_count = self.settings.image_max_retries
            asset = self._mock_cover_asset(
                run_id=state["run_id"],
                plan=plan
                or {
                    "overlay_text": state.get("draft", {}).get("title", "Media Agent"),
                    "prompt": state.get("brief", ""),
                },
            )
            asset["status"] = "fallback_mock_generated"
            ca = dict(asset)
            ca["candidate_index"] = 0
            ca["is_primary"] = True
            candidates = [ca]
            image_assets = [dict(asset)]

        updates = {
            "image_asset": asset,
            "image_assets": image_assets,
            "cover_candidates": candidates,
        }
        node_latency = round((time.perf_counter() - started) * 1000, 2)
        updates.update(
            self._record_node(
                state,
                "generate_cover",
                started,
                usage=self._base_usage(),
                error=error,
                event_payload={
                    "status": asset.get("status", ""),
                    "provider": asset.get("provider", ""),
                    "model": asset.get("model", ""),
                    "requested_size": asset.get("requested_size", ""),
                    "web_path": asset.get("web_path", ""),
                    "retry_count": retry_count,
                    "latency_ms": asset.get("latency_ms", 0.0),
                    "cover_candidate_count": cover_n,
                    "cover_candidates_returned": len(candidates),
                    "image_assets_returned": len(image_assets),
                    "node_total_ms": node_latency,
                },
            )
        )
        return updates

    def _vision_image_parts_for_asset(self, asset: Dict[str, Any]) -> List[Dict[str, Any]]:
        mime = (asset.get("mime_type") or "image/png").split(";")[0].strip()
        local_path = asset.get("local_path") or ""
        if local_path and os.path.isfile(local_path):
            if mime == "image/svg+xml":
                return []
            try:
                raw = Path(local_path).read_bytes()
            except OSError:
                return []
            b64 = b64encode(raw).decode("ascii")
            return [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]
        url = asset.get("image_url") or ""
        if url.startswith("http"):
            return [{"type": "image_url", "image_url": {"url": url}}]
        return []

    def _mock_cover_visual_review_payload(self, state: MediaAgentState) -> Dict[str, Any]:
        draft = state.get("adapted") or state.get("draft") or {}
        title = str(draft.get("title") or "")[:80]
        brief = str(state.get("brief") or "")[:400]
        plan = state.get("image_plan") or {}
        overlay = str(plan.get("overlay_text") or "")[:40]
        theme_hint = any(
            kw in brief or kw in title
            for kw in ("判断", "信息", "趋势", "思考", "认知")
        )
        overlay_ok = bool(overlay) and (overlay[:12] in title or overlay[:8] in brief[:120])
        theme_match = 78 if theme_hint else 62
        if overlay_ok:
            theme_match = min(95, theme_match + 12)
        readability = 74 if len(overlay) <= 22 else 64
        composition = 80 if theme_hint else 68
        overall = int(round((theme_match + readability + composition) / 3))
        risk_flags: List[str] = []
        if not overlay_ok and overlay:
            risk_flags.append("title_overlay_mismatch")
        if theme_match < 70:
            risk_flags.append("theme_alignment_weak")
        feedback = (
            "Mock 视觉质检：封面与标题/摘要整体匹配度尚可，适合作为低成本验证。"
            if overall >= 65
            else "Mock 视觉质检：主题或构图存在偏差，建议更换或微调封面。"
        )
        return CoverVisualReviewPayloadModel(
            theme_match_score=theme_match,
            readability_score=readability,
            composition_score=composition,
            overall_score=overall,
            risk_flags=risk_flags,
            feedback=feedback,
            review_mode="mock",
            vision_model=self.settings.vision_model,
        ).model_dump()

    def _call_vision_review_api(
        self,
        state: MediaAgentState,
        image_parts: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not self.vision_client or not image_parts:
            raise RuntimeError("vision_client_or_image_unavailable")
        draft = state.get("adapted") or state.get("draft") or {}
        title = str(draft.get("title") or "Untitled")[:80]
        body_excerpt = str(draft.get("content") or "")[:500]
        tags = draft.get("tags") or []
        plan = state.get("image_plan") or {}
        user_text = (
            f"brief={state.get('brief', '')[:800]}\n"
            f"title={title}\n"
            f"tags={tags}\n"
            f"content_excerpt={body_excerpt}\n"
            f"image_plan_prompt={plan.get('prompt', '')[:400]}\n"
            f"overlay_text={plan.get('overlay_text', '')[:80]}\n"
            "请仅根据图像与上述文本，输出 JSON。"
        )
        system_prompt = (
            "你是封面图视觉质检助手。根据配图与文本，评估主题一致性、可读性、构图。"
            "只输出一个 JSON 对象，键必须包含："
            "theme_match_score, readability_score, composition_score, overall_score（均为 0-100 整数）, "
            "passed（布尔）, risk_flags（字符串数组，可为空）, feedback（中文短句）。"
            "不要输出 markdown 或解释性文字。"
        )
        request: Dict[str, Any] = {
            "model": self.settings.vision_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [{"type": "text", "text": user_text}, *image_parts],
                },
            ],
            "temperature": 0.1,
            "max_tokens": 700,
        }
        if self.settings.enable_json_mode:
            request["response_format"] = {"type": "json_object"}
        try:
            response = self.vision_client.chat.completions.create(**request)
        except Exception:
            if request.pop("response_format", None):
                response = self.vision_client.chat.completions.create(**request)
            else:
                raise
        text = ""
        if response.choices:
            text = response.choices[0].message.content or ""
        if not text.strip():
            raise RuntimeError("Vision model returned empty content.")
        usage = self._usage_to_dict(response.usage) if response.usage else self._base_usage()
        fallback = CoverVisualReviewPayloadModel(
            theme_match_score=0,
            readability_score=0,
            composition_score=0,
            overall_score=0,
            feedback="视觉模型返回无法解析，已回退。",
            review_mode="fallback",
            vision_model=self.settings.vision_model,
        )
        validated = parse_and_validate_schema(text, CoverVisualReviewPayloadModel, fallback)
        payload = validated.value.model_dump()
        payload["review_mode"] = "real"
        payload["vision_model"] = self.settings.vision_model
        return {"payload": payload, "usage": usage, "parse_strategy": validated.parse_strategy}

    def node_review_cover_visual(self, state: MediaAgentState) -> Dict[str, Any]:
        started = time.perf_counter()
        flags = state.get("runtime_flags") or {}
        effective_mock = bool(flags.get("vision_review_mock", self.settings.vision_review_mock))
        asset = dict(state.get("image_asset") or {})
        image_parts = self._vision_image_parts_for_asset(asset)
        usage = self._base_usage()
        error = ""
        parse_strategy = "mock"
        event_mode = "mock"

        if not asset.get("local_path") and not asset.get("image_url"):
            payload = CoverVisualReviewPayloadModel(
                theme_match_score=0,
                readability_score=0,
                composition_score=0,
                overall_score=0,
                passed=False,
                risk_flags=["missing_cover_image"],
                feedback="无主图可供视觉质检。",
                review_mode="skipped",
                vision_model="",
            ).model_dump()
            updates = {"cover_visual_review": payload}
            updates.update(
                self._record_node(
                    state,
                    "review_cover_visual",
                    started,
                    usage=usage,
                    error="",
                    event_payload={
                        "review_mode": "skipped",
                        "parse_strategy": "no-image",
                    },
                )
            )
            return updates

        if effective_mock or not self.vision_client:
            payload = self._mock_cover_visual_review_payload(state)
            event_mode = "mock"
            if not effective_mock and not self.vision_client:
                payload["review_mode"] = "fallback_mock"
                payload["feedback"] = (
                    payload.get("feedback", "")
                    + "（未配置 STEPFUN_VISION_API_KEY，已使用 mock。）"
                ).strip()
                event_mode = "fallback_mock"
        elif not image_parts:
            payload = self._mock_cover_visual_review_payload(state)
            payload["risk_flags"] = list(
                dict.fromkeys(
                    list(payload.get("risk_flags") or []) + ["svg_or_unreadable_image_for_vision_api"]
                )
            )
            payload["review_mode"] = "fallback_mock"
            payload["feedback"] = (
                payload.get("feedback", "") + " SVG 或未支持的格式，未调用视觉模型。"
            ).strip()
            event_mode = "fallback_mock"
        else:
            try:
                result = self._call_vision_review_api(state, image_parts)
                payload = result["payload"]
                usage = result["usage"]
                parse_strategy = result.get("parse_strategy", "direct")
                event_mode = "real"
            except Exception as exc:
                error = str(exc)
                payload = self._mock_cover_visual_review_payload(state)
                payload["review_mode"] = "fallback_mock"
                payload["risk_flags"] = list(
                    dict.fromkeys(
                        list(payload.get("risk_flags") or []) + ["vision_api_error"]
                    )
                )
                payload["feedback"] = (
                    f"{payload.get('feedback', '')} API 失败：{error[:200]}"
                ).strip()
                event_mode = "fallback_mock"

        updates = {"cover_visual_review": payload}
        updates.update(
            self._record_node(
                state,
                "review_cover_visual",
                started,
                usage=usage,
                error=error,
                event_payload={
                    "review_mode": event_mode,
                    "parse_strategy": parse_strategy,
                    "overall_score": payload.get("overall_score"),
                    "passed": payload.get("passed"),
                },
            )
        )
        return updates

    def node_review_structured(self, state: MediaAgentState) -> Dict[str, Any]:
        started = time.perf_counter()
        threshold = int(state.get("reviewer_threshold", 21))
        base_total = 18 if state.get("revision_count", 0) == 0 and state.get("max_revisions", 0) > 0 else 24
        fallback = ReviewPayloadModel(
            attraction_score=base_total // 3,
            accuracy_score=base_total // 3,
            platform_score=base_total - 2 * (base_total // 3),
            total_score=base_total,
            feedback=(
                "第一版钩子和平台适配不够，可以继续重写。"
                if base_total < threshold
                else "结构清晰，可以进入审批。"
            ),
            passed=base_total >= threshold,
        )
        usage = self._base_usage()
        error = ""
        parse_strategy = "mock"
        retry_count = 0
        ttft_ms: Optional[float] = None
        streamed_chunks = 0
        try:
            if self.settings.llm_mock:
                raw = fallback.model_dump_json(ensure_ascii=False)
                usage = {"prompt_tokens": 90, "completion_tokens": 120, "total_tokens": 210}
            else:
                repair_requirements = (
                    "Return JSON object with attraction_score, accuracy_score, platform_score, total_score, feedback, passed. "
                    "Score fields must be integers from 1 to 10 except total_score which equals the sum. "
                    "feedback must be short Chinese text, no more than 18 Chinese characters. "
                    "passed must be boolean and should align with total_score >= 21."
                )
                llm = self._call_llm(
                    "Strict reviewer. Raw JSON one line. Keys: attraction_score, accuracy_score, platform_score, total_score, feedback, passed. No markdown.",
                    (
                        f"platform={state['platform']}\n"
                        f"content={state.get('adapted', {}).get('content', '')[:900]}\n"
                        "Scores 1–10; total_score = sum; feedback ≤18 Chinese chars; say if rewrite needed."
                    ),
                    temperature=0.0,
                    stream_node="review_structured",
                )
                raw = llm["text"]
                usage = llm["usage"]
                retry_count = int(llm.get("retry_count", 0))
                ttft_ms = llm.get("ttft_ms")
                streamed_chunks = int(llm.get("streamed_chunks", 0))
                payload, usage, parse_strategy = self._validate_with_repair(
                    raw=raw,
                    schema=ReviewPayloadModel,
                    fallback_model=fallback,
                    usage=usage,
                    repair_requirements=repair_requirements,
                    repair_max_tokens=160,
                )
            if self.settings.llm_mock:
                validated = parse_and_validate_schema(raw, ReviewPayloadModel, fallback)
                parse_strategy = validated.parse_strategy
                payload = validated.value.model_dump()
        except Exception as exc:
            error = str(exc)
            payload = fallback.model_dump()
            parse_strategy = "exception-fallback"

        payload["passed"] = int(payload.get("total_score", 0)) >= threshold
        updates = {
            "review": payload,
            "review_feedback": payload.get("feedback", ""),
        }
        updates.update(
            self._record_node(
                state,
                "review_structured",
                started,
                usage=usage,
                error=error,
                event_payload={
                    "parse_strategy": parse_strategy,
                    "total_score": payload.get("total_score", 0),
                    "passed": payload.get("passed", False),
                    "retry_count": retry_count,
                    "ttft_ms": ttft_ms,
                    "streamed_chunks": streamed_chunks,
                },
            )
        )
        return updates

    def node_review_route(self, state: MediaAgentState) -> Dict[str, Any]:
        started = time.perf_counter()
        review = state.get("review", {})
        score = int(review.get("total_score", 0))
        threshold = int(state.get("reviewer_threshold", 21))
        revision_count = int(state.get("revision_count", 0))
        max_revisions = int(state.get("max_revisions", 0))
        if score < threshold and revision_count < max_revisions:
            status = "rewrite_pending"
            next_revision_count = revision_count + 1
        else:
            status = "ready_for_approval"
            next_revision_count = revision_count
        updates = {
            "status": status,
            "revision_count": next_revision_count,
        }
        updates.update(
            self._record_node(
                state,
                "review_route",
                started,
                event_payload={
                    "score": score,
                    "threshold": threshold,
                    "status": status,
                    "revision_count": next_revision_count,
                },
            )
        )
        return updates

    def node_approval_gate(self, state: MediaAgentState) -> Dict[str, Any]:
        started = time.perf_counter()
        decision = state.get("approval_decision", "approve")
        if decision not in {"approve", "needs_edit", "reject"}:
            decision = "approve"
        approval = ApprovalPayloadModel(
            decision=decision,
            note=state.get("approval_note", ""),
            at=_utc_now(),
        )
        status = {
            "approve": "ready_for_export",
            "needs_edit": "needs_manual_edit",
            "reject": "rejected",
        }[decision]
        updates = {
            "approval": approval.model_dump(),
            "status": status,
        }
        updates.update(
            self._record_node(
                state,
                "approval_gate",
                started,
                event_payload={"decision": decision, "status": status},
            )
        )
        return updates

    def node_export(self, state: MediaAgentState) -> Dict[str, Any]:
        started = time.perf_counter()
        final_body = state.get("adapted", {}).get("content") or state.get("draft", {}).get("content", "")
        image_plan = dict(state.get("image_plan", {}))
        image_plans = list(state.get("image_plans") or [])
        image_asset = dict(state.get("image_asset", {}))
        image_assets = list(state.get("image_assets") or [])
        if not image_assets and image_asset:
            image_assets = [image_asset]
        cover_candidates = list(state.get("cover_candidates") or [])
        if not cover_candidates and image_asset:
            ca = dict(image_asset)
            ca.setdefault("candidate_index", 0)
            ca.setdefault("is_primary", True)
            cover_candidates = [ca]
        platform_rule = dict(state.get("platform_rule") or get_platform_rule(state["platform"]))
        draft_tags = state.get("draft", {}).get("tags", [])
        formats = _normalize_export_formats(state.get("export_formats"))
        text_image_consistency = compute_text_image_consistency(
            brief=state.get("brief", ""),
            title=state.get("draft", {}).get("title", "Untitled"),
            content=final_body,
            tags=draft_tags,
            image_plan=image_plan,
            image_asset=image_asset,
        )
        cover_visual_review = dict(state.get("cover_visual_review") or {})
        image_assets_summary = [
            {
                "asset_index": int(asset.get("asset_index", i)),
                "asset_type": asset.get("asset_type", "cover"),
                "usage": asset.get("usage", ""),
                "web_path": asset.get("web_path", ""),
                "image_url": asset.get("image_url", ""),
                "status": asset.get("status", ""),
                "model": asset.get("model", ""),
                "requested_size": asset.get("requested_size", ""),
            }
            for i, asset in enumerate(image_assets)
        ]
        publish_package = {
            "platform": state["platform"],
            "title": state.get("draft", {}).get("title", "Untitled"),
            "content": final_body,
            "tags": draft_tags,
            "image_assets": image_assets_summary,
            "copy_blocks": {
                "title": state.get("draft", {}).get("title", "Untitled"),
                "body": final_body,
                "tags": " ".join(draft_tags),
            },
            "checks": platform_rule.get("publish_checks", []),
            "manual_steps": platform_rule.get("publish_steps", []),
            "automation_research": {
                "official_api_first": True,
                "no_password_storage": True,
                "no_captcha_bypass": True,
                "status": "prepared_package_only",
                "note": "当前版本先交付发布准备包；仅在平台提供官方开放能力时再接自动发布。",
            },
        }
        package = ExportPackageModel(
            run_id=state["run_id"],
            request_id=state.get("request_id", state["run_id"]),
            brief=state["brief"],
            platform=state["platform"],
            style=state["style"],
            export_formats=formats,
            title=state.get("draft", {}).get("title", "Untitled"),
            content=final_body,
            tags=draft_tags,
            image_plan=image_plan,
            image_plans=image_plans,
            image_asset=image_asset,
            image_assets=image_assets,
            cover_candidates=cover_candidates,
            platform_rule=platform_rule,
            publish_package=publish_package,
            cover_visual_review=cover_visual_review,
            review=state.get("review", {}),
            approval=state.get("approval", {}),
            trace=list(state.get("trace", [])) + ["export"],
            revision_count=int(state.get("revision_count", 0)),
            graph_version=state.get("graph_version", self.layout.version),
            metrics_summary=_copy_metrics(state.get("metrics")).get("totals", {}),
            text_image_consistency=text_image_consistency,
            created_at=_utc_now(),
        )
        out_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "outputs")
        )
        os.makedirs(out_dir, exist_ok=True)
        rid = state["run_id"]
        json_path = os.path.abspath(os.path.join(out_dir, f"{rid}.v2.json"))
        md_path = os.path.abspath(os.path.join(out_dir, f"{rid}.v2.md"))
        txt_path_abs = os.path.abspath(os.path.join(out_dir, f"{rid}.v2.txt"))
        html_path_abs = os.path.abspath(os.path.join(out_dir, f"{rid}.v2.html"))
        if "json" not in formats:
            formats = ["json"] + [x for x in formats if x != "json"]
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(package.model_dump(), f, ensure_ascii=False, indent=2)
        if "md" in formats:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(f"# {package.title}\n\n")
                f.write(f"- run_id: {package.run_id}\n")
                f.write(f"- request_id: {package.request_id}\n")
                f.write(f"- graph_version: {state.get('graph_version', self.layout.version)}\n")
                f.write(f"- platform: {package.platform}\n")
                f.write(f"- style: {package.style}\n")
                f.write(f"- review_score: {package.review.get('total_score', 0)}/30\n")
                tic = package.text_image_consistency
                f.write(
                    f"- text_image_consistency: {tic.get('status', '')} "
                    f"(score={tic.get('score', 0)})\n"
                )
                cvr = cover_visual_review
                if cvr:
                    f.write(
                        f"- cover_visual_review: overall={cvr.get('overall_score', 0)} "
                        f"passed={cvr.get('passed')} "
                        f"mode={cvr.get('review_mode', '')}\n"
                    )
                    f.write(f"- cover_visual_review_feedback: {cvr.get('feedback', '')}\n\n")
                else:
                    f.write("\n")
                if image_asset.get("web_path") or image_asset.get("image_url"):
                    f.write(f"- cover_web_path: {image_asset.get('web_path', '')}\n")
                    if image_asset.get("image_url"):
                        f.write(f"- cover_image_url: {image_asset.get('image_url', '')}\n")
                    if len(cover_candidates) > 1:
                        f.write(f"- cover_candidate_count: {len(cover_candidates)}\n")
                        for c in cover_candidates:
                            if not c.get("is_primary") and c.get("web_path"):
                                f.write(f"- cover_candidate_web_path: {c.get('web_path', '')}\n")
                    f.write("\n")
                if image_assets_summary:
                    f.write("## 图片素材清单\n\n")
                    for item in image_assets_summary:
                        f.write(
                            f"- {item.get('usage') or item.get('asset_type')}: "
                            f"{item.get('web_path') or item.get('image_url')}\n"
                        )
                    f.write("\n")
                f.write("## 正文\n\n")
                f.write(package.content)
                if package.tags:
                    f.write("\n\n")
                    f.write(" ".join(package.tags))
                    f.write("\n")
        txt_written = ""
        if "txt" in formats:
            txt_lines = [package.title, "", package.content]
            if package.tags:
                txt_lines.extend(["", " ".join(package.tags)])
            with open(txt_path_abs, "w", encoding="utf-8") as f:
                f.write("\n".join(txt_lines))
            txt_written = txt_path_abs
        html_written = ""
        if "html" in formats:
            safe_title = html.escape(package.title, quote=True)
            safe_content = html.escape(package.content, quote=True)
            safe_tags = html.escape(" ".join(package.tags), quote=True)
            doc = (
                "<!doctype html><html lang=\"zh-CN\"><head>"
                '<meta charset="utf-8">'
                f"<title>{safe_title}</title>"
                "<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:2rem auto;line-height:1.7}</style>"
                "</head><body>"
                f"<article><h1>{safe_title}</h1>"
                f"<div style=\"white-space:pre-wrap\">{safe_content}</div>"
                f"<p>{safe_tags}</p></article></body></html>"
            )
            with open(html_path_abs, "w", encoding="utf-8") as f:
                f.write(doc)
            html_written = html_path_abs
        cand_summary = [
            {
                "candidate_index": int(c.get("candidate_index", i)),
                "is_primary": bool(c.get("is_primary", i == 0)),
                "web_path": c.get("web_path", ""),
                "status": c.get("status", ""),
                "latency_ms": c.get("latency_ms"),
                "requested_size": c.get("requested_size", ""),
                "model": c.get("model", ""),
            }
            for i, c in enumerate(cover_candidates)
        ]
        cpkg: Dict[str, Any] = {
            "json_path": json_path,
            "title": package.title,
            "request_id": package.request_id,
            "graph_version": package.graph_version,
            "image_url": image_asset.get("image_url", ""),
            "image_web_path": image_asset.get("web_path", ""),
            "cover_candidate_count": len(cover_candidates),
            "cover_candidates_summary": cand_summary,
            "image_assets_summary": image_assets_summary,
            "publish_package": publish_package,
            "text_image_consistency": text_image_consistency,
            "cover_visual_review": cover_visual_review,
        }
        if "md" in formats:
            cpkg["markdown_path"] = md_path
        if txt_written:
            cpkg["text_path"] = txt_written
        if html_written:
            cpkg["html_path"] = html_written
        updates = {
            "content_package": cpkg,
            "publish_package": publish_package,
            "text_image_consistency": text_image_consistency,
            "status": "completed",
        }
        updates.update(
            self._record_node(
                state,
                "export",
                started,
                event_payload={
                    "json_path": json_path,
                    "markdown_path": md_path if "md" in formats else "",
                    "text_path": txt_written,
                    "html_path": html_written,
                },
            )
        )
        return updates

    def _build_research_subgraph(self):
        builder = StateGraph(MediaAgentState)
        builder.add_node("research_topic", self._cancel_aware("research_topic", self.node_research_topic))
        builder.add_node("research_evidence_merge", self._cancel_aware("research_evidence_merge", self.node_research_evidence_merge))
        builder.add_edge(START, "research_topic")
        builder.add_edge("research_topic", "research_evidence_merge")
        builder.add_edge("research_evidence_merge", END)
        return builder.compile()

    def _build_writing_subgraph(self):
        builder = StateGraph(MediaAgentState)
        builder.add_node("write_draft", self._cancel_aware("write_draft", self.node_write_draft))
        builder.add_node("adapt_platform", self._cancel_aware("adapt_platform", self.node_adapt_platform))
        builder.add_edge(START, "write_draft")
        builder.add_edge("write_draft", "adapt_platform")
        builder.add_edge("adapt_platform", END)
        return builder.compile()

    def _build_visual_subgraph(self):
        builder = StateGraph(MediaAgentState)
        builder.add_node("plan_cover", self._cancel_aware("plan_cover", self.node_plan_cover))
        builder.add_node("generate_cover", self._cancel_aware("generate_cover", self.node_generate_cover))
        builder.add_node("review_cover_visual", self._cancel_aware("review_cover_visual", self.node_review_cover_visual))
        builder.add_edge(START, "plan_cover")
        builder.add_edge("plan_cover", "generate_cover")
        builder.add_edge("generate_cover", "review_cover_visual")
        builder.add_edge("review_cover_visual", END)
        return builder.compile()

    def _build_review_approval_subgraph(self):
        builder = StateGraph(MediaAgentState)
        builder.add_node("review_structured", self._cancel_aware("review_structured", self.node_review_structured))
        builder.add_node("review_route", self._cancel_aware("review_route", self.node_review_route))
        builder.add_node("approval_gate", self._cancel_aware("approval_gate", self.node_approval_gate))
        builder.add_edge(START, "review_structured")
        builder.add_edge("review_structured", "review_route")
        builder.add_conditional_edges(
            "review_route",
            self._route_after_review,
            {
                "rewrite": END,
                "approval": "approval_gate",
            },
        )
        builder.add_edge("approval_gate", END)
        return builder.compile()

    def _route_after_review(self, state: MediaAgentState) -> str:
        return "rewrite" if state.get("status") == "rewrite_pending" else "approval"

    def _route_after_review_subgraph(self, state: MediaAgentState) -> str:
        status = state.get("status")
        if status == "cancelled":
            return "stop"
        if status == "rewrite_pending":
            return "rewrite"
        if status == "ready_for_export":
            return "export"
        return "stop"

    def _route_after_research(self, state: MediaAgentState) -> str:
        if state.get("status") == "cancelled":
            return "stop"
        if state.get("run_mode") != "guided":
            return "writing"
        if state.get("guided_topic_locked"):
            return "writing"
        return "stop"

    def _build_continuation_graph(self):
        """writing → visual → review → export (no checkpointer); used after guided topic pick."""
        writing_subgraph = self._build_writing_subgraph()
        visual_subgraph = self._build_visual_subgraph()
        review_approval_subgraph = self._build_review_approval_subgraph()
        builder = StateGraph(MediaAgentState)
        builder.add_node("writing_subgraph", writing_subgraph)
        builder.add_node("visual_subgraph", visual_subgraph)
        builder.add_node("review_approval_subgraph", review_approval_subgraph)
        builder.add_node("export", self._cancel_aware("export", self.node_export))
        builder.add_edge(START, "writing_subgraph")
        builder.add_edge("writing_subgraph", "visual_subgraph")
        builder.add_edge("visual_subgraph", "review_approval_subgraph")
        builder.add_conditional_edges(
            "review_approval_subgraph",
            self._route_after_review_subgraph,
            {
                "rewrite": "writing_subgraph",
                "export": "export",
                "stop": END,
            },
        )
        builder.add_edge("export", END)
        return builder.compile()

    def _build_graph(self):
        research_subgraph = self._build_research_subgraph()
        writing_subgraph = self._build_writing_subgraph()
        visual_subgraph = self._build_visual_subgraph()
        review_approval_subgraph = self._build_review_approval_subgraph()

        builder = StateGraph(MediaAgentState)
        builder.add_node("brief_intake", self._cancel_aware("brief_intake", self.node_brief_intake))
        builder.add_node("research_subgraph", research_subgraph)
        builder.add_node("writing_subgraph", writing_subgraph)
        builder.add_node("visual_subgraph", visual_subgraph)
        builder.add_node("review_approval_subgraph", review_approval_subgraph)
        builder.add_node("export", self._cancel_aware("export", self.node_export))
        builder.add_node("topic_selection_stop", self._cancel_aware("topic_selection_stop", self.node_topic_selection_stop))

        builder.add_edge(START, "brief_intake")
        builder.add_edge("brief_intake", "research_subgraph")
        builder.add_conditional_edges(
            "research_subgraph",
            self._route_after_research,
            {
                "writing": "writing_subgraph",
                "stop": "topic_selection_stop",
            },
        )
        builder.add_edge("topic_selection_stop", END)
        builder.add_edge("writing_subgraph", "visual_subgraph")
        builder.add_edge("visual_subgraph", "review_approval_subgraph")
        builder.add_conditional_edges(
            "review_approval_subgraph",
            self._route_after_review_subgraph,
            {
                "rewrite": "writing_subgraph",
                "export": "export",
                "stop": END,
            },
        )
        builder.add_edge("export", END)
        return builder.compile(checkpointer=self.checkpointer)

    @traceable(name="media_agent_v2_invoke", run_type="chain")
    def _invoke_graph(
        self,
        state: MediaAgentState,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self.graph.invoke(state, config=config)

    def run_workflow(
        self,
        brief: str,
        platform: str = "小红书",
        style: str = "种草推荐",
        approval_decision: str = "approve",
        approval_note: str = "",
        reviewer_threshold: int = 21,
        max_revisions: int = 2,
        run_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        request_id: Optional[str] = None,
        runtime_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        state = self._initial_state(
            brief=brief,
            platform=platform,
            style=style,
            approval_decision=approval_decision,
            approval_note=approval_note,
            reviewer_threshold=reviewer_threshold,
            max_revisions=max_revisions,
            run_id=run_id,
            thread_id=thread_id,
            request_id=request_id,
            runtime_overrides=runtime_overrides,
        )
        config = {"configurable": {"thread_id": state["thread_id"]}}
        self.logger.info(
            "workflow_started",
            run_id=state["run_id"],
            request_id=state["request_id"],
            thread_id=state["thread_id"],
            platform=platform,
            style=style,
        )
        final_state = self._invoke_graph(state, config)
        self.logger.info(
            "workflow_completed",
            run_id=final_state["run_id"],
            request_id=final_state.get("request_id", state["request_id"]),
            status=final_state.get("status"),
            trace=final_state.get("trace", []),
            content_package=final_state.get("content_package", {}),
        )
        self._remember_run(final_state)
        return {
            "run_id": final_state["run_id"],
            "request_id": final_state.get("request_id", state["request_id"]),
            "status": final_state.get("status", "unknown"),
            "state": final_state,
            "metrics": final_state.get("metrics", _default_metrics()),
        }

    def run_workflow_continue(
        self,
        base_state: Dict[str, Any],
        selected_topic_index: int,
        approval_decision: str = "approve",
        approval_note: str = "",
        reviewer_threshold: Optional[int] = None,
        max_revisions: Optional[int] = None,
        request_id: Optional[str] = None,
        runtime_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        merged: Dict[str, Any] = copy.deepcopy(base_state)
        topics = (merged.get("research") or {}).get("topics") or []
        if not topics:
            raise ValueError("guided continue requires state.research.topics")
        if selected_topic_index < 0 or selected_topic_index >= len(topics):
            raise ValueError("selected_topic_index out of range")
        raw_topic = topics[selected_topic_index]
        if isinstance(raw_topic, dict):
            picked = ResearchTopicModel.model_validate(raw_topic).model_dump()
        else:
            picked = ResearchTopicModel.model_validate(dict(raw_topic)).model_dump()
        merged["selected_topic"] = picked
        merged["guided_topic_locked"] = True
        merged["status"] = "running"
        if request_id:
            merged["request_id"] = request_id
        merged["approval_decision"] = approval_decision
        merged["approval_note"] = approval_note
        if reviewer_threshold is not None:
            merged["reviewer_threshold"] = reviewer_threshold
        if max_revisions is not None:
            merged["max_revisions"] = max_revisions
        ro = dict(runtime_overrides or {})
        if ro.get("export_formats") is not None:
            merged["export_formats"] = _normalize_export_formats(ro.get("export_formats"))
        raw_cc = ro.get("cover_candidate_count")
        if raw_cc is not None:
            try:
                merged["cover_candidate_count"] = max(1, min(4, int(raw_cc)))
            except (TypeError, ValueError):
                pass
        flags = dict(merged.get("runtime_flags") or self._default_flags())
        if ro.get("image_mock") is not None:
            flags["image_mock"] = bool(ro["image_mock"])
        if ro.get("vision_review_mock") is not None:
            flags["vision_review_mock"] = bool(ro["vision_review_mock"])
        merged["runtime_flags"] = flags
        config: Dict[str, Any] = {
            "configurable": {"thread_id": merged.get("thread_id") or merged.get("run_id") or "default"}
        }
        self.logger.info(
            "workflow_continue_started",
            run_id=merged.get("run_id"),
            request_id=merged.get("request_id"),
            thread_id=merged.get("thread_id"),
            topic_index=selected_topic_index,
        )
        final_state = self._continuation_graph.invoke(merged, config=config)
        self.logger.info(
            "workflow_continue_completed",
            run_id=final_state.get("run_id"),
            request_id=final_state.get("request_id"),
            status=final_state.get("status"),
        )
        self._remember_run(final_state)
        return {
            "run_id": final_state["run_id"],
            "request_id": final_state.get("request_id", merged.get("request_id")),
            "status": final_state.get("status", "unknown"),
            "state": final_state,
            "metrics": final_state.get("metrics", _default_metrics()),
        }

    def stream_workflow(
        self,
        brief: str,
        platform: str = "小红书",
        style: str = "种草推荐",
        approval_decision: str = "approve",
        approval_note: str = "",
        reviewer_threshold: int = 21,
        max_revisions: int = 2,
        run_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        request_id: Optional[str] = None,
        runtime_overrides: Optional[Dict[str, Any]] = None,
    ):
        state = self._initial_state(
            brief=brief,
            platform=platform,
            style=style,
            approval_decision=approval_decision,
            approval_note=approval_note,
            reviewer_threshold=reviewer_threshold,
            max_revisions=max_revisions,
            run_id=run_id,
            thread_id=thread_id,
            request_id=request_id,
            runtime_overrides=runtime_overrides,
        )
        config = {"configurable": {"thread_id": state["thread_id"]}}
        stream_context = {
            "run_id": state["run_id"],
            "thread_id": state["thread_id"],
            "request_id": state["request_id"],
        }
        self.logger.info(
            "workflow_stream_started",
            run_id=state["run_id"],
            request_id=state["request_id"],
            thread_id=state["thread_id"],
        )
        yield {
            "event": "start",
            "data": {
                "run_id": state["run_id"],
                "thread_id": state["thread_id"],
                "request_id": state["request_id"],
            },
        }
        queue: Queue[Optional[Dict[str, Any]]] = Queue()

        def push_event(event_name: str, data: Dict[str, Any]) -> None:
            payload = dict(stream_context)
            payload.update(data)
            queue.put({"event": event_name, "data": payload})

        def worker() -> None:
            values: Dict[str, Any] = {}
            self._set_stream_emitter(push_event, context=stream_context)
            try:
                for chunk in self.graph.stream(state, config=config, stream_mode="updates"):
                    push_event("update", chunk)
                snapshot = self.graph.get_state(config)
                values = snapshot.values if snapshot else {}
                push_event(
                    "final",
                    {
                        "status": values.get("status", "unknown"),
                        "trace": values.get("trace", []),
                        "metrics": values.get("metrics", _default_metrics()),
                        "title": values.get("title", ""),
                        "content": values.get("content", ""),
                        "tags": values.get("tags", []),
                        "draft": values.get("draft", {}),
                        "adapted": values.get("adapted", {}),
                        "image_plan": values.get("image_plan", {}),
                        "image_asset": values.get("image_asset", {}),
                        "cover_candidates": values.get("cover_candidates", []),
                        "content_package": values.get("content_package", {}),
                        "text_image_consistency": values.get("text_image_consistency", {}),
                        "cover_visual_review": values.get("cover_visual_review", {}),
                        "research": values.get("research", {}),
                        "run_mode": values.get("run_mode"),
                        "guided_topic_locked": values.get("guided_topic_locked"),
                        "selected_topic": values.get("selected_topic", {}),
                    },
                )
                self.logger.info(
                    "workflow_stream_completed",
                    run_id=state["run_id"],
                    request_id=state["request_id"],
                    status=values.get("status", "unknown"),
                    trace=values.get("trace", []),
                )
                self._remember_run(values)
            except Exception as exc:
                self.logger.info(
                    "workflow_stream_failed",
                    run_id=state["run_id"],
                    request_id=state["request_id"],
                    error=str(exc),
                )
                push_event("error", {"detail": str(exc)})
            finally:
                self._clear_stream_emitter()
                queue.put(None)

        worker_thread = Thread(target=worker, daemon=True)
        worker_thread.start()
        try:
            while True:
                item = queue.get()
                if item is None:
                    break
                yield item
        finally:
            worker_thread.join(timeout=1.0)

    def get_run(self, run_id: str, thread_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        cached = self._run_cache.get(run_id)
        if cached:
            return {
                "run_id": run_id,
                "state": copy.deepcopy(cached),
                "status": cached.get("status", "unknown"),
            }
        config = {"configurable": {"thread_id": thread_id or run_id}}
        snapshot = self.graph.get_state(config)
        if not snapshot or not snapshot.values:
            return None
        self.logger.info(
            "workflow_snapshot_loaded",
            run_id=run_id,
            thread_id=thread_id or run_id,
            status=snapshot.values.get("status", "unknown"),
        )
        return {
            "run_id": run_id,
            "state": snapshot.values,
            "status": snapshot.values.get("status", "unknown"),
        }
