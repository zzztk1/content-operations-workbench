from __future__ import annotations

import os
from dataclasses import dataclass


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class V2Settings:
    llm_api_key: str
    llm_api_base: str
    llm_model: str
    image_api_key: str
    image_api_base: str
    image_model: str
    image_size: str
    image_quality: str
    vision_api_key: str
    vision_api_base: str
    vision_model: str
    vision_review_mock: bool
    image_download_timeout_sec: int
    image_max_retries: int
    image_retry_backoff_base_sec: float
    checkpoint_backend: str
    postgres_dsn: str
    langsmith_tracing: bool
    langsmith_tracing_v2: bool
    langsmith_endpoint: str
    langsmith_workspace_id: str
    langsmith_project: str
    llm_mock: bool
    image_mock: bool
    checkpointer_mock: bool
    enable_sse: bool
    enable_slowapi: bool
    enable_json_mode: bool
    rate_limit_per_minute: int
    graceful_shutdown_timeout_sec: int
    circuit_breaker_threshold: int
    circuit_breaker_cooldown_sec: int
    llm_max_retries: int
    llm_retry_backoff_base_sec: float
    model_price_per_1k_usd: float

    @classmethod
    def from_env(cls) -> "V2Settings":
        return cls(
            llm_api_key=os.getenv("STEPFUN_API_KEY", os.getenv("DEEPSEEK_API_KEY", "")),
            llm_api_base=os.getenv(
                "STEPFUN_API_BASE",
                os.getenv("DEEPSEEK_API_BASE", ""),
            ),
            llm_model=os.getenv("STEPFUN_MODEL", os.getenv("DEEPSEEK_MODEL", "")),
            image_api_key=os.getenv(
                "STEPFUN_IMAGE_API_KEY",
                os.getenv("STEPFUN_API_KEY", ""),
            ),
            image_api_base=os.getenv(
                "STEPFUN_IMAGE_API_BASE",
                "https://api.stepfun.com/v1",
            ),
            image_model=os.getenv("STEPFUN_IMAGE_MODEL", "step-2x-large"),
            image_size=os.getenv("STEPFUN_IMAGE_SIZE", "1024x1024"),
            image_quality=os.getenv("STEPFUN_IMAGE_QUALITY", "medium"),
            vision_api_key=os.getenv(
                "STEPFUN_VISION_API_KEY",
                os.getenv("STEPFUN_API_KEY", ""),
            ),
            vision_api_base=os.getenv(
                "STEPFUN_VISION_API_BASE",
                "https://api.stepfun.com/v1",
            ),
            vision_model=os.getenv("STEPFUN_VISION_MODEL", "step-1o-turbo-vision"),
            vision_review_mock=_as_bool(os.getenv("VISION_REVIEW_MOCK", "true"), default=True),
            image_download_timeout_sec=_as_int(
                os.getenv("IMAGE_DOWNLOAD_TIMEOUT_SEC", "45"),
                default=45,
            ),
            image_max_retries=_as_int(
                os.getenv("IMAGE_MAX_RETRIES", "2"),
                default=2,
            ),
            image_retry_backoff_base_sec=_as_float(
                os.getenv("IMAGE_RETRY_BACKOFF_BASE_SEC", "1.0"),
                default=1.0,
            ),
            checkpoint_backend=os.getenv("CHECKPOINT_BACKEND", "postgres"),
            postgres_dsn=os.getenv("POSTGRES_DSN", ""),
            langsmith_tracing=_as_bool(os.getenv("LANGSMITH_TRACING", "false")),
            langsmith_tracing_v2=_as_bool(os.getenv("LANGSMITH_TRACING_V2", "false")),
            langsmith_endpoint=os.getenv(
                "LANGSMITH_ENDPOINT",
                "https://api.smith.langchain.com",
            ),
            langsmith_workspace_id=os.getenv("LANGSMITH_WORKSPACE_ID", ""),
            langsmith_project=os.getenv("LANGSMITH_PROJECT", "media-agent-v2"),
            llm_mock=_as_bool(os.getenv("LLM_MOCK", "false")),
            image_mock=_as_bool(os.getenv("IMAGE_MOCK", "true"), default=True),
            checkpointer_mock=_as_bool(
                os.getenv("CHECKPOINTER_MOCK", "false"),
                default=False,
            ),
            enable_sse=_as_bool(os.getenv("ENABLE_SSE", "false")),
            enable_slowapi=_as_bool(os.getenv("ENABLE_SLOWAPI", "false")),
            enable_json_mode=_as_bool(os.getenv("ENABLE_JSON_MODE", "true"), default=True),
            rate_limit_per_minute=_as_int(
                os.getenv("RATE_LIMIT_PER_MINUTE", "10"),
                default=10,
            ),
            graceful_shutdown_timeout_sec=_as_int(
                os.getenv("GRACEFUL_SHUTDOWN_TIMEOUT_SEC", "15"),
                default=15,
            ),
            circuit_breaker_threshold=_as_int(
                os.getenv("LLM_CIRCUIT_BREAKER_THRESHOLD", "3"),
                default=3,
            ),
            circuit_breaker_cooldown_sec=_as_int(
                os.getenv("LLM_CIRCUIT_BREAKER_COOLDOWN_SEC", "30"),
                default=30,
            ),
            llm_max_retries=_as_int(
                os.getenv("LLM_MAX_RETRIES", "2"),
                default=2,
            ),
            llm_retry_backoff_base_sec=_as_float(
                os.getenv("LLM_RETRY_BACKOFF_BASE_SEC", "0.8"),
                default=0.8,
            ),
            model_price_per_1k_usd=_as_float(
                os.getenv("MODEL_PRICE_PER_1K_USD", "0"),
                default=0.0,
            ),
        )
