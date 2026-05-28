from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

@dataclass(frozen=True)
class JsonParseResult:
    ok: bool
    value: Any
    strategy: str
    error: str = ""


def parse_json_with_fallback(raw: str, fallback: Any) -> JsonParseResult:
    """Small migration-safe placeholder for the v2 JSON parsing path.

    Final implementation target:
    1. JSON mode response
    2. json.loads
    3. salvage extraction
    4. Pydantic validation
    """

    try:
        return JsonParseResult(ok=True, value=json.loads(raw), strategy="direct")
    except Exception as exc:
        direct_error = str(exc)

    fenced_matches = re.findall(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
    for candidate in fenced_matches:
        try:
            return JsonParseResult(
                ok=True,
                value=json.loads(candidate.strip()),
                strategy="fenced-salvage",
            )
        except Exception:
            continue

    decoder = json.JSONDecoder()
    for idx, char in enumerate(raw):
        if char not in "{[":
            continue
        try:
            value, end_idx = decoder.raw_decode(raw[idx:])
            strategy = "object-salvage" if char == "{" else "array-salvage"
            trailing = raw[idx + end_idx :].strip()
            if trailing:
                strategy = f"{strategy}-trailing-text"
            return JsonParseResult(ok=True, value=value, strategy=strategy)
        except Exception:
            continue

    return JsonParseResult(
        ok=False,
        value=fallback,
        strategy="fallback",
        error=direct_error,
    )


SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass(frozen=True)
class SchemaValidationResult:
    ok: bool
    value: BaseModel
    parse_strategy: str
    validation_error: str = ""


def parse_and_validate_schema(
    raw: str,
    schema: type[SchemaT],
    fallback_model: SchemaT,
) -> SchemaValidationResult:
    parsed = parse_json_with_fallback(raw, fallback_model.model_dump())
    try:
        value = schema.model_validate(parsed.value)
        return SchemaValidationResult(
            ok=parsed.ok,
            value=value,
            parse_strategy=parsed.strategy,
        )
    except ValidationError as exc:
        return SchemaValidationResult(
            ok=False,
            value=fallback_model,
            parse_strategy=f"{parsed.strategy}-validation-fallback",
            validation_error=str(exc),
        )
