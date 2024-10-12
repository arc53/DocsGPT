import unittest
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
    
    # Manually calculate the expected hash
    expected_combined = f"{model}_test_user_message"
    expected_hash = get_hash(expected_combined)
    cache_key = gen_cache_key(messages=messages, model=model)

    assert cache_key == expected_hash


def test_gen_cache_key_no_messages():
    # Test with no messages
    with unittest.TestCase.assertRaises(unittest.TestCase, ValueError) as context:
        gen_cache_key([], model="docgpt")
    assert str(context.exception) == "No messages found in the conversation to generate a cache key."


def test_gen_cache_key_invalid_message_format():
    # Test when messages is not a list
    with unittest.TestCase.assertRaises(unittest.TestCase, ValueError) as context:
        gen_cache_key("This is not a list", model="docgpt")
    assert str(context.exception) == "Messages must be a list of dictionaries."


def test_gen_cache_key_no_user_message():
    # Test when there is no user message in the messages
    messages = [
        {'role': 'system', 'content': 'System message.'},
        {'role': 'assistant', 'content': 'I can help you.'}
    ]
    with unittest.TestCase.assertRaises(unittest.TestCase, ValueError) as context:
        gen_cache_key(messages=messages, model="docgpt")
    assert str(context.exception) == "No user message found in the conversation to generate a cache key."


# Test for gen_cache decorator
@patch('application.cache.make_redis')  # Mock the Redis client
def test_gen_cache_hit(mock_make_redis):
    # Arrange
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.return_value = b"cached_result"  # Simulate a cache hit

    @gen_cache
    def mock_function(self, model, messages):
        return "new_result"

    messages = [{'role': 'user', 'content': 'test_user_message'}]
    model = "test_docgpt"

    # Act
    result = mock_function(None, model, messages)

    # Assert
    assert result == "cached_result"  # Should return cached result
    mock_redis_instance.get.assert_called_once()  # Ensure Redis get was called
    mock_redis_instance.set.assert_not_called()  # Ensure the function result is not cached again


@patch('application.cache.make_redis')  # Mock the Redis client
def test_gen_cache_miss(mock_make_redis):
    # Arrange
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.get.return_value = None  # Simulate a cache miss

    @gen_cache
    def mock_function(self, model, messages):
        return "new_result"

    messages = [
        {'role': 'user', 'content': 'test_user_message'},
        {'role': 'system', 'content': 'test_system_message'},
    ]
    model = "test_docgpt"
    # Act
    result = mock_function(None, model, messages)

    # Assert
    assert result == "new_result"
    mock_redis_instance.get.assert_called_once() 


@patch('application.cache.make_redis') 
def test_gen_cache_no_user_message(mock_make_redis):
    # Arrange
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance

    @gen_cache
    def mock_function(self, model, messages):
        return "new_result"

    messages = [{'role': 'system', 'content': 'test_system_message'}]
    model = "test_docgpt"

    # Act
    result = mock_function(None, model, messages)

    # Assert
    assert result == "Error: No user message found in the conversation to generate a cache key."
    mock_redis_instance.get.assert_not_called()
    mock_redis_instance.set.assert_not_called()


@patch('application.cache.make_redis')  
def test_stream_cache_hit(mock_make_redis):
    # Arrange
    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.lrange.return_value = [b"chunk1", b"chunk2"]  # Simulate a cache hit with chunks

    @stream_cache
    def mock_function(self, model, messages, stream):
        yield "new_chunk"

    messages = [{'role': 'user', 'content': 'test_user_message'}]
    model = "test_docgpt"

    # Act
    result = list(mock_function(None, model, messages, stream=True))

    # Assert
    assert result == ["chunk1", "chunk2"]  # Should return cached chunks
    mock_redis_instance.lrange.assert_called_once()
    mock_redis_instance.rpush.assert_not_called() 


@patch('application.cache.make_redis')
def test_stream_cache_miss(mock_make_redis):

    mock_redis_instance = MagicMock()
    mock_make_redis.return_value = mock_redis_instance
    mock_redis_instance.lrange.return_value = [] 

    @stream_cache
    def mock_function(self, model, messages, stream):
        yield "new_chunk"

    messages = [
                {'role': 'user', 'content': 'This is the context'},
                {'role': 'system', 'content': 'Some other message'},
                {'role': 'user', 'content': 'What is the answer?'}
    ]

    model = "test_docgpt"

    # Act
    result = list(mock_function(None, model, messages, stream=True))
    
    # Assert
    assert result == ["new_chunk"]
    mock_redis_instance.lrange.assert_called_once()
    mock_redis_instance.rpush.assert_called_once()



    


