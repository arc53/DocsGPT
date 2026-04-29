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
            "redis://localhost:6379/0", socket_connect_timeout=2
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
