"""``chat`` spans and GenAI metrics for LLM calls.

Called from the token-usage wrappers in ``docsgpt/usage.py``: one span per
decorated invocation, so a primary attempt, its same-provider retry and a
fallback each get their own span with the provider that actually ran.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from docsgpt.tracing import core
from docsgpt.tracing.otel import provider_name, record_llm_metrics

#: LLM attribute a cache wrapper sets when it served the call from Redis.
CACHE_HIT_ATTR = "_trace_cache_hit"


def start_llm_span(llm: Any, model: Optional[str], *, stream: bool, tools: Any = None):
    """Open a ``chat {model}`` span for a call on ``llm`` (no-op without a trace)."""
    if core.current_trace() is None:
        return core.NOOP_SPAN
    attributes = {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": provider_name(getattr(llm, "provider_name", None)),
        "gen_ai.request.model": str(model) if model else None,
        "docsgpt.token_source": getattr(llm, "_token_usage_source", None) or "agent_stream",
        "docsgpt.stream": bool(stream),
        "docsgpt.tool_count": len(tools) if tools else None,
    }
    return core.start_span(
        core.KIND_LLM,
        f"chat {model}" if model else "chat",
        attributes={k: v for k, v in attributes.items() if v is not None},
    )


def output_text(chunks: Iterable[Any]) -> str:
    """Concatenate the text deltas of a streamed or returned response."""
    if isinstance(chunks, str):
        return chunks
    return "".join(chunk for chunk in chunks if isinstance(chunk, str))


def finish_llm_call(
    span: Any,
    llm: Any,
    model: Optional[str],
    call_usage: Dict[str, Any],
    *,
    duration_ms: int,
    error: Optional[BaseException],
    completed: bool = True,
    ttft_ms: Optional[int] = None,
    cost_usd: Optional[float] = None,
    estimated: bool = True,
    output: Optional[str] = None,
) -> None:
    """Close the call's span and record the GenAI client metrics.

    Args:
        span: The span from :func:`start_llm_span`.
        llm: The LLM instance that ran the call.
        model: Model the call was made with.
        call_usage: Final token counts (provider-reported when available).
        duration_ms: Provider time for the call.
        error: The exception the call raised, if any.
        completed: False when a stream was abandoned before it finished.
        ttft_ms: Time to first streamed chunk.
        cost_usd: Cost priced for the call, when known.
        estimated: True when token counts are local estimates.
        output: Response text for the preview.
    """
    cache_hit = bool(getattr(llm, CACHE_HIT_ATTR, False))
    try:
        setattr(llm, CACHE_HIT_ATTR, False)
    except AttributeError:
        pass
    record_llm_metrics(
        provider=getattr(llm, "provider_name", None),
        model=str(model) if model else None,
        input_tokens=call_usage.get("prompt_tokens", 0),
        output_tokens=call_usage.get("generated_tokens", 0),
        duration_s=max(duration_ms, 0) / 1000.0,
        error_type=type(error).__name__ if error is not None else None,
    )
    if not span:
        return
    if output:
        span.preview("output", output)
    span.end(
        None if completed or error is not None else core.STATUS_CANCELLED,
        error=error,
        attributes={
            "gen_ai.usage.input_tokens": int(call_usage.get("prompt_tokens") or 0),
            "gen_ai.usage.output_tokens": int(call_usage.get("generated_tokens") or 0),
            "gen_ai.usage.cache_read.input_tokens": call_usage.get("cached_tokens"),
            "gen_ai.usage.cache_creation.input_tokens": call_usage.get("cache_write_tokens"),
            "docsgpt.usage_estimated": estimated,
            "docsgpt.provider_ms": duration_ms,
            "docsgpt.ttft_ms": ttft_ms,
            "docsgpt.cost_usd": cost_usd if isinstance(cost_usd, (int, float)) else None,
            "docsgpt.cache_hit": True if cache_hit else None,
        },
    )


def record_cached_gen(llm: Any, model: Optional[str], output: Optional[str]) -> None:
    """Record a non-streaming call answered from the response cache.

    The gen cache wraps the usage wrapper, so a hit never reaches it; this
    records the zero-cost call so the trace still shows it happened.
    """
    span = start_llm_span(llm, model, stream=False)
    if not span:
        return
    if output:
        span.preview("output", output)
    span.end(attributes={"docsgpt.cache_hit": True})
