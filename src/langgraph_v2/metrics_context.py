from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _default_totals() -> Dict[str, Any]:
    return {
        "latency_ms": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "estimated_cost_available": False,
        "cost_estimation_basis": "",
        "price_per_1k_usd": 0.0,
        "error_count": 0,
    }


@dataclass
class MetricsContext:
    node_metrics: List[Dict[str, Any]] = field(default_factory=list)
    totals: Dict[str, Any] = field(default_factory=_default_totals)

    @classmethod
    def empty(cls) -> "MetricsContext":
        return cls()

    @classmethod
    def from_payload(cls, payload: Optional[Dict[str, Any]]) -> "MetricsContext":
        cloned = json.loads(json.dumps(payload or {}, ensure_ascii=False))
        node_metrics = list(cloned.get("node_metrics", []))
        totals = _default_totals()
        totals.update(cloned.get("totals", {}))
        return cls(node_metrics=node_metrics, totals=totals)

    def add_node_metric(
        self,
        *,
        node: str,
        latency_ms: float,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        estimated_cost_usd: float,
        estimated_cost_available: bool,
        cost_estimation_basis: str,
        price_per_1k_usd: float,
        error: str,
        ts: str,
    ) -> None:
        self.node_metrics.append(
            {
                "node": node,
                "latency_ms": latency_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "estimated_cost_usd": estimated_cost_usd,
                "estimated_cost_available": estimated_cost_available,
                "cost_estimation_basis": cost_estimation_basis,
                "price_per_1k_usd": round(price_per_1k_usd, 6),
                "error": error,
                "ts": ts,
            }
        )
        self.totals["latency_ms"] = round(float(self.totals.get("latency_ms", 0.0)) + latency_ms, 2)
        self.totals["prompt_tokens"] = int(self.totals.get("prompt_tokens", 0)) + prompt_tokens
        self.totals["completion_tokens"] = int(self.totals.get("completion_tokens", 0)) + completion_tokens
        self.totals["total_tokens"] = int(self.totals.get("total_tokens", 0)) + total_tokens
        if estimated_cost_available:
            self.totals["estimated_cost_usd"] = round(
                float(self.totals.get("estimated_cost_usd", 0.0)) + estimated_cost_usd,
                6,
            )
            self.totals["estimated_cost_available"] = True
            self.totals["cost_estimation_basis"] = cost_estimation_basis
            self.totals["price_per_1k_usd"] = round(price_per_1k_usd, 6)
        elif not self.totals.get("estimated_cost_available", False):
            self.totals["estimated_cost_available"] = False
            self.totals["cost_estimation_basis"] = cost_estimation_basis
            self.totals["price_per_1k_usd"] = round(price_per_1k_usd, 6)
        if error:
            self.totals["error_count"] = int(self.totals.get("error_count", 0)) + 1
        else:
            self.totals.setdefault("error_count", 0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_metrics": list(self.node_metrics),
            "totals": dict(self.totals),
        }
