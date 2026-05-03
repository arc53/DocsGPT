import logging
import time
from datetime import datetime

from application.storage.db.repositories.token_usage import TokenUsageRepository
from application.storage.db.session import db_session
from application.utils import num_tokens_from_object_or_list, num_tokens_from_string

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


def _persist_call_usage(llm, call_usage):
    """Write one ``token_usage`` row per LLM call. Always-on; no flag.

    Source defaults to ``agent_stream`` and can be overridden per
    instance via ``_token_usage_source`` (set on side-channel LLMs:
    title / compression / rag_condense / fallback). A ``_request_id``
    stamped on the LLM lets ``count_in_range`` deduplicate the multiple
    rows produced by a single multi-tool agent run.
    """
    if call_usage["prompt_tokens"] == 0 and call_usage["generated_tokens"] == 0:
        return
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
        return
    try:
        with db_session() as conn:
            TokenUsageRepository(conn).insert(
                user_id=user_id,
                api_key=user_api_key,
                agent_id=str(agent_id) if agent_id else None,
                prompt_tokens=call_usage["prompt_tokens"],
                generated_tokens=call_usage["generated_tokens"],
                source=(
                    getattr(llm, "_token_usage_source", None) or "agent_stream"
                ),
                request_id=getattr(llm, "_request_id", None),
                timestamp=datetime.now(),
            )
    except Exception:
        logger.exception("token_usage persist failed")


def gen_token_usage(func):
    """Accumulate per-call token counts and write a ``token_usage`` row.

    The accumulator on ``self.token_usage`` stays in place for code
    paths that introspect it (e.g., logging, response payloads). DB
    persistence happens here for every call so primary streams,
    side-channel LLMs, and no-save flows all produce rows uniformly.
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
        result = func(self, model, messages, stream, tools, **kwargs)
        call_usage["generated_tokens"] += _count_tokens(result)
        self.token_usage["prompt_tokens"] += call_usage["prompt_tokens"]
        self.token_usage["generated_tokens"] += call_usage["generated_tokens"]
        _persist_call_usage(self, call_usage)
        return result

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
        error: BaseException | None = None
        try:
            result = func(self, model, messages, stream, tools, **kwargs)
            for r in result:
                batch.append(r)
                yield r
        except Exception as exc:
            # ``GeneratorExit`` (consumer disconnected) and KeyboardInterrupt
            # flow through as ``status="ok"`` — same convention as
            # ``application.logging._consume_and_log``.
            error = exc
            raise
        finally:
            for line in batch:
                call_usage["generated_tokens"] += _count_tokens(line)
            self.token_usage["prompt_tokens"] += call_usage["prompt_tokens"]
            self.token_usage["generated_tokens"] += call_usage["generated_tokens"]
            _persist_call_usage(self, call_usage)
            emit = getattr(self, "_emit_stream_finished_log", None)
            if callable(emit):
                try:
                    emit(
                        model,
                        prompt_tokens=call_usage["prompt_tokens"],
                        completion_tokens=call_usage["generated_tokens"],
                        latency_ms=int((time.monotonic() - started_at) * 1000),
                        error=error,
                    )
                except Exception:
                    logger.exception("Failed to emit llm_stream_finished")

    return wrapper
