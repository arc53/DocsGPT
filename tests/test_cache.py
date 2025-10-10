import json
from unittest.mock import MagicMock, patch

import pytest
from application.cache import gen_cache, gen_cache_key, stream_cache
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
