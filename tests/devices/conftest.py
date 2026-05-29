"""Shared fixtures for device-broker tests.

The repo has no ``fakeredis`` dependency, so ``FakeRedis`` is a tiny
in-memory double covering only the commands ``DeviceBroker`` issues. It is
deliberately *not* faithful in several ways, so tests must not lean on them:
- blocking ops (``blpop`` / ``xread``) don't truly block — they return
  immediately (or after a tiny sleep) so tests stay fast;
- TTL is not modeled — ``set(ex=)`` and ``expire`` are no-ops, so expiry must
  be simulated by an explicit ``delete``;
- ``xadd`` trims to an EXACT ``maxlen`` and ignores ``approximate``, whereas
  real Redis with ``approximate=True`` only trims past a slack.
One ``FakeRedis`` shared by two ``DeviceBroker`` instances models two
processes (e.g. a Celery worker and the web tier) talking through one Redis.
"""

from __future__ import annotations

import threading
import time

import pytest

from application.devices.broker import DeviceBroker


def _b(value) -> bytes:
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


def _seq_of(entry_id) -> int:
    text = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
    try:
        return int(text.split("-", 1)[0])
    except (ValueError, IndexError):
        return 0


class FakeRedis:
    """In-memory stand-in for the redis-py commands the broker uses."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.kv: dict = {}
        self.lists: dict = {}
        self.hashes: dict = {}
        self.streams: dict = {}
        self._seq = 0

    # -- strings ------------------------------------------------------
    def get(self, key):
        with self._lock:
            return self.kv.get(key)

    def set(self, key, value, ex=None, nx=False):
        with self._lock:
            if nx and key in self.kv:
                return None
            self.kv[key] = _b(value)
            return True

    def delete(self, *keys):
        removed = 0
        with self._lock:
            for key in keys:
                for store in (self.kv, self.lists, self.hashes, self.streams):
                    if key in store:
                        del store[key]
                        removed += 1
        return removed

    def exists(self, key):
        with self._lock:
            present = (
                key in self.kv
                or key in self.hashes
                or key in self.lists
                or key in self.streams
            )
            return 1 if present else 0

    def expire(self, key, ttl):  # TTL is not simulated.
        return True

    # -- lists --------------------------------------------------------
    def llen(self, key):
        with self._lock:
            return len(self.lists.get(key, []))

    def rpush(self, key, *values):
        with self._lock:
            lst = self.lists.setdefault(key, [])
            lst.extend(_b(v) for v in values)
            return len(lst)

    def blpop(self, key, timeout=0):
        with self._lock:
            lst = self.lists.get(key)
            if lst:
                value = lst.pop(0)
                if not lst:
                    del self.lists[key]
                return (_b(key), value)
        return None

    def lrem(self, key, count, value):
        with self._lock:
            lst = self.lists.get(key)
            if not lst:
                return 0
            target = _b(value)
            kept = [item for item in lst if item != target]
            removed = len(lst) - len(kept)
            if kept:
                self.lists[key] = kept
            else:
                self.lists.pop(key, None)
            return removed

    # -- hashes -------------------------------------------------------
    def hset(self, key, field=None, value=None, mapping=None):
        with self._lock:
            h = self.hashes.setdefault(key, {})
            count = 0
            if mapping:
                for f, v in mapping.items():
                    h[f] = _b(v)
                    count += 1
            if field is not None:
                h[field] = _b(value)
                count += 1
            return count

    def hsetnx(self, key, field, value):
        with self._lock:
            h = self.hashes.setdefault(key, {})
            if field in h:
                return 0
            h[field] = _b(value)
            return 1

    def hget(self, key, field):
        with self._lock:
            return self.hashes.get(key, {}).get(field)

    def hgetall(self, key):
        with self._lock:
            return {_b(f): v for f, v in self.hashes.get(key, {}).items()}

    def hincrby(self, key, field, amount):
        with self._lock:
            h = self.hashes.setdefault(key, {})
            current = int(h.get(field, b"0"))
            current += int(amount)
            h[field] = _b(str(current))
            return current

    # -- streams ------------------------------------------------------
    def xadd(self, key, fields, maxlen=None, approximate=True):
        with self._lock:
            self._seq += 1
            entry_id = f"{self._seq}-0"
            entries = self.streams.setdefault(key, [])
            entries.append((entry_id, {_b(f): _b(v) for f, v in fields.items()}))
            if maxlen is not None and len(entries) > maxlen:
                del entries[: len(entries) - maxlen]
            return _b(entry_id)

    def xread(self, streams, count=None, block=None):
        if block:
            time.sleep(min(block / 1000.0, 0.02))
        out = []
        with self._lock:
            for key, last_id in streams.items():
                entries = self.streams.get(key, [])
                last_seq = _seq_of(last_id)
                fresh = [
                    (eid, fields)
                    for (eid, fields) in entries
                    if _seq_of(eid) > last_seq
                ]
                if count:
                    fresh = fresh[:count]
                if fresh:
                    out.append([_b(key), [(_b(eid), f) for eid, f in fresh]])
        return out or None


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def broker_env(monkeypatch, fake_redis):
    """A ``DeviceBroker`` wired to a fresh ``FakeRedis``; returns (broker, fake)."""
    monkeypatch.setattr(
        "application.devices.broker.get_redis_instance", lambda: fake_redis
    )
    return DeviceBroker(), fake_redis
