import hashlib
import json
import logging
import socket as _socket
import time
from threading import Lock

import redis

from application.core.settings import settings
from application.utils import get_hash

logger = logging.getLogger(__name__)

# Upper bound on any single blocking read by a pub/sub subscriber. Must stay
# comfortably above Topic.subscribe's poll_timeout (1 s) — get_message's idle
# wait polls with select() and never trips socket_timeout, but a half-open
# connection's pending read (e.g. the health-check PONG) does.
PUBSUB_SOCKET_TIMEOUT_SECONDS = 10


def _cache_default(value):
    # Image attachments arrive inline as bytes (see GoogleLLM.prepare_messages_with_attachments);
    # hash so the cache key stays bounded in size and stable across identical content.
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<bytes:sha256:{hashlib.sha256(bytes(value)).hexdigest()}>"
    return repr(value)

_redis_instance = None
_redis_creation_failed = False
_instance_lock = Lock()

def get_redis_instance():
    global _redis_instance, _redis_creation_failed
    if _redis_instance is None and not _redis_creation_failed:
        with _instance_lock:
            if _redis_instance is None and not _redis_creation_failed:
                try:
                    # ``health_check_interval`` makes redis-py ping the
                    # connection every N seconds when otherwise idle.
                    # Without it, a half-open TCP (NAT silently dropped
                    # state, ELB idle-close) can hang the SSE generator
                    # in ``pubsub.get_message`` past its keepalive
                    # cadence — the kernel never surfaces the dead
                    # socket because no payload is in flight.
                    _redis_instance = redis.Redis.from_url(
                        settings.CACHE_REDIS_URL,
                        socket_connect_timeout=2,
                        health_check_interval=10,
                    )
                except ValueError as e:
                    logger.error(f"Invalid Redis URL: {e}")
                    _redis_creation_failed = True  # Stop future attempts
                    _redis_instance = None
                except redis.ConnectionError as e:
                    logger.error(f"Redis connection error: {e}")
                    _redis_instance = None  # Keep trying for connection errors
    return _redis_instance


_pubsub_redis_instance = None
_pubsub_redis_creation_failed = False


def _tcp_keepalive_options():
    """Kernel keepalive knobs for long-lived, mostly-idle pub/sub sockets.

    Probing well inside NAT/IPVS idle-expiry windows (Docker Swarm's IPVS
    expires idle flows after ~15 min) keeps the flow-table entry alive and
    lets the kernel surface a dead peer instead of leaving the socket
    half-open. The constants are Linux-specific, so build the dict from
    whatever this platform exposes.
    """
    options = {}
    for name, value in (("TCP_KEEPIDLE", 300), ("TCP_KEEPINTVL", 60), ("TCP_KEEPCNT", 3)):
        const = getattr(_socket, name, None)
        if const is not None:
            options[const] = value
    return options


def get_pubsub_redis_instance():
    """Redis client dedicated to pub/sub subscribers.

    Separate from ``get_redis_instance`` because subscribers hold a socket
    open for the life of an SSE connection. Without ``socket_timeout``, a
    connection silently dropped by NAT/IPVS blocks ``pubsub.get_message``
    forever — including the ``health_check_interval`` PONG read — pinning
    the subscriber's WSGI thread until the worker restarts. Bounding every
    read lets a dead subscriber fail within seconds and release its thread.

    Returns:
        A shared ``redis.Redis`` client, or ``None`` if Redis is
        unavailable or ``CACHE_REDIS_URL`` is invalid.
    """
    global _pubsub_redis_instance, _pubsub_redis_creation_failed
    if _pubsub_redis_instance is None and not _pubsub_redis_creation_failed:
        with _instance_lock:
            if _pubsub_redis_instance is None and not _pubsub_redis_creation_failed:
                try:
                    _pubsub_redis_instance = redis.Redis.from_url(
                        settings.CACHE_REDIS_URL,
                        socket_connect_timeout=2,
                        socket_timeout=PUBSUB_SOCKET_TIMEOUT_SECONDS,
                        socket_keepalive=True,
                        socket_keepalive_options=_tcp_keepalive_options(),
                        health_check_interval=10,
                    )
                except ValueError as e:
                    logger.error(f"Invalid Redis URL: {e}")
                    _pubsub_redis_creation_failed = True  # Stop future attempts
                    _pubsub_redis_instance = None
                except redis.ConnectionError as e:
                    logger.error(f"Redis connection error: {e}")
                    _pubsub_redis_instance = None  # Keep trying for connection errors
    return _pubsub_redis_instance


def gen_cache_key(messages, model="docgpt", tools=None):
    if not all(isinstance(msg, dict) for msg in messages):
        raise ValueError("All messages must be dictionaries.")
    messages_str = json.dumps(messages, default=_cache_default)
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
                    decoded = json.loads(cached_response.decode("utf-8"))
                    if (
                        isinstance(decoded, dict)
                        and decoded.get("version") == 1
                        and isinstance(decoded.get("chunks"), list)
                    ):
                        cached_chunks = decoded["chunks"]
                    elif isinstance(decoded, list) and not any(
                        isinstance(chunk, str)
                        and "_RespChoice" in chunk
                        for chunk in decoded
                    ):
                        # Backward-compatible read for pre-v1 string-only
                        # entries. Protocol-object reprs are deliberately
                        # rejected and refreshed from upstream.
                        cached_chunks = decoded
                    else:
                        cached_chunks = None

                    if cached_chunks is not None:
                        logger.info(f"Cache hit for stream key: {cache_key}")
                        for chunk in cached_chunks:
                            yield chunk
                            time.sleep(0.03)  # Simulate streaming delay
                        return
                    redis_client.delete(cache_key)
            except Exception as e:
                logger.error(f"Error getting cached stream: {e}", exc_info=True)

        stream_cache_data = []
        cacheable = True
        # Skip caching streams that produced no visible content — a
        # reasoning-only stop (thoughts only, no str deltas) would
        # otherwise be replayed for the whole TTL on every identical
        # request, poisoning the cache and denying the reasoning-only
        # recovery path any chance to run against a fresh provider call
        # (subsequent identical requests replay the cached empty stream,
        # trip the recovery guard, and produce another silent-loss).
        had_content = False
        for chunk in func(self, model, messages, stream, tools, *args, **kwargs):
            yield chunk
            if isinstance(chunk, str) and chunk:
                had_content = True
            if isinstance(chunk, (str, dict, list, int, float, bool, type(None))):
                try:
                    json.dumps(chunk)
                    stream_cache_data.append(chunk)
                except (TypeError, ValueError):
                    cacheable = False
            else:
                cacheable = False

        if redis_client and cacheable and had_content:
            try:
                payload = {"version": 1, "chunks": stream_cache_data}
                redis_client.set(cache_key, json.dumps(payload), ex=1800)
                logger.info(f"Stream cache saved for key: {cache_key}")
            except Exception as e:
                logger.error(f"Error setting stream cache: {e}", exc_info=True)

    return wrapper
