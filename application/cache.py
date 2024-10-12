import sys
import redis
import time
from datetime import datetime
from application.core.settings import settings
from application.utils import get_hash


# Initialize Redis client
redis_client = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=settings.REDIS_DB,
)

def gen_cache_key(messages):
    """
    Generate a unique cache key using the latest user prompt.
    """
    latest_user_prompt = next((msg['content'] for msg in reversed(messages) if msg['role'] == 'user'), None)
    if latest_user_prompt is None:
        raise ValueError("No user message found in the conversation to generate a cache key.")
    cache_key = get_hash(latest_user_prompt)
    return cache_key


def gen_cache(func):
    """
    Decorator to cache the response of a function that generates a response using an LLM.
    
    This decorator first checks if a response is cached for the given input (model and messages).
    If a cached response is found, it returns that. If not, it generates the response,
    caches it, and returns the generated response.
    Args:
        func (function): The function to be decorated.
    Returns:
        function: The wrapped function that handles caching and LLM response generation.
    """
    def wrapper(self, model, messages, *args, **kwargs):
        cache_key = gen_cache_key(messages=messages)
        cached_response = redis_client.get(cache_key)
        if cached_response:
            print(f"Cache hit for key: {cache_key}")
            return cached_response.decode('utf-8')
        result = func(self, model, messages, *args, **kwargs)
        redis_client.set(cache_key, result, ex=3600)
        print(f"Cache saved for key: {cache_key}")
        return result
    return wrapper

def stream_cache(func):
    """
    Decorator to cache the streamed response of an LLM function.
    
    This decorator first checks if a streamed response is cached for the given input (model and messages).
    If a cached response is found, it yields that. If not, it streams the response, caches it,
    and then yields the response.
    
    Args:
        func (function): The function to be decorated.
        
    Returns:
        function: The wrapped function that handles caching and streaming LLM responses.
    """
    def wrapper(self, model, messages, *args, **kwargs):
        cache_key = gen_cache_key(messages=messages)

        # we are using lrange and rpush to simulate streaming
        cached_response = redis_client.lrange(cache_key, 0, -1)
        if cached_response:
            print(f"Cache hit for stream key: {cache_key}")
            for chunk in cached_response:
                print(f"Streaming cached chunk: {chunk.decode('utf-8')}")
                yield chunk.decode('utf-8')
                # need to slow down the response to simulate streaming
                # because the cached response is instantaneous
                # and redis is using in-memory storage  
                time.sleep(0.07)
            return

        result = func(self, model, messages, *args, **kwargs)
        
        for chunk in result:
            print(f"Streaming live chunk: {chunk}")
            redis_client.rpush(cache_key, chunk)
            yield chunk 
        
        # expire the cache after 30 minutes
        redis_client.expire(cache_key, 1800)
        print(f"Stream cache saved for key: {cache_key}")
        
    return wrapper

