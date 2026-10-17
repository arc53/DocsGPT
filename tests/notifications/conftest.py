"""Fixtures for the notifications tests.

``FakeRedis`` covers only the hash and sorted-set commands presence uses
(the repo has no fakeredis dependency). TTLs are not modeled: presence keeps
its own timestamps, which is what the tests exercise.
"""

from __future__ import annotations

import pytest


class _Pipeline:
    def __init__(self, redis: "FakeRedis") -> None:
        self._redis = redis
        self._calls: list = []

    def __getattr__(self, name):
        def queue(*args, **kwargs):
            self._calls.append((name, args, kwargs))
            return self

        return queue

    def execute(self):
        return [getattr(self._redis, name)(*args, **kwargs) for name, args, kwargs in self._calls]


class FakeRedis:
    """In-memory hashes and sorted sets."""

    def __init__(self) -> None:
        self.hashes: dict = {}
        self.zsets: dict = {}
        self.expires: dict = {}
        self.fail = False

    def _check(self):
        if self.fail:
            raise ConnectionError("redis down")

    def pipeline(self, transaction=True):
        return _Pipeline(self)

    def hset(self, key, field, value):
        self._check()
        self.hashes.setdefault(key, {})[field.encode()] = value.encode()
        return 1

    def hgetall(self, key):
        self._check()
        return dict(self.hashes.get(key, {}))

    def hdel(self, key, *fields):
        self._check()
        bucket = self.hashes.get(key, {})
        removed = 0
        for field in fields:
            removed += bucket.pop(field.encode() if isinstance(field, str) else field, None) is not None
        return removed

    def hlen(self, key):
        self._check()
        return len(self.hashes.get(key, {}))

    def expire(self, key, seconds):
        self._check()
        self.expires[key] = seconds
        return True

    def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    def zcount(self, key, low, high):
        self._check()
        high_value = float("inf") if high == "+inf" else float(high)
        return sum(1 for score in self.zsets.get(key, {}).values() if float(low) <= score <= high_value)


@pytest.fixture()
def fake_redis(monkeypatch):
    """Point presence at an in-memory Redis."""
    redis = FakeRedis()
    monkeypatch.setattr("docsgpt.notifications.presence.get_redis_instance", lambda: redis)
    return redis
