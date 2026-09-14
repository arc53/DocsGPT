"""Lazy async Redis client for the native-async (event-loop) routes.

Async twin of :func:`docsgpt.cache.get_redis_instance`. The Starlette-mounted
routes — the chat reconnect reader, ``/api/events`` and the device command
stream — wait on Redis from the event loop, so they need a ``redis.asyncio``
client rather than the sync one used by the producer side. The app runs a
single ASGI worker / event loop, so a module-level singleton is sufficient
and avoids reconnecting per request.
"""

from __future__ import annotations

import logging
from typing import Optional

import redis.asyncio as aioredis

from docsgpt.cache import PUBSUB_SOCKET_TIMEOUT_SECONDS, _tcp_keepalive_options
from docsgpt.core.settings import settings

logger = logging.getLogger(__name__)

# Upper bound on one Redis command made while opening or holding a stream, so
# a stalled connection fails open instead of holding the request or cleanup.
ASYNC_REDIS_OP_TIMEOUT_SECONDS = 5.0

_async_redis: Optional[aioredis.Redis] = None
_creation_failed = False


async def get_async_redis_instance() -> Optional[aioredis.Redis]:
    """Return a process-wide async Redis client, or ``None`` if unavailable.

    ``from_url`` builds the client without opening a socket (connection is
    lazy), so a transient broker outage surfaces later on the first command
    rather than here. Uses the sync pub/sub client's timeouts and TCP
    keepalive, so a connection NAT/IPVS dropped without a FIN fails a
    ``BLPOP`` or ``XRANGE`` instead of hanging it. Pub/sub polls pass their
    own read timeout, so ``socket_timeout`` doesn't cut idle subscribers.
    Every open stream holds a pooled connection, so the pool is sized by
    ``ASYNC_REDIS_MAX_CONNECTIONS`` rather than redis-py's default of 100.
    """
    global _async_redis, _creation_failed
    if _async_redis is None and not _creation_failed:
        try:
            _async_redis = aioredis.Redis.from_url(
                settings.CACHE_REDIS_URL,
                socket_connect_timeout=2,
                socket_timeout=PUBSUB_SOCKET_TIMEOUT_SECONDS,
                socket_keepalive=True,
                socket_keepalive_options=_tcp_keepalive_options(),
                health_check_interval=10,
                max_connections=int(settings.ASYNC_REDIS_MAX_CONNECTIONS),
            )
        except ValueError as e:
            logger.error("Invalid Redis URL for async client: %s", e)
            _creation_failed = True
            _async_redis = None
    return _async_redis
