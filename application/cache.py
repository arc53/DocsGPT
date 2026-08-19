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


# Generation kwargs that never reach the provider: usage-accounting side
# channels only. Everything else the caller passes (``response_format``,
# ``response_schema``, ``tool_choice``, ``reasoning_effort``, sampling
# params, ...) is part of the request and therefore part of the key —
# otherwise a workflow node that changed its JSON schema replays the old
# schema's cached answer for the whole TTL.
_CACHE_KEY_IGNORED_KWARGS = frozenset({"_usage_attachments", "attachments"})

# Kwargs that make the answer depend on provider-held state no key can
# capture. ``previous_response_id`` chains a Responses API turn server
# side, and a cache hit would also skip the ``_last_response_id``
# bookkeeping the next turn needs — so skip the cache entirely.
_CACHE_BYPASS_KWARGS = ("previous_response_id",)


def _gen_kwargs_fingerprint(extra: dict | None) -> str:
    """Stable fingerprint of the generation-affecting kwargs.

    Args:
        extra: Keyword arguments forwarded to the generation call.

    Returns:
        A sorted JSON dump of the semantic kwargs, or "" when there are none.

    Raises:
        ValueError: If the kwargs cannot be serialized (callers treat this
            as "do not cache").
    """
    if not extra:
        return ""
    filtered = {
        key: value
        for key, value in extra.items()
        if key not in _CACHE_KEY_IGNORED_KWARGS and value is not None
    }
    if not filtered:
        return ""
    try:
        return json.dumps(filtered, sort_keys=True, default=_cache_default)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Unserializable generation kwargs: {e}") from e


def _bypasses_cache(extra: dict | None) -> bool:
    """Whether a kwarg ties the call to provider-side conversation state."""
    if not extra:
        return False
    return any(extra.get(key) for key in _CACHE_BYPASS_KWARGS)


def _is_stream_payload(raw: str) -> bool:
    """Whether a cached value is a ``stream_cache`` chunk envelope.

    ``gen_cache`` and ``stream_cache`` share one key space, so a
    non-streaming read can land on a stream entry; without this guard the
    serialized chunk list would be handed back as the model's answer.
    """
    if not raw.startswith("{"):
        return False
    try:
        decoded = json.loads(raw)
    except ValueError:
        return False
    return isinstance(decoded, dict) and isinstance(decoded.get("chunks"), list)


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


def gen_cache_key(messages, model="docgpt", tools=None, extra=None):
    """Build the Redis key for one generation call.

    Args:
        messages: Chat messages for the call.
        model: Model identifier.
        tools: Tool schemas, when the call carries any.
        extra: Remaining generation kwargs (``response_format``,
            ``response_schema``, sampling params, ...). Non-semantic keys
            are dropped before hashing; the suffix is omitted entirely when
            nothing semantic remains, so keys for plain calls are unchanged.

    Returns:
        Hex digest used as the cache key.

    Raises:
        ValueError: If ``messages`` holds a non-dict entry, or ``extra``
            cannot be serialized.
    """
    if not all(isinstance(msg, dict) for msg in messages):
        raise ValueError("All messages must be dictionaries.")
    messages_str = json.dumps(messages, default=_cache_default)
    tools_str = json.dumps(str(tools)) if tools else ""
    combined = f"{model}_{messages_str}_{tools_str}"
    extra_str = _gen_kwargs_fingerprint(extra)
    if extra_str:
        combined = f"{combined}_{extra_str}"
    cache_key = get_hash(combined)
    return cache_key


def gen_cache(func):
    def wrapper(self, model, messages, stream, tools=None, *args, **kwargs):
        if tools is not None or _bypasses_cache(kwargs):
            return func(self, model, messages, stream, tools, *args, **kwargs)

        try:
            cache_key = gen_cache_key(messages, model, tools, extra=kwargs)
        except ValueError as e:
            logger.error(f"Cache key generation failed: {e}")
            return func(self, model, messages, stream, tools, *args, **kwargs)

        redis_client = get_redis_instance()
        if redis_client:
            try:
                cached_response = redis_client.get(cache_key)
                if cached_response:
                    decoded = cached_response.decode("utf-8")
                    if not _is_stream_payload(decoded):
                        return decoded
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
        if tools is not None or _bypasses_cache(kwargs):
            yield from func(self, model, messages, stream, tools, *args, **kwargs)
            return

        try:
            cache_key = gen_cache_key(messages, model, tools, extra=kwargs)
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
