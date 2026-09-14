"""In-memory ``redis.asyncio`` stand-in for the SSE lease and event-stream tests.

Sorted sets and transactional pipelines behave like Redis, enough for the
per-connection leases. ``incr``, ``expire``, ``xrange`` and ``xinfo_stream``
are ``AsyncMock`` attributes that tests configure directly. Set ``fail`` to
make sorted-set commands and pipelines raise, ``hang`` to make them never
return (a dead connection), or ``hang_after_execute`` to make a pipeline apply
its commands and then never reply (a reply lost after the server ran EXEC).
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock

import anyio


def _bound(value) -> float:
    if isinstance(value, bytes):
        value = value.decode()
    if value == "-inf":
        return float("-inf")
    if value in ("+inf", "inf"):
        return float("inf")
    return float(value)


def _member(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


class FakeAsyncRedis:
    """Sorted sets + pipelines in memory; everything else is an ``AsyncMock``."""

    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}
        self.key_ttls: dict[str, int] = {}
        self.fail: Optional[BaseException] = None
        self.hang = False
        self.hang_after_execute = False
        self.incr = AsyncMock(return_value=1)
        self.expire = AsyncMock(return_value=True)
        self.xrange = AsyncMock(return_value=[])
        self.xinfo_stream = AsyncMock(side_effect=Exception("no such key"))

    async def _gate(self) -> None:
        if self.hang:
            await anyio.sleep_forever()
        if self.fail is not None:
            raise self.fail

    # -- synchronous cores, shared by direct calls and pipelines -------
    def _zadd(self, key, mapping, xx=False):
        zset = self.zsets.setdefault(key, {})
        added = 0
        for member, score in mapping.items():
            member = _member(member)
            if xx and member not in zset:
                continue
            added += member not in zset
            zset[member] = float(score)
        if not zset:
            self.zsets.pop(key, None)
        return added

    def _zrem(self, key, *members):
        zset = self.zsets.get(key, {})
        removed = 0
        for member in members:
            if zset.pop(_member(member), None) is not None:
                removed += 1
        if key in self.zsets and not zset:
            self.zsets.pop(key)
        return removed

    def _zcard(self, key):
        return len(self.zsets.get(key, {}))

    def _zremrangebyscore(self, key, min, max):
        lo, hi = _bound(min), _bound(max)
        zset = self.zsets.get(key, {})
        stale = [m for m, score in zset.items() if lo <= score <= hi]
        for member in stale:
            zset.pop(member)
        if key in self.zsets and not zset:
            self.zsets.pop(key)
        return len(stale)

    def _set_ttl(self, key, seconds):
        self.key_ttls[key] = int(seconds)
        return True

    # -- awaitable commands --------------------------------------------
    async def zadd(self, key, mapping, xx=False):
        await self._gate()
        return self._zadd(key, mapping, xx=xx)

    async def zrem(self, key, *members):
        await self._gate()
        return self._zrem(key, *members)

    async def zcard(self, key):
        await self._gate()
        return self._zcard(key)

    async def zremrangebyscore(self, key, min, max):
        await self._gate()
        return self._zremrangebyscore(key, min, max)

    def pipeline(self, transaction=True):
        return FakePipeline(self)


class FakePipeline:
    """Queues commands and applies them together on ``execute``."""

    def __init__(self, redis: FakeAsyncRedis) -> None:
        self._redis = redis
        self._ops: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self._ops.clear()

    def _queue(self, fn, *args, **kwargs):
        self._ops.append((fn, args, kwargs))
        return self

    def zadd(self, key, mapping, xx=False):
        return self._queue(self._redis._zadd, key, mapping, xx=xx)

    def zrem(self, key, *members):
        return self._queue(self._redis._zrem, key, *members)

    def zcard(self, key):
        return self._queue(self._redis._zcard, key)

    def zremrangebyscore(self, key, min, max):
        return self._queue(self._redis._zremrangebyscore, key, min, max)

    def expire(self, key, seconds):
        return self._queue(self._redis._set_ttl, key, seconds)

    async def execute(self):
        await self._redis._gate()
        results = [fn(*args, **kwargs) for fn, args, kwargs in self._ops]
        self._ops.clear()
        if self._redis.hang_after_execute:
            await anyio.sleep_forever()
        return results
