import json
from unittest.mock import MagicMock, patch

import pytest
from application.cache import (
    gen_cache,
    gen_cache_key,
    get_redis_instance,
    stream_cache,
)
from application.utils import get_hash


@pytest.mark.unit
def test_make_gen_cache_key():
    messages = [
        {"role": "user", "content": "test_user_message"},
        {"role": "system", "content": "test_system_message"},
    ]
    model = "test_docgpt"
    tools = None

    messages_str = json.dumps(messages)
    tools_str = json.dumps(tools) if tools else ""
    expected_combined = f"{model}_{messages_str}_{tools_str}"
    expected_hash = get_hash(expected_combined)
    cache_key = gen_cache_key(messages, model=model, tools=None)

    assert cache_key == expected_hash


@pytest.mark.unit
def test_gen_cache_key_invalid_message_format():
    with pytest.raises(ValueError, match="All messages must be dictionaries."):
        gen_cache_key("This is not a list", model="docgpt", tools=None)


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_gen_cache_hit(mock_make_redis):
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.return_value = b"cached_result"

    @gen_cache
    def mock_function(self, model, messages, stream, tools):
        return "new_result"

    messages = [{"role": "user", "content": "test_user_message"}]
    model = "test_docgpt"

    result = mock_function(None, model, messages, stream=False, tools=None)

    assert result == "cached_result"
    mock_redis_instance.get.assert_called_once()
    mock_redis_instance.set.assert_not_called()


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_gen_cache_miss(mock_make_redis):
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.return_value = None

    @gen_cache
    def mock_function(self, model, messages, steam, tools):
        return "new_result"

    messages = [
        {"role": "user", "content": "test_user_message"},
        {"role": "system", "content": "test_system_message"},
    ]
    model = "test_docgpt"

    result = mock_function(None, model, messages, stream=False, tools=None)

    assert result == "new_result"
    mock_redis_instance.get.assert_called_once()


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_stream_cache_hit(mock_make_redis):
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance

    cached_chunk = json.dumps(["chunk1", "chunk2"]).encode("utf-8")
    mock_redis_instance.get.return_value = cached_chunk

    @stream_cache
    def mock_function(self, model, messages, stream, tools):
        yield "new_chunk"

    messages = [{"role": "user", "content": "test_user_message"}]
    model = "test_docgpt"

    result = list(mock_function(None, model, messages, stream=True, tools=None))

    assert result == ["chunk1", "chunk2"]
    mock_redis_instance.get.assert_called_once()
    mock_redis_instance.set.assert_not_called()


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_stream_cache_miss(mock_make_redis):
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.return_value = None

    @stream_cache
    def mock_function(self, model, messages, stream, tools):
        yield "new_chunk"

    messages = [
        {"role": "user", "content": "This is the context"},
        {"role": "system", "content": "Some other message"},
        {"role": "user", "content": "What is the answer?"},
    ]
    model = "test_docgpt"

    result = list(mock_function(None, model, messages, stream=True, tools=None))

    assert result == ["new_chunk"]
    mock_redis_instance.get.assert_called_once()
    mock_redis_instance.set.assert_called_once()


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_stream_cache_preserves_json_chunk_types(mock_make_redis):
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.return_value = json.dumps({
        "version": 1,
        "chunks": ["text", {"type": "thought", "thought": "reasoning"}],
    }).encode("utf-8")

    @stream_cache
    def mock_function(self, model, messages, stream, tools):
        yield "new_chunk"

    result = list(mock_function(
        None,
        "model",
        [{"role": "user", "content": "test"}],
        stream=True,
        tools=None,
    ))

    assert result == ["text", {"type": "thought", "thought": "reasoning"}]
    mock_redis_instance.set.assert_not_called()


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_stream_cache_does_not_stringify_protocol_objects(mock_make_redis):
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.return_value = None
    terminal_chunk = MagicMock(name="responses_terminal_choice")

    @stream_cache
    def mock_function(self, model, messages, stream, tools):
        yield "partial"
        yield terminal_chunk

    result = list(mock_function(
        None,
        "model",
        [{"role": "user", "content": "test"}],
        stream=True,
        tools=None,
    ))

    assert result[0] == "partial"
    assert result[1] is terminal_chunk
    mock_redis_instance.set.assert_not_called()


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_stream_cache_rejects_legacy_protocol_object_repr(mock_make_redis):
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.return_value = json.dumps([
        "partial",
        "<application.llm.openai._RespChoice object at 0x123>",
    ]).encode("utf-8")

    @stream_cache
    def mock_function(self, model, messages, stream, tools):
        yield "fresh"

    result = list(mock_function(
        None,
        "model",
        [{"role": "user", "content": "test"}],
        stream=True,
        tools=None,
    ))

    assert result == ["fresh"]
    mock_redis_instance.delete.assert_called_once()


# ── get_redis_instance ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestGetRedisInstance:

    def setup_method(self):
        """Reset module-level redis state between tests."""
        import application.cache as cache_mod

        cache_mod._redis_instance = None
        cache_mod._redis_creation_failed = False

    def teardown_method(self):
        import application.cache as cache_mod

        cache_mod._redis_instance = None
        cache_mod._redis_creation_failed = False

    @patch("application.cache.redis.Redis.from_url")
    @patch("application.cache.settings")
    def test_creates_redis_instance(self, mock_settings, mock_from_url):
        mock_settings.CACHE_REDIS_URL = "redis://localhost:6379/0"
        mock_instance = MagicMock()
        mock_from_url.return_value = mock_instance

        result = get_redis_instance()

        assert result is mock_instance
        mock_from_url.assert_called_once_with(
            "redis://localhost:6379/0",
            socket_connect_timeout=2,
            health_check_interval=10,
        )

    @patch("application.cache.redis.Redis.from_url")
    @patch("application.cache.settings")
    def test_returns_cached_instance(self, mock_settings, mock_from_url):
        mock_settings.CACHE_REDIS_URL = "redis://localhost:6379/0"
        mock_instance = MagicMock()
        mock_from_url.return_value = mock_instance

        result1 = get_redis_instance()
        result2 = get_redis_instance()

        assert result1 is result2
        assert mock_from_url.call_count == 1

    @patch("application.cache.redis.Redis.from_url")
    @patch("application.cache.settings")
    def test_value_error_stops_retries(self, mock_settings, mock_from_url):
        import application.cache as cache_mod

        mock_settings.CACHE_REDIS_URL = "invalid://url"
        mock_from_url.side_effect = ValueError("Invalid Redis URL")

        result = get_redis_instance()

        assert result is None
        assert cache_mod._redis_creation_failed is True

        # Subsequent calls should not retry
        mock_from_url.reset_mock()
        result2 = get_redis_instance()
        assert result2 is None
        mock_from_url.assert_not_called()

    @patch("application.cache.redis.Redis.from_url")
    @patch("application.cache.settings")
    def test_connection_error_allows_retries(self, mock_settings, mock_from_url):
        import application.cache as cache_mod
        import redis as redis_mod

        mock_settings.CACHE_REDIS_URL = "redis://unreachable:6379/0"
        mock_from_url.side_effect = redis_mod.ConnectionError("Connection refused")

        result = get_redis_instance()

        assert result is None
        assert cache_mod._redis_creation_failed is False

        # Subsequent calls should retry
        mock_from_url.side_effect = None
        mock_from_url.return_value = MagicMock()
        result2 = get_redis_instance()
        assert result2 is not None


# ── gen_cache_key edge cases ────────────────────────────────────────────────


@pytest.mark.unit
def test_gen_cache_key_with_tools():
    messages = [{"role": "user", "content": "test"}]
    tools = [{"type": "function", "function": {"name": "test"}}]

    key = gen_cache_key(messages, model="docgpt", tools=tools)
    assert isinstance(key, str)
    assert len(key) == 32


@pytest.mark.unit
def test_gen_cache_key_default_model():
    messages = [{"role": "user", "content": "test"}]
    key = gen_cache_key(messages)
    assert isinstance(key, str)
    assert len(key) == 32


@pytest.mark.unit
def test_gen_cache_key_deterministic():
    messages = [{"role": "user", "content": "test"}]
    key1 = gen_cache_key(messages, model="m1")
    key2 = gen_cache_key(messages, model="m1")
    assert key1 == key2


@pytest.mark.unit
def test_gen_cache_key_different_models():
    messages = [{"role": "user", "content": "test"}]
    key1 = gen_cache_key(messages, model="m1")
    key2 = gen_cache_key(messages, model="m2")
    assert key1 != key2


# ── gen_cache with tools bypass ─────────────────────────────────────────────


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_gen_cache_bypasses_when_tools_provided(mock_make_redis):
    """When tools are provided, caching is bypassed."""
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance

    @gen_cache
    def mock_function(self, model, messages, stream, tools):
        return "direct_result"

    messages = [{"role": "user", "content": "test"}]
    tools = [{"type": "function"}]
    result = mock_function(None, "model", messages, stream=False, tools=tools)

    assert result == "direct_result"
    mock_redis_instance.get.assert_not_called()


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_gen_cache_no_redis(mock_make_redis):
    """When redis is unavailable, function runs without caching."""
    mock_make_redis.return_value = None

    @gen_cache
    def mock_function(self, model, messages, stream, tools):
        return "no_cache_result"

    messages = [{"role": "user", "content": "test"}]
    result = mock_function(None, "model", messages, stream=False, tools=None)

    assert result == "no_cache_result"


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_gen_cache_redis_get_error(mock_make_redis):
    """When redis.get raises, function falls through gracefully."""
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.side_effect = Exception("Redis error")

    @gen_cache
    def mock_function(self, model, messages, stream, tools):
        return "fallback_result"

    messages = [{"role": "user", "content": "test"}]
    result = mock_function(None, "model", messages, stream=False, tools=None)

    assert result == "fallback_result"


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_gen_cache_redis_set_error(mock_make_redis):
    """When redis.set raises, the result is still returned."""
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.return_value = None
    mock_redis_instance.set.side_effect = Exception("Redis write error")

    @gen_cache
    def mock_function(self, model, messages, stream, tools):
        return "result_str"

    messages = [{"role": "user", "content": "test"}]
    result = mock_function(None, "model", messages, stream=False, tools=None)

    assert result == "result_str"


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_gen_cache_non_string_result_not_cached(mock_make_redis):
    """Non-string results should not be cached."""
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.return_value = None

    @gen_cache
    def mock_function(self, model, messages, stream, tools):
        return {"key": "value"}  # not a string

    messages = [{"role": "user", "content": "test"}]
    result = mock_function(None, "model", messages, stream=False, tools=None)

    assert result == {"key": "value"}
    mock_redis_instance.set.assert_not_called()


# ── stream_cache edge cases ─────────────────────────────────────────────────


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_stream_cache_bypasses_when_tools_provided(mock_make_redis):
    """When tools are provided, streaming cache is bypassed."""
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance

    @stream_cache
    def mock_function(self, model, messages, stream, tools):
        yield "direct_chunk"

    messages = [{"role": "user", "content": "test"}]
    tools = [{"type": "function"}]
    result = list(mock_function(None, "model", messages, stream=True, tools=tools))

    assert result == ["direct_chunk"]
    mock_redis_instance.get.assert_not_called()


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_stream_cache_skips_write_when_no_content_deltas(mock_make_redis):
    """A stream that emits only reasoning ("thought") dicts and a
    finish chunk — i.e. reasoning-only-stop, the silent-loss bug's
    signature — must NOT be cached. Otherwise the empty stream is
    replayed for the TTL on every identical request, poisoning the
    cache and denying the reasoning-only recovery any chance to hit
    a fresh provider call.
    """
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.return_value = None

    @stream_cache
    def mock_function(self, model, messages, stream, tools):
        yield {"type": "thought", "thought": "thinking hard"}
        yield {"type": "thought", "thought": " and harder"}
        yield {"type": "stop"}

    messages = [{"role": "user", "content": "test"}]
    result = list(mock_function(None, "model", messages, stream=True, tools=None))

    assert len(result) == 3
    mock_redis_instance.set.assert_not_called()


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_stream_cache_writes_when_any_content_chunk_seen(mock_make_redis):
    """The mirror case: a stream with even one str content delta is
    cached normally (the poison guard is minimal — only reasoning-only
    streams are dropped)."""
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.return_value = None

    @stream_cache
    def mock_function(self, model, messages, stream, tools):
        yield {"type": "thought", "thought": "brief thought"}
        yield "the answer"

    messages = [{"role": "user", "content": "test"}]
    result = list(mock_function(None, "model", messages, stream=True, tools=None))

    assert result == [{"type": "thought", "thought": "brief thought"}, "the answer"]
    mock_redis_instance.set.assert_called_once()


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_stream_cache_no_redis(mock_make_redis):
    """When redis is unavailable, streaming works without caching."""
    mock_make_redis.return_value = None

    @stream_cache
    def mock_function(self, model, messages, stream, tools):
        yield "chunk1"
        yield "chunk2"

    messages = [{"role": "user", "content": "test"}]
    result = list(mock_function(None, "model", messages, stream=True, tools=None))

    assert result == ["chunk1", "chunk2"]


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_stream_cache_redis_get_error(mock_make_redis):
    """When redis.get raises during stream, falls through gracefully."""
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.side_effect = Exception("Redis error")

    @stream_cache
    def mock_function(self, model, messages, stream, tools):
        yield "fallback_chunk"

    messages = [{"role": "user", "content": "test"}]
    result = list(mock_function(None, "model", messages, stream=True, tools=None))

    assert result == ["fallback_chunk"]


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_stream_cache_redis_set_error(mock_make_redis):
    """When redis.set raises during stream save, chunks are still yielded."""
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.return_value = None
    mock_redis_instance.set.side_effect = Exception("Redis write error")

    @stream_cache
    def mock_function(self, model, messages, stream, tools):
        yield "chunk"

    messages = [{"role": "user", "content": "test"}]
    result = list(mock_function(None, "model", messages, stream=True, tools=None))

    assert result == ["chunk"]


# =====================================================================
# Coverage gap tests  (lines 86-89)
# =====================================================================


@patch("application.cache.get_redis_instance")
def test_stream_cache_key_generation_failure_yields(mock_make_redis):
    """Cover lines 86-89: ValueError in gen_cache_key falls through to func."""
    mock_make_redis.return_value = None

    @stream_cache
    def mock_function(self, model, messages, stream, tools):
        yield "fallback_chunk"

    # Pass invalid messages (not dicts) to trigger ValueError in gen_cache_key
    messages = ["not_a_dict"]
    result = list(mock_function(None, "model", messages, stream=True, tools=None))
    assert result == ["fallback_chunk"]


# =====================================================================
# gen_cache_key with inline bytes (Google attachments)
# =====================================================================


@pytest.mark.unit
def test_gen_cache_key_handles_inline_bytes():
    """Image attachments arrive in messages as raw bytes (see
    GoogleLLM.prepare_messages_with_attachments). gen_cache_key must not
    crash on json.dumps of bytes."""
    msgs = [
        {
            "role": "user",
            "content": [{"file_bytes": b"\x00\x01\x02", "mime_type": "image/png"}],
        }
    ]
    key = gen_cache_key(msgs, model="x")
    assert isinstance(key, str)
    assert len(key) == 32


@pytest.mark.unit
def test_gen_cache_key_stable_for_same_bytes():
    """Two requests with identical image bytes must produce the same key
    — otherwise we'd never get cache hits on image-bearing prompts."""
    a = [
        {
            "role": "user",
            "content": [{"file_bytes": b"abc", "mime_type": "image/png"}],
        }
    ]
    b = [
        {
            "role": "user",
            "content": [{"file_bytes": b"abc", "mime_type": "image/png"}],
        }
    ]
    assert gen_cache_key(a, "m") == gen_cache_key(b, "m")


@pytest.mark.unit
def test_gen_cache_key_differs_for_different_bytes():
    """Different image bytes must produce different keys — otherwise two
    different images would collide in cache."""
    a = [
        {
            "role": "user",
            "content": [{"file_bytes": b"abc", "mime_type": "image/png"}],
        }
    ]
    b = [
        {
            "role": "user",
            "content": [{"file_bytes": b"xyz", "mime_type": "image/png"}],
        }
    ]
    assert gen_cache_key(a, "m") != gen_cache_key(b, "m")


@pytest.mark.unit
def test_gen_cache_key_handles_bytearray_and_memoryview():
    """The default helper covers all bytes-like types so refactors that
    swap bytes for bytearray/memoryview don't silently re-introduce the
    TypeError."""
    msgs_ba = [
        {
            "role": "user",
            "content": [
                {"file_bytes": bytearray(b"abc"), "mime_type": "image/png"}
            ],
        }
    ]
    msgs_mv = [
        {
            "role": "user",
            "content": [
                {"file_bytes": memoryview(b"abc"), "mime_type": "image/png"}
            ],
        }
    ]
    msgs_b = [
        {
            "role": "user",
            "content": [{"file_bytes": b"abc", "mime_type": "image/png"}],
        }
    ]
    # All three should hash the same content to the same key.
    assert gen_cache_key(msgs_ba, "m") == gen_cache_key(msgs_b, "m")
    assert gen_cache_key(msgs_mv, "m") == gen_cache_key(msgs_b, "m")


# =====================================================================
# Generation kwargs are part of the cache key
#
# The decorators wrap ``_raw_gen``/``_raw_gen_stream``, whose extra kwargs
# carry ``response_format`` (OpenAI structured output) and
# ``response_schema`` (Google). Before these were hashed, changing a
# workflow node's JSON schema replayed the previous schema's answer for
# the whole 30-minute TTL.
# =====================================================================


class _FakeRedis:
    """Dict-backed stand-in for the redis client used by the decorators."""

    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value.encode("utf-8") if isinstance(value, str) else value

    def delete(self, key):
        self.store.pop(key, None)


_SCHEMA_A = {
    "type": "json_schema",
    "json_schema": {"name": "r", "schema": {"properties": {"a": {"type": "string"}}}},
}
_SCHEMA_B = {
    "type": "json_schema",
    "json_schema": {"name": "r", "schema": {"properties": {"b": {"type": "number"}}}},
}


@pytest.mark.unit
def test_gen_cache_key_differs_for_different_response_format():
    messages = [{"role": "user", "content": "test"}]
    key_a = gen_cache_key(messages, "m", None, extra={"response_format": _SCHEMA_A})
    key_b = gen_cache_key(messages, "m", None, extra={"response_format": _SCHEMA_B})
    assert key_a != key_b


@pytest.mark.unit
def test_gen_cache_key_stable_for_same_response_format():
    messages = [{"role": "user", "content": "test"}]
    key_a = gen_cache_key(messages, "m", None, extra={"response_format": _SCHEMA_A})
    key_b = gen_cache_key(messages, "m", None, extra={"response_format": dict(_SCHEMA_A)})
    assert key_a == key_b


@pytest.mark.unit
def test_gen_cache_key_response_format_differs_from_no_format():
    messages = [{"role": "user", "content": "test"}]
    assert gen_cache_key(messages, "m") != gen_cache_key(
        messages, "m", None, extra={"response_format": _SCHEMA_A}
    )


@pytest.mark.unit
def test_gen_cache_key_differs_for_different_response_schema():
    """Google's structured-output kwarg is keyed just like OpenAI's."""
    messages = [{"role": "user", "content": "test"}]
    key_a = gen_cache_key(messages, "m", None, extra={"response_schema": _SCHEMA_A})
    key_b = gen_cache_key(messages, "m", None, extra={"response_schema": _SCHEMA_B})
    assert key_a != key_b


@pytest.mark.unit
def test_gen_cache_key_covers_other_generation_kwargs():
    messages = [{"role": "user", "content": "test"}]
    assert gen_cache_key(
        messages, "m", None, extra={"temperature": 0.1}
    ) != gen_cache_key(messages, "m", None, extra={"temperature": 0.9})
    assert gen_cache_key(
        messages, "m", None, extra={"reasoning_effort": "low"}
    ) != gen_cache_key(messages, "m", None, extra={"reasoning_effort": "high"})


@pytest.mark.unit
def test_gen_cache_key_ignores_usage_attachments():
    """``_usage_attachments`` is a token-accounting side channel that never
    reaches the provider — and the gen/stream decorator stacks disagree on
    whether it is still in kwargs — so it must not move the key."""
    messages = [{"role": "user", "content": "test"}]
    plain = gen_cache_key(messages, "m")
    with_attachments = gen_cache_key(
        messages, "m", None, extra={"_usage_attachments": [{"id": "att1"}]}
    )
    assert plain == with_attachments


@pytest.mark.unit
def test_gen_cache_key_ignores_none_valued_kwargs():
    """``response_format=None`` is the default, not a distinct request."""
    messages = [{"role": "user", "content": "test"}]
    assert gen_cache_key(messages, "m") == gen_cache_key(
        messages, "m", None, extra={"response_format": None, "response_schema": None}
    )


@pytest.mark.unit
def test_gen_cache_key_extra_ordering_is_irrelevant():
    messages = [{"role": "user", "content": "test"}]
    first = gen_cache_key(messages, "m", None, extra={"a": 1, "b": 2})
    second = gen_cache_key(messages, "m", None, extra={"b": 2, "a": 1})
    assert first == second


@pytest.mark.unit
def test_gen_cache_key_unserializable_extra_raises_value_error():
    """A key we cannot compute must raise so the decorators bypass the
    cache rather than reuse a wrong entry."""
    messages = [{"role": "user", "content": "test"}]
    circular = {}
    circular["self"] = circular
    with pytest.raises(ValueError):
        gen_cache_key(messages, "m", None, extra={"response_format": circular})


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_gen_cache_does_not_serve_entry_from_other_response_format(mock_make_redis):
    fake = _FakeRedis()
    mock_make_redis.return_value = fake
    calls = []

    @gen_cache
    def mock_function(self, model, messages, stream, tools, **kwargs):
        calls.append(kwargs.get("response_format"))
        return f"answer-{len(calls)}"

    messages = [{"role": "user", "content": "test"}]
    first = mock_function(
        None, "m", messages, stream=False, tools=None, response_format=_SCHEMA_A
    )
    second = mock_function(
        None, "m", messages, stream=False, tools=None, response_format=_SCHEMA_B
    )
    cached = mock_function(
        None, "m", messages, stream=False, tools=None, response_format=_SCHEMA_A
    )

    assert first == "answer-1"
    assert second == "answer-2"
    assert cached == "answer-1"
    assert calls == [_SCHEMA_A, _SCHEMA_B]


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_stream_cache_does_not_replay_entry_from_other_response_format(mock_make_redis):
    """The reported bug: a workflow node whose schema changed replayed the
    old schema's cached stream for the rest of the TTL."""
    fake = _FakeRedis()
    mock_make_redis.return_value = fake
    calls = []

    @stream_cache
    def mock_function(self, model, messages, stream, tools, **kwargs):
        calls.append(kwargs.get("response_format"))
        yield f"chunk-{len(calls)}"

    messages = [{"role": "user", "content": "test"}]
    first = list(
        mock_function(
            None, "m", messages, stream=True, tools=None, response_format=_SCHEMA_A
        )
    )
    second = list(
        mock_function(
            None, "m", messages, stream=True, tools=None, response_format=_SCHEMA_B
        )
    )
    replay = list(
        mock_function(
            None, "m", messages, stream=True, tools=None, response_format=_SCHEMA_A
        )
    )

    assert first == ["chunk-1"]
    assert second == ["chunk-2"]
    assert replay == ["chunk-1"]
    assert calls == [_SCHEMA_A, _SCHEMA_B]


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_gen_cache_bypassed_for_previous_response_id(mock_make_redis):
    """A Responses API turn chained to a server-held id depends on state no
    key can capture, so it must not read or write the cache."""
    fake = MagicMock()
    mock_make_redis.return_value = fake

    @gen_cache
    def mock_function(self, model, messages, stream, tools, **kwargs):
        return "fresh"

    messages = [{"role": "user", "content": "test"}]
    result = mock_function(
        None, "m", messages, stream=False, tools=None, previous_response_id="resp_1"
    )

    assert result == "fresh"
    fake.get.assert_not_called()
    fake.set.assert_not_called()


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_stream_cache_bypassed_for_previous_response_id(mock_make_redis):
    fake = MagicMock()
    mock_make_redis.return_value = fake

    @stream_cache
    def mock_function(self, model, messages, stream, tools, **kwargs):
        yield "fresh"

    messages = [{"role": "user", "content": "test"}]
    result = list(
        mock_function(
            None, "m", messages, stream=True, tools=None, previous_response_id="resp_1"
        )
    )

    assert result == ["fresh"]
    fake.get.assert_not_called()
    fake.set.assert_not_called()


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_gen_cache_ignores_stream_payload_stored_under_same_key(mock_make_redis):
    """Belt-and-braces: even planted directly under the gen key, a stream
    envelope must never be handed back as a non-streaming answer."""
    fake = _FakeRedis()
    mock_make_redis.return_value = fake
    messages = [{"role": "user", "content": "test"}]
    key = f"gen:{gen_cache_key(messages, 'm', None)}"
    fake.set(key, json.dumps({"version": 1, "chunks": ["a", "b"]}))

    @gen_cache
    def mock_function(self, model, messages, stream, tools, **kwargs):
        return "real answer"

    result = mock_function(None, "m", messages, stream=False, tools=None)
    assert result == "real answer"


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_gen_and_stream_caches_do_not_share_a_key_space(mock_make_redis):
    """A gen write must not overwrite the stream envelope for the same call.

    Both wrappers hash the same (messages, model, kwargs) tuple, so before the
    namespacing they collided: the gen write replaced the envelope with a bare
    string and the next stream read failed to decode it.
    """
    fake = _FakeRedis()
    mock_make_redis.return_value = fake
    messages = [{"role": "user", "content": "test"}]

    @stream_cache
    def streamer(self, model, messages, stream, tools, **kwargs):
        yield "alpha"
        yield "beta"

    @gen_cache
    def generator(self, model, messages, stream, tools, **kwargs):
        return "a plain answer"

    assert list(streamer(None, "m", messages, stream=True, tools=None)) == [
        "alpha", "beta",
    ]
    assert generator(None, "m", messages, stream=False, tools=None) == "a plain answer"

    upstream_calls = []

    @stream_cache
    def streamer_again(self, model, messages, stream, tools, **kwargs):
        upstream_calls.append(1)
        yield "SHOULD NOT REACH UPSTREAM"

    replayed = list(streamer_again(None, "m", messages, stream=True, tools=None))

    assert replayed == ["alpha", "beta"]
    assert not upstream_calls


@pytest.mark.unit
@patch("application.cache.get_redis_instance")
def test_a_json_array_answer_is_never_replayed_as_stream_chunks(mock_make_redis):
    """A gen answer that happens to be a JSON array is not a chunk list.

    The stream reader's pre-v1 compatibility branch accepts a bare JSON array,
    so a colliding gen entry used to be replayed verbatim as the streamed
    answer -- silent corruption rather than a cache miss.
    """
    fake = _FakeRedis()
    mock_make_redis.return_value = fake
    messages = [{"role": "user", "content": "test"}]

    @gen_cache
    def generator(self, model, messages, stream, tools, **kwargs):
        return '["alpha", "beta"]'

    generator(None, "m", messages, stream=False, tools=None)

    @stream_cache
    def streamer(self, model, messages, stream, tools, **kwargs):
        yield "fresh"

    assert list(streamer(None, "m", messages, stream=True, tools=None)) == ["fresh"]
