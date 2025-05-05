import json
import logging
import time
from threading import Lock

import redis

from application.core.settings import settings
from application.utils import get_hash

logger = logging.getLogger(__name__)

_redis_instance = None
_redis_creation_failed = False
_instance_lock = Lock()

def get_redis_instance():
    global _redis_instance, _redis_creation_failed
    if _redis_instance is None and not _redis_creation_failed:
        with _instance_lock:
            if _redis_instance is None and not _redis_creation_failed:
                try:
                    _redis_instance = redis.Redis.from_url(
                        settings.CACHE_REDIS_URL, socket_connect_timeout=2
                    )
                except ValueError as e:
                    logger.error(f"Invalid Redis URL: {e}")
                    _redis_creation_failed = True  # Stop future attempts
                    _redis_instance = None
                except redis.ConnectionError as e:
                    logger.error(f"Redis connection error: {e}")
                    _redis_instance = None  # Keep trying for connection errors
    return _redis_instance


def gen_cache_key(messages, model="docgpt", tools=None):
    if not all(isinstance(msg, dict) for msg in messages):
        raise ValueError("All messages must be dictionaries.")
    messages_str = json.dumps(messages)
    tools_str = json.dumps(str(tools)) if tools else ""
    combined = f"{model}_{messages_str}_{tools_str}"
    cache_key = get_hash(combined)
    return cache_key


def gen_cache(func):
    def wrapper(self, model, messages, stream, tools=None, *args, **kwargs):
        if tools is not None:
            return func(self, model, messages, stream, tools, *args, **kwargs)
        
        try:
            cache_key = gen_cache_key(messages, model, tools)
        except ValueError as e:
            logger.error(f"Cache key generation failed: {e}")
            return func(self, model, messages, stream, tools, *args, **kwargs)

        redis_client = get_redis_instance()
        if redis_client:
            try:
                cached_response = redis_client.get(cache_key)
                if cached_response:
                    return cached_response.decode("utf-8")
            except Exception as e:
                logger.error(f"Error getting cached response: {e}", exc_info=True)

        result = func(self, model, messages, stream, tools, *args, **kwargs)
        if redis_client and isinstance(result, str):
            try:
                redis_client.set(cache_key, result, ex=1800)
            except Exception as e:
                logger.error(f"Error setting cache: {e}", exc_info=True)

        return result

    return wrapper


def stream_cache(func):
    def wrapper(self, model, messages, stream, tools=None, *args, **kwargs):
        if tools is not None:
            yield from func(self, model, messages, stream, tools, *args, **kwargs)
            return
        
        try:
            cache_key = gen_cache_key(messages, model, tools)
        except ValueError as e:
            logger.error(f"Cache key generation failed: {e}")
            yield from func(self, model, messages, stream, tools, *args, **kwargs)
            return

        redis_client = get_redis_instance()
        if redis_client:
            try:
                cached_response = redis_client.get(cache_key)
                if cached_response:
                    logger.info(f"Cache hit for stream key: {cache_key}")
                    cached_response = json.loads(cached_response.decode("utf-8"))
                    for chunk in cached_response:
                        yield chunk
                        time.sleep(0.03)  # Simulate streaming delay
                    return
            except Exception as e:
                logger.error(f"Error getting cached stream: {e}", exc_info=True)

        stream_cache_data = []
        for chunk in func(self, model, messages, stream, tools, *args, **kwargs):
            yield chunk
            stream_cache_data.append(str(chunk))

        if redis_client:
            try:
                redis_client.set(cache_key, json.dumps(stream_cache_data), ex=1800)
                logger.info(f"Stream cache saved for key: {cache_key}")
            except Exception as e:
                logger.error(f"Error setting stream cache: {e}", exc_info=True)

    return wrapper
