"""Per-connection leases behind the per-user SSE connection cap.

Each open stream holds a member in the sorted set ``user:{id}:sse_leases``,
scored by when it last refreshed. Dropping stale members and counting the rest
enforces ``SSE_MAX_CONCURRENT_PER_USER``. A stream refreshes its lease while it
runs and removes it when it ends; a lease whose stream died without cleanup
(SIGKILL, OOM) ages out after the lease TTL. Unlike a shared counter with a
TTL, an expiring lease can't take another stream's slot with it or drive the
count negative.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional, TypeVar

import anyio

from docsgpt.core.settings import settings
from docsgpt.events.keys import connection_leases_key
from docsgpt.streaming.async_redis import ASYNC_REDIS_OP_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

T = TypeVar("T")


class StreamCapExceeded(Exception):
    """Raised when the user already holds ``SSE_MAX_CONCURRENT_PER_USER`` streams."""


def lease_ttl_seconds() -> float:
    """Seconds a lease survives without a refresh.

    A stream yields at least once per keepalive interval and refreshes on the
    first yield after a third of the TTL, so four keepalives of headroom keep a
    live stream's lease from expiring.
    """
    return max(60.0, 4.0 * float(settings.SSE_KEEPALIVE_SECONDS))


@dataclass
class StreamLease:
    """One stream's claim on a slot in its user's connection cap."""

    redis: Any
    key: str
    lease_id: str
    ttl: float
    refreshed_at: float

    async def refresh_if_due(self) -> None:
        """Re-stamp the lease once a third of its TTL has passed; failures are logged, not raised."""
        now = time.monotonic()
        if now - self.refreshed_at < self.ttl / 3:
            return
        self.refreshed_at = now
        try:
            with anyio.fail_after(ASYNC_REDIS_OP_TIMEOUT_SECONDS):
                async with self.redis.pipeline(transaction=True) as pipe:
                    # XX: a lease pruned or cleared while refreshes were failing
                    # stays gone instead of retaking a slot past the cap.
                    pipe.zadd(self.key, {self.lease_id: time.time()}, xx=True)
                    pipe.expire(self.key, int(self.ttl))
                    await pipe.execute()
        except Exception:
            logger.debug("SSE lease refresh failed for key=%s", self.key, exc_info=True)

    async def release(self) -> None:
        """Remove this lease; shielded so it completes during cancellation, and bounded."""
        with anyio.move_on_after(ASYNC_REDIS_OP_TIMEOUT_SECONDS, shield=True):
            try:
                await self.redis.zrem(self.key, self.lease_id)
            except Exception:
                logger.debug("SSE lease release failed for key=%s", self.key, exc_info=True)


async def acquire_stream_lease(redis: Any, user_id: str) -> Optional[StreamLease]:
    """Claim a connection slot for ``user_id``.

    Args:
        redis: The async Redis client, or ``None`` when unavailable.
        user_id: The user opening the stream.

    Returns:
        The lease to refresh and release, or ``None`` when the cap is disabled
        or Redis is unavailable or failing (fail-open).

    Raises:
        StreamCapExceeded: The user already holds the maximum number of streams.
    """
    cap = int(settings.SSE_MAX_CONCURRENT_PER_USER)
    if cap <= 0 or redis is None:
        return None
    key = connection_leases_key(user_id)
    ttl = lease_ttl_seconds()
    lease = StreamLease(redis=redis, key=key, lease_id=uuid.uuid4().hex, ttl=ttl, refreshed_at=time.monotonic())
    now = time.time()
    try:
        with anyio.fail_after(ASYNC_REDIS_OP_TIMEOUT_SECONDS):
            # One transaction, so concurrent connects are counted one at a time.
            async with redis.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(key, "-inf", now - ttl)
                pipe.zadd(key, {lease.lease_id: now})
                pipe.zcard(key)
                pipe.expire(key, int(ttl))
                results = await pipe.execute()
    except Exception:
        logger.debug("SSE lease acquire failed for user=%s; failing open", user_id, exc_info=True)
        # EXEC may have run before its reply was lost; the stream opens without
        # a lease, so its member must not keep counting against the cap.
        await lease.release()
        return None
    if int(results[2]) > cap:
        await lease.release()
        raise StreamCapExceeded()
    return lease


async def hold_lease(stream: AsyncIterator[T], lease: Optional[StreamLease]) -> AsyncIterator[T]:
    """Yield from ``stream``, refreshing ``lease`` between frames; closing this closes ``stream``."""
    async with aclosing(stream):
        async for item in stream:
            yield item
            if lease is not None:
                await lease.refresh_if_due()
