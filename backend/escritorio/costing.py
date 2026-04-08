from __future__ import annotations

from typing import Any

from backend.escritorio.models import RatioEscritorioState


def _read_usage_value(usage: Any, *names: str) -> int:
    for name in names:
        if isinstance(usage, dict) and name in usage:
            try:
                return int(usage[name] or 0)
            except Exception:
                return 0
        value = getattr(usage, name, None)
        if value is not None:
            try:
                return int(value or 0)
            except Exception:
                return 0
    return 0


def extract_usage_counts(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        usage = getattr(response, "usageMetadata", None)
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    prompt_tokens = _read_usage_value(
        usage,
        "prompt_token_count",
        "promptTokenCount",
        "input_token_count",
        "inputTokenCount",
    )
    completion_tokens = _read_usage_value(
        usage,
        "candidates_token_count",
        "candidatesTokenCount",
        "output_token_count",
        "outputTokenCount",
    )
    total_tokens = _read_usage_value(usage, "total_token_count", "totalTokenCount")
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens
    return {
        "prompt_tokens": max(0, prompt_tokens),
        "completion_tokens": max(0, completion_tokens),
        "total_tokens": max(0, total_tokens),
    }


def estimate_gemini_cost_usd(model_name: str, *, prompt_tokens: int, completion_tokens: int) -> float:
    model = str(model_name or "").strip().lower()

    if model == "gemini-3-flash-preview":
        input_rate = 0.50
        output_rate = 3.00
    elif model == "gemini-3.1-pro-preview":
        threshold = max(0, int(prompt_tokens))
        input_rate = 2.00 if threshold < 200_000 else 4.00
        output_rate = 12.00 if threshold < 200_000 else 18.00
    elif model == "gemini-3.1-flash-lite-preview":
        input_rate = 0.25
        output_rate = 1.50
    else:
        return 0.0

    return round(((prompt_tokens / 1_000_000) * input_rate) + ((completion_tokens / 1_000_000) * output_rate), 8)


def build_usage_entry(*, model_name: str, response: Any, operation: str) -> dict[str, Any]:
    counts = extract_usage_counts(response)
    estimated_cost_usd = estimate_gemini_cost_usd(
        model_name,
        prompt_tokens=counts["prompt_tokens"],
        completion_tokens=counts["completion_tokens"],
    )
    return {
        "provider": "gemini",
        "model": model_name,
        "operation": operation,
        "prompt_tokens": counts["prompt_tokens"],
        "completion_tokens": counts["completion_tokens"],
        "total_tokens": counts["total_tokens"],
        "estimated_cost_usd": estimated_cost_usd,
    }


def merge_usage_into_state(
    state: RatioEscritorioState,
    *entries: dict[str, Any] | None,
) -> dict[str, Any]:
    token_log = list(state.token_log or [])
    total_cost = float(state.custo_total_usd or 0.0)
    for entry in entries:
        if not entry:
            continue
        token_log.append(entry)
        total_cost += float(entry.get("estimated_cost_usd") or 0.0)
    return {
        "token_log": token_log,
        "custo_total_usd": round(total_cost, 8),
    }
