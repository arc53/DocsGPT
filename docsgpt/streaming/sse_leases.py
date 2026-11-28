"""Per-connection leases behind the per-user SSE connection cap.

Each open stream holds a member in the sorted set ``user:{id}:sse_leases``,
scored by when it last refreshed. Dropping stale members and counting the rest
enforces ``SSE_MAX_CONCURRENT_PER_USER``. A stream refreshes its lease while it
runs and removes it when it ends; a lease whose stream died without cleanup
(SIGKILL, OOM) ages out after the lease TTL. Unlike a shared counter with a
TTL, an expiring lease can't take another stream's slot with it or drive the
count negative.

A chat reconnect may evict instead of being refused. When a phone or laptop
loses its network, the server keeps that device's streams (and their leases)
until a write fails, so the reconnect that follows can find the cap full of
the user's own dead connections. The oldest leases are moved to
``user:{id}:sse_evicted`` and their streams end at their next refresh.
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
from docsgpt.events.keys import connection_leases_key, evicted_leases_key
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

    evicted_key: str = ""

    async def refresh_if_due(self) -> bool:
        """Re-stamp the lease once a third of its TTL has passed; failures are logged, not raised.

        Returns:
            False when a newer connection evicted this lease, so its stream
            should end; True otherwise, including when the refresh failed.
        """
        now = time.monotonic()
        if now - self.refreshed_at < self.ttl / 3:
            return True
        self.refreshed_at = now
        try:
            with anyio.fail_after(ASYNC_REDIS_OP_TIMEOUT_SECONDS):
                async with self.redis.pipeline(transaction=True) as pipe:
                    # XX: a lease pruned or cleared while refreshes were failing
                    # stays gone instead of retaking a slot past the cap.
                    pipe.zadd(self.key, {self.lease_id: time.time()}, xx=True)
                    pipe.expire(self.key, int(self.ttl))
                    if self.evicted_key:
                        pipe.zscore(self.evicted_key, self.lease_id)
                    results = await pipe.execute()
        except Exception:
            logger.debug("SSE lease refresh failed for key=%s", self.key, exc_info=True)
            return True
        return not (self.evicted_key and results[2] is not None)

    async def release(self) -> None:
        """Remove this lease; shielded so it completes during cancellation, and bounded."""
        with anyio.move_on_after(ASYNC_REDIS_OP_TIMEOUT_SECONDS, shield=True):
            try:
                await self.redis.zrem(self.key, self.lease_id)
            except Exception:
                logger.debug("SSE lease release failed for key=%s", self.key, exc_info=True)


async def acquire_stream_lease(redis: Any, user_id: str, *, evict_oldest: bool = False) -> Optional[StreamLease]:
    """Claim a connection slot for ``user_id``.

    Args:
        redis: The async Redis client, or ``None`` when unavailable.
        user_id: The user opening the stream.
        evict_oldest: Over the cap, evict the user's oldest leases instead of
            refusing. For a chat reconnect: the answer it follows is still
            running, and the slots are most likely held by the connections
            that died with the user's network.

    Returns:
        The lease to refresh and release, or ``None`` when the cap is disabled
        or Redis is unavailable or failing (fail-open).

    Raises:
        StreamCapExceeded: The user already holds the maximum number of
            streams, and ``evict_oldest`` is not set or eviction failed.
    """
    cap = int(settings.SSE_MAX_CONCURRENT_PER_USER)
    if cap <= 0 or redis is None:
        return None
    key = connection_leases_key(user_id)
    ttl = lease_ttl_seconds()
    lease = StreamLease(
        redis=redis,
        key=key,
        lease_id=uuid.uuid4().hex,
        ttl=ttl,
        refreshed_at=time.monotonic(),
        evicted_key=evicted_leases_key(user_id),
    )
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
    count = int(results[2])
    if count > cap:
        if not (evict_oldest and await _evict_oldest(lease, count - cap)):
            await lease.release()
            raise StreamCapExceeded()
    return lease


async def _evict_oldest(lease: StreamLease, overflow: int) -> bool:
    """Free ``overflow`` slots by evicting the oldest leases other than ``lease``.

    The evicted ids are recorded so their streams end at their next refresh
    (within a third of the lease TTL) instead of running on uncounted.

    Returns:
        True when the slots were freed.
    """
    try:
        with anyio.fail_after(ASYNC_REDIS_OP_TIMEOUT_SECONDS):
            # One extra, in case the new lease ties the oldest score.
            oldest = await lease.redis.zrange(lease.key, 0, overflow)
            victims = [m for m in (_member(m) for m in oldest) if m != lease.lease_id][:overflow]
            if len(victims) < overflow:
                return False
            now = time.time()
            async with lease.redis.pipeline(transaction=True) as pipe:
                pipe.zrem(lease.key, *victims)
                pipe.zadd(lease.evicted_key, {victim: now for victim in victims})
                pipe.zremrangebyscore(lease.evicted_key, "-inf", now - lease.ttl)
                pipe.expire(lease.evicted_key, int(lease.ttl))
                await pipe.execute()
    except Exception:
        logger.debug("SSE lease eviction failed for key=%s", lease.key, exc_info=True)
        return False
    logger.info("sse.lease.evicted key=%s count=%d", lease.key, len(victims))
    return True


def _member(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


async def hold_lease(stream: AsyncIterator[T], lease: Optional[StreamLease]) -> AsyncIterator[T]:
    """Yield from ``stream``, refreshing ``lease`` between frames; closing this closes ``stream``."""
    async with aclosing(stream):
        async for item in stream:
            yield item
            if lease is not None and not await lease.refresh_if_due():
                # A newer chat reconnect took this slot. The client, if it
                # is still there, reconnects; most likely it is long gone.
                logger.info("sse.lease.evicted_stream_closed key=%s", lease.key)
                return
