from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import structlog

try:
    from langsmith import traceable as _langsmith_traceable
except Exception:
    _langsmith_traceable = None


def traceable(*args, **kwargs):
    if _langsmith_traceable is None:
        def decorator(func):
            return func

        return decorator
    return _langsmith_traceable(*args, **kwargs)


@lru_cache(maxsize=8)
def get_struct_logger(name: str, log_path: str):
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    logger_name = f"media_agent_v2.{name}.{abs(hash(str(path)))}"
    base_logger = logging.getLogger(logger_name)
    base_logger.setLevel(logging.INFO)
    base_logger.handlers.clear()
    base_logger.propagate = False

    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    base_logger.addHandler(handler)

    wrapped = structlog.wrap_logger(
        base_logger,
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
    )
    return wrapped.bind(component=name)
