"""Lazy async Redis client for the native-async SSE reader.

Async twin of :func:`application.cache.get_redis_instance`. The
Starlette-mounted reader (``application.api.async_sse``) tails pub/sub on
the event loop, so it needs a ``redis.asyncio`` client rather than the
sync one used by the producer side. The app runs a single ASGI worker /
event loop, so a module-level singleton is sufficient and avoids
reconnecting per request.
"""

from __future__ import annotations

import logging
from typing import Optional

import redis.asyncio as aioredis

from application.core.settings import settings

logger = logging.getLogger(__name__)

_async_redis: Optional[aioredis.Redis] = None
_creation_failed = False


async def get_async_redis_instance() -> Optional[aioredis.Redis]:
    """Return a process-wide async Redis client, or ``None`` if unavailable.

    ``from_url`` builds the client without opening a socket (connection is
    lazy), so a transient broker outage surfaces later on the first command
    rather than here. Mirrors the sync client's ``socket_connect_timeout``
    and ``health_check_interval`` so a half-open TCP can't wedge the tail
    loop past its keepalive cadence.
    """
    global _async_redis, _creation_failed
    if _async_redis is None and not _creation_failed:
        try:
            _async_redis = aioredis.Redis.from_url(
                settings.CACHE_REDIS_URL,
                socket_connect_timeout=2,
                health_check_interval=10,
            )
        except ValueError as e:
            logger.error("Invalid Redis URL for async client: %s", e)
            _creation_failed = True
            _async_redis = None
    return _async_redis
