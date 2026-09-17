"""Provider-agnostic token and cost accounting."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from macpilot.core.context import estimate_tokens


@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float = 0.0
    output_per_million: float = 0.0


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def estimated_cost(self, pricing: ModelPricing) -> float:
        return (
            self.input_tokens * pricing.input_per_million
            + self.output_tokens * pricing.output_per_million
        ) / 1_000_000

    def as_dict(self, pricing: ModelPricing | None = None) -> dict[str, Any]:
        value = asdict(self)
        value["total_tokens"] = self.total_tokens
        if pricing is not None:
            value["estimated_cost_usd"] = self.estimated_cost(pricing)
        return value


def _read_usage(response: Any) -> tuple[int, int] | None:
    candidates = [
        getattr(response, "usage_metadata", None),
        getattr(response, "response_metadata", {}).get("token_usage")
        if isinstance(getattr(response, "response_metadata", None), dict)
        else None,
    ]
    for value in candidates:
        if not isinstance(value, dict):
            continue
        input_tokens = value.get("input_tokens", value.get("prompt_tokens"))
        output_tokens = value.get("output_tokens", value.get("completion_tokens"))
        if input_tokens is not None or output_tokens is not None:
            return int(input_tokens or 0), int(output_tokens or 0)
    return None


def usage_for_response(response: Any, prompt: Any, *, cache_hit: bool = False) -> TokenUsage:
    """Prefer provider-reported usage and fall back to a deterministic estimate."""
    reported = _read_usage(response)
    if reported is not None:
        return TokenUsage(*reported, cache_hit=cache_hit)
    output = getattr(response, "content", response)
    return TokenUsage(
        input_tokens=0 if cache_hit else estimate_tokens(prompt),
        output_tokens=0 if cache_hit else estimate_tokens(output),
        cache_hit=cache_hit,
    )


def pricing_from_env(model: str) -> ModelPricing:
    """Read optional per-million pricing without making pricing mandatory."""
    import os

    model_key = model.upper().replace("-", "_").replace(".", "_")
    input_price = os.getenv(f"MACPILOT_{model_key}_INPUT_USD_PER_MILLION", "0")
    output_price = os.getenv(f"MACPILOT_{model_key}_OUTPUT_USD_PER_MILLION", "0")
    return ModelPricing(float(input_price), float(output_price))


def record_model_usage(
    audit_store: Any | None,
    task_id: str | None,
    model: str,
    response: Any,
    prompt: Any,
    *,
    cache_hit: bool = False,
) -> TokenUsage:
    """Persist one normalized usage event when an audit store is available."""
    usage = usage_for_response(response, prompt, cache_hit=cache_hit)
    pricing = pricing_from_env(model)
    if audit_store is not None and task_id is not None:
        audit_store.append_event(
            "model_usage",
            {
                "model": model,
                **usage.as_dict(pricing),
            },
            task_id=task_id,
        )
    return usage
