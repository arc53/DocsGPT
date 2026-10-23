"""Tests for ``source_index_lock``: one job at a time rewrites a source's index."""

import time

import pytest


class LockRedis:
    """The redis-py commands the lock uses (``set`` with nx/xx/ex, ``get``, ``delete``), in memory."""

    def __init__(self):
        self.kv = {}
        self.expiry = {}

    def _alive(self, key):
        deadline = self.expiry.get(key)
        if deadline is not None and deadline <= time.time():
            self.kv.pop(key, None)
            self.expiry.pop(key, None)
        return key in self.kv

    def set(self, key, value, nx=False, xx=False, ex=None):
        alive = self._alive(key)
        if (nx and alive) or (xx and not alive):
            return None
        self.kv[key] = value.encode() if isinstance(value, str) else value
        if ex is not None:
            self.expiry[key] = time.time() + ex
        return True

    def get(self, key):
        return self.kv.get(key) if self._alive(key) else None

    def delete(self, key):
        existed = self._alive(key)
        self.kv.pop(key, None)
        self.expiry.pop(key, None)
        return int(existed)


@pytest.fixture
def fake_redis(monkeypatch):
    redis = LockRedis()
    monkeypatch.setattr("docsgpt.vectorstore.index_lock.get_redis_instance", lambda: redis)
    return redis


@pytest.mark.unit
class TestSourceIndexLock:
    def test_holds_the_key_while_the_block_runs_and_releases_it(self, fake_redis):
        from docsgpt.vectorstore.index_lock import lock_key, source_index_lock

        with source_index_lock("src-1"):
            assert fake_redis.get(lock_key("src-1")) is not None
        assert fake_redis.get(lock_key("src-1")) is None

    def test_a_second_holder_waits_then_gives_up(self, fake_redis):
        from docsgpt.vectorstore.index_lock import SourceBusy, source_index_lock

        with source_index_lock("src-1"):
            started = time.monotonic()
            with pytest.raises(SourceBusy):
                with source_index_lock("src-1", wait_seconds=0.2, poll_seconds=0.05):
                    pass
            assert time.monotonic() - started >= 0.2
            # Another source is not held up.
            with source_index_lock("src-2", wait_seconds=0):
                pass

    def test_released_on_error(self, fake_redis):
        from docsgpt.vectorstore.index_lock import lock_key, source_index_lock

        with pytest.raises(RuntimeError):
            with source_index_lock("src-1"):
                raise RuntimeError("boom")
        assert fake_redis.get(lock_key("src-1")) is None

    def test_an_expired_lock_is_not_released_by_its_old_holder(self, fake_redis):
        # The holder ran past the expiry and another job took the lock; the
        # first one's release must leave the new holder's lock alone.
        from docsgpt.vectorstore.index_lock import lock_key, source_index_lock

        with source_index_lock("src-1", renew=False):
            fake_redis.kv[lock_key("src-1")] = b"someone-else"
        assert fake_redis.get(lock_key("src-1")) == b"someone-else"

    def test_the_lock_is_renewed_while_held(self, fake_redis):
        from docsgpt.vectorstore.index_lock import lock_key, source_index_lock

        with source_index_lock("src-1", ttl_seconds=1, renew_seconds=0.1):
            time.sleep(1.3)
            assert fake_redis.get(lock_key("src-1")) is not None

    def test_without_redis_the_block_runs_unlocked(self, monkeypatch):
        from docsgpt.vectorstore.index_lock import source_index_lock

        monkeypatch.setattr("docsgpt.vectorstore.index_lock.get_redis_instance", lambda: None)
        ran = []
        with source_index_lock("src-1"):
            ran.append(True)
        assert ran == [True]

    def test_a_redis_error_runs_the_block_unlocked(self, monkeypatch):
        from docsgpt.vectorstore.index_lock import source_index_lock

        class _Down:
            def set(self, *a, **k):
                raise ConnectionError("redis down")

        monkeypatch.setattr("docsgpt.vectorstore.index_lock.get_redis_instance", lambda: _Down())
        ran = []
        with source_index_lock("src-1"):
            ran.append(True)
        assert ran == [True]
