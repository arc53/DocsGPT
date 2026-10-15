"""Shared fixtures for the Activity tests."""

from __future__ import annotations

import math
import time

import pytest


def _b(value) -> bytes:
    return value if isinstance(value, bytes) else str(value).encode("utf-8")


class FakeRedis:
    """In-memory stand-in for the redis-py commands the Activity flags use.

    The repo has no fakeredis dependency. Values come back as bytes, as from
    redis-py; a key past its expiry is gone.
    """

    def __init__(self) -> None:
        self.kv: dict = {}
        self.hashes: dict = {}
        self.expiry: dict = {}

    def _alive(self, key) -> bool:
        deadline = self.expiry.get(key)
        if deadline is not None and deadline <= time.time():
            self.kv.pop(key, None)
            self.hashes.pop(key, None)
            self.expiry.pop(key, None)
        return key in self.kv or key in self.hashes

    def set(self, key, value, ex=None):
        self.kv[key] = _b(value)
        self.hashes.pop(key, None)
        if ex is None:
            self.expiry.pop(key, None)
        else:
            self.expiry[key] = time.time() + ex
        return True

    def exists(self, key) -> int:
        return int(self._alive(key))

    def delete(self, *keys) -> int:
        removed = 0
        for key in keys:
            if self._alive(key):
                removed += 1
            self.kv.pop(key, None)
            self.hashes.pop(key, None)
            self.expiry.pop(key, None)
        return removed

    def ttl(self, key) -> int:
        if not self._alive(key):
            return -2
        deadline = self.expiry.get(key)
        return -1 if deadline is None else math.ceil(deadline - time.time())

    def expire(self, key, seconds) -> bool:
        if not self._alive(key):
            return False
        self.expiry[key] = time.time() + seconds
        return True

    def hset(self, key, field, value) -> int:
        self._alive(key)
        fields = self.hashes.setdefault(key, {})
        added = int(_b(field) not in fields)
        fields[_b(field)] = _b(value)
        return added

    def hdel(self, key, *fields) -> int:
        if not self._alive(key):
            return 0
        stored = self.hashes[key]
        removed = sum(1 for field in fields if stored.pop(_b(field), None) is not None)
        if not stored:
            self.delete(key)
        return removed

    def hgetall(self, key) -> dict:
        return dict(self.hashes.get(key, {})) if self._alive(key) else {}


@pytest.fixture
def redis(monkeypatch):
    """A ``FakeRedis`` behind both of the flags module's clients."""
    from docsgpt.activity import flags

    fake = FakeRedis()
    monkeypatch.setattr(flags, "get_redis_instance", lambda: fake)
    monkeypatch.setattr(flags, "_stop_redis", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _no_beat(monkeypatch):
    """Keep the snapshot and calendar off the real RedBeat: no sync times
    unless a test sets its own."""
    from docsgpt.activity import now, planned

    monkeypatch.setattr(now, "next_sync_times", lambda: {})
    monkeypatch.setattr(planned, "sync_schedule", lambda: {})
