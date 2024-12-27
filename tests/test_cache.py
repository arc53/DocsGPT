import unittest
import json
from unittest.mock import patch, MagicMock
from application.cache import gen_cache_key, stream_cache, gen_cache
from application.utils import get_hash


# Test for gen_cache_key function
def test_make_gen_cache_key():
    messages = [
        {'role': 'user', 'content': 'test_user_message'},
        {'role': 'system', 'content': 'test_system_message'},
    ]
    model = "test_docgpt"
    tools = None
    
    # Manually calculate the expected hash
    messages_str = json.dumps(messages)
    tools_str = json.dumps(tools) if tools else ""
    expected_combined = f"{model}_{messages_str}_{tools_str}"
    expected_hash = get_hash(expected_combined)
    cache_key = gen_cache_key(messages, model=model, tools=None)

    assert cache_key == expected_hash

def test_gen_cache_key_invalid_message_format():
    # Test when messages is not a list
    with unittest.TestCase.assertRaises(unittest.TestCase, ValueError) as context:
        gen_cache_key("This is not a list", model="docgpt", tools=None)
    assert str(context.exception) == "All messages must be dictionaries."

# Test for gen_cache decorator
@patch('application.cache.get_redis_instance')  # Mock the Redis client
def test_gen_cache_hit(mock_make_redis):
    # Arrange
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.return_value = b"cached_result"  # Simulate a cache hit

    @gen_cache
    def mock_function(self, model, messages, stream, tools):
        return "new_result"

    messages = [{'role': 'user', 'content': 'test_user_message'}]
    model = "test_docgpt"

    # Act
    result = mock_function(None, model, messages, stream=False, tools=None)

    # Assert
    assert result == "cached_result"  # Should return cached result
    mock_redis_instance.get.assert_called_once()  # Ensure Redis get was called
    mock_redis_instance.set.assert_not_called()  # Ensure the function result is not cached again


@patch('application.cache.get_redis_instance')  # Mock the Redis client
def test_gen_cache_miss(mock_make_redis):
    # Arrange
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.return_value = None  # Simulate a cache miss

    @gen_cache
    def mock_function(self, model, messages, steam, tools):
        return "new_result"

    messages = [
        {'role': 'user', 'content': 'test_user_message'},
        {'role': 'system', 'content': 'test_system_message'},
    ]
    model = "test_docgpt"
    # Act
    result = mock_function(None, model, messages, stream=False, tools=None)

    # Assert
    assert result == "new_result"
    mock_redis_instance.get.assert_called_once() 

@patch('application.cache.get_redis_instance')  
def test_stream_cache_hit(mock_make_redis):
    # Arrange
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance

    cached_chunk = json.dumps(["chunk1", "chunk2"]).encode('utf-8')
    mock_redis_instance.get.return_value = cached_chunk

    @stream_cache
    def mock_function(self, model, messages, stream, tools):
        yield "new_chunk"

    messages = [{'role': 'user', 'content': 'test_user_message'}]
    model = "test_docgpt"

    # Act
    result = list(mock_function(None, model, messages, stream=True, tools=None))

    # Assert
    assert result == ["chunk1", "chunk2"]  # Should return cached chunks
    mock_redis_instance.get.assert_called_once()
    mock_redis_instance.set.assert_not_called()


@patch('application.cache.get_redis_instance')
def test_stream_cache_miss(mock_make_redis):
    # Arrange
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.return_value = None  # Simulate a cache miss

    @stream_cache
    def mock_function(self, model, messages, stream, tools):
        yield "new_chunk"

    messages = [
        {'role': 'user', 'content': 'This is the context'},
        {'role': 'system', 'content': 'Some other message'},
        {'role': 'user', 'content': 'What is the answer?'}
    ]
    model = "test_docgpt"

    # Act
    result = list(mock_function(None, model, messages, stream=True, tools=None))

    # Assert
    assert result == ["new_chunk"]
    mock_redis_instance.get.assert_called_once()  
    mock_redis_instance.set.assert_called_once()  



    


