import logging
import time
from typing import Any, Dict

from docsgpt.pricing import compute_cost_usd
from docsgpt.tracing.llm import finish_llm_call, start_llm_span
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.storage.db.session import db_session
from docsgpt.utils import num_tokens_from_object_or_list, num_tokens_from_string

logger = logging.getLogger(__name__)


def _serialize_for_token_count(value):
    """Normalize payloads into token-countable primitives."""
    if isinstance(value, str):
        # Avoid counting large binary payloads in data URLs as text tokens.
        if value.startswith("data:") and ";base64," in value:
            return ""
        return value

    if value is None:
        return ""

    # Raw binary payloads (image/file attachments arrive as ``bytes`` from
    # ``GoogleLLM.prepare_messages_with_attachments``) — without this
    # branch they fall through to ``str(value)`` below, which produces a
    # multi-megabyte ``"b'\\x89PNG...'"`` repr-string and inflates
    # ``prompt_tokens`` by orders of magnitude. Same intent as the
    # data-URL skip above.
    if isinstance(value, (bytes, bytearray, memoryview)):
        return ""

    if isinstance(value, list):
        return [_serialize_for_token_count(item) for item in value]

    if isinstance(value, dict):
        serialized = {}
        for key, raw in value.items():
            key_lower = str(key).lower()

            # Skip raw binary-like fields; keep textual tool-call fields.
            if key_lower in {"data", "base64", "image_data"} and isinstance(raw, str):
                continue
            if key_lower == "url" and isinstance(raw, str) and ";base64," in raw:
                continue

            serialized[key] = _serialize_for_token_count(raw)
        return serialized

    if hasattr(value, "model_dump") and callable(getattr(value, "model_dump")):
        return _serialize_for_token_count(value.model_dump())
    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        return _serialize_for_token_count(value.to_dict())
    if hasattr(value, "__dict__"):
        return _serialize_for_token_count(vars(value))

    return str(value)


def _count_tokens(value):
    serialized = _serialize_for_token_count(value)
    if isinstance(serialized, str):
        return num_tokens_from_string(serialized)
    return num_tokens_from_object_or_list(serialized)


def _count_prompt_tokens(messages, tools=None, usage_attachments=None, **kwargs):
    prompt_tokens = 0

    for message in messages or []:
        if not isinstance(message, dict):
            prompt_tokens += _count_tokens(message)
            continue

        prompt_tokens += _count_tokens(message.get("content"))

        # Include tool-related message fields for providers that use OpenAI-native format.
        prompt_tokens += _count_tokens(message.get("tool_calls"))
        prompt_tokens += _count_tokens(message.get("tool_call_id"))
        prompt_tokens += _count_tokens(message.get("function_call"))
        prompt_tokens += _count_tokens(message.get("function_response"))

    # Count tool schema payload passed to the model.
    prompt_tokens += _count_tokens(tools)

    # Count structured-output/schema payloads when provided.
    prompt_tokens += _count_tokens(kwargs.get("response_format"))
    prompt_tokens += _count_tokens(kwargs.get("response_schema"))

    # Optional usage-only attachment context (not forwarded to provider).
    prompt_tokens += _count_tokens(usage_attachments)

    return prompt_tokens


def _persist_call_usage(llm, call_usage, *, duration_ms=None, ttft_ms=None):
    """Write one ``token_usage`` row per LLM call. Always-on; no flag.

    Source defaults to ``agent_stream`` and can be overridden per
    instance via ``_token_usage_source`` (set on side-channel LLMs:
    title / compression / rag_condense / fallback). A ``_request_id``
    stamped on the LLM lets ``count_in_range`` deduplicate the multiple
    rows produced by a single multi-tool agent run.

    Args:
        llm: The LLM instance the call ran on.
        call_usage: The call's token counts.
        duration_ms: Wall-clock for the call, measured by the wrapper.
        ttft_ms: Time to the first streamed chunk; None for a non-streaming
            call and for a stream that failed before yielding anything.

    Returns:
        The call's priced cost in USD, or None when no row was written.
    """
    if call_usage["prompt_tokens"] == 0 and call_usage["generated_tokens"] == 0:
        return None
    decoded_token = getattr(llm, "decoded_token", None)
    user_id = (
        decoded_token.get("sub") if isinstance(decoded_token, dict) else None
    )
    user_api_key = getattr(llm, "user_api_key", None)
    agent_id = getattr(llm, "agent_id", None)
    if not user_id and not user_api_key:
        # Repository would raise on the attribution check — log instead
        # so operators see the gap rather than crashing the stream.
        logger.warning(
            "token_usage skip: no user_id/api_key on LLM instance",
            extra={
                "source": getattr(llm, "_token_usage_source", "agent_stream"),
            },
        )
        return None
    model_id = getattr(llm, "_canonical_model_id", None)
    # Bring-your-own models run on the user's own provider key: recorded, never priced.
    if getattr(llm, "_is_byom", False):
        cost = 0.0
    else:
        cost = _call_cost_usd(model_id, call_usage)
    try:
        with db_session() as conn:
            # ``timestamp`` is omitted so Postgres ``server_default
            # = func.now()`` populates a tz-aware UTC value; passing
            # naive ``datetime.now()`` would silently shift on
            # non-UTC servers.
            TokenUsageRepository(conn).insert(
                user_id=user_id,
                api_key=user_api_key,
                agent_id=str(agent_id) if agent_id else None,
                prompt_tokens=call_usage["prompt_tokens"],
                generated_tokens=call_usage["generated_tokens"],
                # Present only when the provider reported the breakdown;
                # persisted as NULL otherwise so "unknown" never reads as
                # "0% cache hits".
                cached_tokens=call_usage.get("cached_tokens"),
                cache_write_tokens=call_usage.get("cache_write_tokens"),
                cost=cost,
                source=(
                    getattr(llm, "_token_usage_source", None) or "agent_stream"
                ),
                request_id=getattr(llm, "_request_id", None),
                model_id=model_id,
                duration_ms=duration_ms,
                ttft_ms=ttft_ms,
            )
    except Exception:
        logger.exception("token_usage persist failed")
    return cost


def _call_cost_usd(model_id, call_usage) -> float:
    """Price one call; a pricing failure records $0 rather than dropping the row."""
    try:
        return compute_cost_usd(
            model_id,
            call_usage["prompt_tokens"],
            call_usage["generated_tokens"],
            cached_tokens=call_usage.get("cached_tokens"),
            cache_write_tokens=call_usage.get("cache_write_tokens"),
        )
    except Exception:
        logger.exception("token_usage cost computation failed")
        return 0.0


def _prefer_provider_usage(llm: Any, call_usage: Dict[str, int]) -> Dict[str, int]:
    """Replace estimates with upstream counts when a provider reported them.

    Invariant: provider totals are billing-parity bins. Upstream
    ``prompt_tokens`` already includes cached-read tokens and
    ``completion_tokens`` already includes reasoning/refusal tokens, so
    they map 1:1 onto our two columns. Never subtract the
    ``*_tokens_details`` breakdowns (``cached_tokens``,
    ``reasoning_tokens``) back out of these bins — that would break
    parity with what providers bill.

    The prompt-cache sub-bins ARE carried alongside (``cached_tokens``,
    ``cache_write_tokens``; Anthropic's ``cache_creation_tokens`` maps to
    the latter) so persistence and the finish events can chart them. They
    are added only when the provider reported them. The rest of
    ``call_usage`` (e.g. ``model``) is preserved rather than replaced.
    """
    reported = getattr(llm, "_last_usage", None)
    if not isinstance(reported, dict):
        return call_usage
    # ``_last_usage`` is shared instance state overwritten by every call on
    # this LLM. Each reported usage may be billed to exactly ONE call: the
    # provider clears ``_last_usage_claimed`` when it records fresh usage,
    # and the first decorator ``finally`` to read it claims it. Without
    # this, a generator finalized late (abandoned round, GC) would adopt a
    # *different* call's provider counts. ``_last_usage`` itself is left in
    # place for read-only consumers (client-facing usage metadata).
    if getattr(llm, "_last_usage_claimed", False):
        return call_usage
    prompt = reported.get("prompt_tokens")
    completion = reported.get("completion_tokens")
    if prompt is None or completion is None:
        return call_usage
    try:
        llm._last_usage_claimed = True
    except AttributeError:
        # Slotted/immutable LLM stand-ins can't record the claim; this
        # call still gets the provider counts, which is correct for them.
        pass
    merged = {
        **call_usage,
        "prompt_tokens": int(prompt or 0),
        "generated_tokens": int(completion or 0),
    }
    details = reported.get("prompt_tokens_details")
    if isinstance(details, dict):
        cached = details.get("cached_tokens")
        written = details.get("cache_write_tokens")
        if written is None:
            written = details.get("cache_creation_tokens")
        if cached is not None:
            merged["cached_tokens"] = int(cached or 0)
        if written is not None:
            merged["cache_write_tokens"] = int(written or 0)
    return merged


def gen_token_usage(func):
    """Accumulate per-call token counts and write a ``token_usage`` row.

    The accumulator on ``self.token_usage`` stays in place for code
    paths that introspect it (e.g., logging, response payloads). DB
    persistence happens here for every call so primary streams,
    side-channel LLMs, and no-save flows all produce rows uniformly.

    Mirrors ``stream_token_usage``: persistence and the
    ``llm_gen_finished`` log fire from a ``finally`` block, so a failed
    call still records the prompt tokens it consumed and emits a
    ``status="error"`` finish event.
    """
    def wrapper(self, model, messages, stream, tools, **kwargs):
        usage_attachments = kwargs.pop("_usage_attachments", None)
        call_usage = {"prompt_tokens": 0, "generated_tokens": 0}
        call_usage["prompt_tokens"] += _count_prompt_tokens(
            messages,
            tools=tools,
            usage_attachments=usage_attachments,
            **kwargs,
        )
        span = start_llm_span(self, model, stream=False, tools=tools)
        started_at = time.monotonic()
        error: BaseException | None = None
        result = None
        try:
            result = func(self, model, messages, stream, tools, **kwargs)
            call_usage["generated_tokens"] += _count_tokens(result)
            return result
        except Exception as exc:
            error = exc
            raise
        finally:
            duration_ms = int((time.monotonic() - started_at) * 1000)
            estimated_usage = call_usage
            call_usage = _prefer_provider_usage(self, call_usage)
            self.token_usage["prompt_tokens"] += call_usage["prompt_tokens"]
            self.token_usage["generated_tokens"] += call_usage["generated_tokens"]
            # A non-streaming call has no first-token moment; ttft stays NULL.
            cost = _persist_call_usage(self, call_usage, duration_ms=duration_ms)
            finish_llm_call(
                span,
                self,
                model,
                call_usage,
                duration_ms=duration_ms,
                error=error,
                cost_usd=cost,
                estimated=call_usage is estimated_usage,
                output=result if isinstance(result, str) else None,
            )
            emit = getattr(self, "_emit_gen_finished_log", None)
            if callable(emit):
                try:
                    emit(
                        model,
                        prompt_tokens=call_usage["prompt_tokens"],
                        completion_tokens=call_usage["generated_tokens"],
                        latency_ms=duration_ms,
                        cached_tokens=call_usage.get("cached_tokens"),
                        cache_write_tokens=call_usage.get("cache_write_tokens"),
                        error=error,
                    )
                except Exception:
                    logger.exception("Failed to emit llm_gen_finished")

    return wrapper


def stream_token_usage(func):
    """Stream variant of ``gen_token_usage``. Same persistence contract."""
    def wrapper(self, model, messages, stream, tools, **kwargs):
        usage_attachments = kwargs.pop("_usage_attachments", None)
        call_usage = {"prompt_tokens": 0, "generated_tokens": 0}
        call_usage["prompt_tokens"] += _count_prompt_tokens(
            messages,
            tools=tools,
            usage_attachments=usage_attachments,
            **kwargs,
        )
        batch = []
        started_at = time.monotonic()
        first_chunk_at: float | None = None
        # Time spent waiting on the provider, accumulated across ``next()``
        # calls. The wall clock cannot be used here: this is a generator, so
        # every ``yield`` suspends until the consumer comes back, and the span
        # from start to exhaustion includes the agent loop's tool handling and
        # the SSE client's backpressure. A slow browser would otherwise record
        # 30s for a 900ms call, and latency_summary would mix that with true
        # non-streaming durations under one p50.
        provider_seconds = 0.0
        error: BaseException | None = None
        completed = False
        # This body runs on the first ``next()``, not at ``gen_stream()``
        # time, so the span starts when the provider call really does.
        span = start_llm_span(self, model, stream=True, tools=tools)
        try:
            result = func(self, model, messages, stream, tools, **kwargs)
            stream_iter = iter(result)
            while True:
                pull_started = time.monotonic()
                try:
                    r = next(stream_iter)
                except StopIteration:
                    provider_seconds += time.monotonic() - pull_started
                    completed = True
                    break
                provider_seconds += time.monotonic() - pull_started
                if first_chunk_at is None:
                    first_chunk_at = pull_started + provider_seconds
                batch.append(r)
                yield r
        except Exception as exc:
            # ``GeneratorExit`` (consumer disconnected) and KeyboardInterrupt
            # flow through as ``status="ok"`` — same convention as
            # ``docsgpt.logging._consume_and_log``.
            error = exc
            raise
        finally:
            duration_ms = int(provider_seconds * 1000)
            # NULL, not 0, when the stream failed before yielding: "no first
            # token" must not read as an instant one in a p50.
            ttft_ms = (
                int((first_chunk_at - started_at) * 1000)
                if first_chunk_at is not None
                else None
            )
            for line in batch:
                call_usage["generated_tokens"] += _count_tokens(line)
            estimated_usage = call_usage
            call_usage = _prefer_provider_usage(self, call_usage)
            self.token_usage["prompt_tokens"] += call_usage["prompt_tokens"]
            self.token_usage["generated_tokens"] += call_usage["generated_tokens"]
            cost = _persist_call_usage(
                self, call_usage, duration_ms=duration_ms, ttft_ms=ttft_ms
            )
            finish_llm_call(
                span,
                self,
                model,
                call_usage,
                duration_ms=duration_ms,
                error=error,
                completed=completed,
                ttft_ms=ttft_ms,
                cost_usd=cost,
                estimated=call_usage is estimated_usage,
                output=batch,
            )
            emit = getattr(self, "_emit_stream_finished_log", None)
            if callable(emit):
                try:
                    emit(
                        model,
                        prompt_tokens=call_usage["prompt_tokens"],
                        completion_tokens=call_usage["generated_tokens"],
                        # The log line has always meant end-to-end wall clock
                        # for the streamed response; only the persisted column
                        # isolates provider time.
                        latency_ms=int((time.monotonic() - started_at) * 1000),
                        cached_tokens=call_usage.get("cached_tokens"),
                        cache_write_tokens=call_usage.get("cache_write_tokens"),
                        error=error,
                    )
                except Exception:
                    logger.exception("Failed to emit llm_stream_finished")

    return wrapper
