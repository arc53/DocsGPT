import json
import logging
import time
from threading import Lock

import redis

from application.core.settings import settings
from application.utils import get_hash

logger = logging.getLogger(__name__)

_redis_instance = None
_instance_lock = Lock()


def get_redis_instance():
    global _redis_instance
    if _redis_instance is None:
        with _instance_lock:
            if _redis_instance is None:
                try:
                    _redis_instance = redis.Redis.from_url(
                        settings.CACHE_REDIS_URL, socket_connect_timeout=2
                    )
                except redis.ConnectionError as e:
                    logger.error(f"Redis connection error: {e}")
                    _redis_instance = None
    return _redis_instance


def gen_cache_key(messages, model="docgpt", tools=None):
    if not all(isinstance(msg, dict) for msg in messages):
        raise ValueError("All messages must be dictionaries.")
    messages_str = json.dumps(messages)
    tools_str = json.dumps(tools) if tools else ""
    combined = f"{model}_{messages_str}_{tools_str}"
    cache_key = get_hash(combined)
    return cache_key


def gen_cache(func):
    def wrapper(self, model, messages, stream, tools=None, *args, **kwargs):
        try:
            cache_key = gen_cache_key(messages, model, tools)
            redis_client = get_redis_instance()
            if redis_client:
                try:
                    cached_response = redis_client.get(cache_key)
                    if cached_response:
                        return cached_response.decode("utf-8")
                except redis.ConnectionError as e:
                    logger.error(f"Redis connection error: {e}")

            result = func(self, model, messages, stream, tools, *args, **kwargs)
            if redis_client and isinstance(result, str):
                try:
                    redis_client.set(cache_key, result, ex=1800)
                except redis.ConnectionError as e:
                    logger.error(f"Redis connection error: {e}")

            return result
        except ValueError as e:
            logger.error(e)
            return "Error: No user message found in the conversation to generate a cache key."

    return wrapper


def stream_cache(func):
    def wrapper(self, model, messages, stream, *args, **kwargs):
        cache_key = gen_cache_key(messages)
        logger.info(f"Stream cache key: {cache_key}")

        redis_client = get_redis_instance()
        if redis_client:
            try:
                cached_response = redis_client.get(cache_key)
                if cached_response:
                    logger.info(f"Cache hit for stream key: {cache_key}")
                    cached_response = json.loads(cached_response.decode("utf-8"))
                    for chunk in cached_response:
                        yield chunk
                        time.sleep(0.03)
                    return
            except redis.ConnectionError as e:
                logger.error(f"Redis connection error: {e}")

        result = func(self, model, messages, stream, *args, **kwargs)
        stream_cache_data = []

        for chunk in result:
            stream_cache_data.append(chunk)
            yield chunk

        if redis_client:
            try:
                redis_client.set(cache_key, json.dumps(stream_cache_data), ex=1800)
                logger.info(f"Stream cache saved for key: {cache_key}")
            except redis.ConnectionError as e:
                logger.error(f"Redis connection error: {e}")

    return wrapper
