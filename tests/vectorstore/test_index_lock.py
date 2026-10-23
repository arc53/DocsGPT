"""Tests for ``source_index_lock``: one job at a time rewrites a source's index."""

import time

import pytest


class LockRedis:
    """The redis-py commands the lock uses (``set`` with nx/ex, ``eval`` of its two scripts), in memory.

    ``eval`` runs the lock's compare-and-act scripts atomically, as Redis
    does: renew (``expire``) or release (``del``) only while the key holds
    the caller's token.
    """

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

    def eval(self, script, numkeys, key, token, *args):
        if not self._alive(key) or self.kv[key] != token.encode():
            return 0
        if "'del'" in script:
            return self.delete(key)
        self.expiry[key] = time.time() + int(args[0])
        return 1


class RacingRedis(LockRedis):
    """A ``LockRedis`` where another job takes the lock right after any read of it.

    A holder that reads the key and then acts on it in a second command acts
    on the other job's lock; one that checks and acts in one script doesn't.
    """

    def __init__(self):
        super().__init__()
        self.armed = False
        self.taken = False

    def get(self, key):
        value = super().get(key)
        if self.armed:
            self.kv[key] = b"someone-else"
            self.expiry[key] = time.time() + 600
            self.taken = True
        return value

    def others_lock_survived(self, key):
        """True unless another job took the lock and lost it to this one."""
        return not self.taken or self.kv.get(key) == b"someone-else"


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

    def test_release_never_deletes_a_lock_taken_between_check_and_delete(self, monkeypatch):
        from docsgpt.vectorstore.index_lock import lock_key, source_index_lock

        redis = RacingRedis()
        monkeypatch.setattr("docsgpt.vectorstore.index_lock.get_redis_instance", lambda: redis)
        with source_index_lock("src-1", renew=False):
            redis.armed = True
        assert redis.others_lock_survived(lock_key("src-1"))

    def test_renewal_never_overwrites_a_lock_taken_between_check_and_set(self, monkeypatch):
        from docsgpt.vectorstore.index_lock import lock_key, source_index_lock

        redis = RacingRedis()
        monkeypatch.setattr("docsgpt.vectorstore.index_lock.get_redis_instance", lambda: redis)
        with source_index_lock("src-1", ttl_seconds=60, renew_seconds=0.05):
            redis.armed = True
            time.sleep(0.2)
            assert redis.others_lock_survived(lock_key("src-1"))

    def test_renewal_leaves_a_lock_another_job_holds(self, fake_redis):
        from docsgpt.vectorstore.index_lock import lock_key, source_index_lock

        with source_index_lock("src-1", ttl_seconds=60, renew_seconds=0.05):
            fake_redis.kv[lock_key("src-1")] = b"someone-else"
            time.sleep(0.2)
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


@pytest.mark.unit
class TestGraphExtractLock:
    """One graph extraction at a time per source, apart from the index lock."""

    def test_holds_its_own_key_and_releases_it(self, fake_redis):
        from docsgpt.vectorstore.index_lock import graph_extract_lock, graph_extract_lock_key, lock_key

        assert graph_extract_lock_key("src-1") == "docsgpt:graph_extract_lock:src-1"
        with graph_extract_lock("src-1"):
            assert fake_redis.get(graph_extract_lock_key("src-1")) is not None
            assert fake_redis.get(lock_key("src-1")) is None
        assert fake_redis.get(graph_extract_lock_key("src-1")) is None

    def test_a_second_extraction_waits_then_gives_up(self, fake_redis):
        from docsgpt.vectorstore.index_lock import SourceBusy, graph_extract_lock, source_index_lock

        with graph_extract_lock("src-1"):
            with pytest.raises(SourceBusy):
                with graph_extract_lock("src-1", wait_seconds=0.1, poll_seconds=0.05):
                    pass
            # A page change on the same source is not held up by an extraction.
            with source_index_lock("src-1", wait_seconds=0):
                pass

    def test_without_redis_the_block_runs_unlocked(self, monkeypatch):
        from docsgpt.vectorstore.index_lock import graph_extract_lock

        monkeypatch.setattr("docsgpt.vectorstore.index_lock.get_redis_instance", lambda: None)
        ran = []
        with graph_extract_lock("src-1"):
            ran.append(True)
        assert ran == [True]


@pytest.mark.unit
class TestTheWorkerWait:
    """A task waiting on the lock must give up before the broker redelivers it (acks_late)."""

    def test_the_default_wait_is_well_below_the_visibility_timeout(self):
        from docsgpt.core.settings import settings
        from docsgpt.vectorstore.index_lock import WORKER_WAIT_SECONDS

        assert 0 < WORKER_WAIT_SECONDS <= settings.CELERY_VISIBILITY_TIMEOUT / 2

    @pytest.mark.parametrize("visibility, wait", [(3600, 1800), (600, 300), (1, 0)])
    def test_the_wait_follows_the_visibility_timeout(self, visibility, wait):
        from docsgpt.vectorstore.index_lock import worker_wait_seconds

        assert worker_wait_seconds(visibility) == wait
