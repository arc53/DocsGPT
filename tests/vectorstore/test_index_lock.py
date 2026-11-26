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

    def pttl(self, key):
        if not self._alive(key):
            return -2
        deadline = self.expiry.get(key)
        return -1 if deadline is None else int((deadline - time.time()) * 1000)

    def exists(self, key):
        return int(self._alive(key))

    def delete(self, key):
        existed = self._alive(key)
        self.kv.pop(key, None)
        self.expiry.pop(key, None)
        return int(existed)

    def eval(self, script, numkeys, key, token, *args):
        if "'pttl'" in script:
            # The holder check: this TTL only while the value starts with the prefix, in one step.
            value = self.kv.get(key) if self._alive(key) else None
            if value is None or not value.startswith(token.encode()):
                return -3
            deadline = self.expiry.get(key)
            return -1 if deadline is None else int((deadline - time.time()) * 1000)
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


class _Down:
    """A Redis whose every command fails."""

    def set(self, *a, **k):
        raise ConnectionError("redis down")


def _use(monkeypatch, redis):
    monkeypatch.setattr("docsgpt.vectorstore.index_lock.get_redis_instance", lambda: redis)
    return redis


@pytest.fixture
def fake_redis(monkeypatch):
    return _use(monkeypatch, LockRedis())


@pytest.fixture
def no_renewal(monkeypatch):
    """The renewer never fires inside a test's block."""
    monkeypatch.setattr("docsgpt.vectorstore.index_lock._RENEW_SECONDS", 3600)


@pytest.fixture
def fast_renewal(monkeypatch):
    """A 1 s lock renewed every 0.05 s."""
    monkeypatch.setattr("docsgpt.vectorstore.index_lock._TTL_SECONDS", 1)
    monkeypatch.setattr("docsgpt.vectorstore.index_lock._RENEW_SECONDS", 0.05)


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

    def test_an_expired_lock_is_not_released_by_its_old_holder(self, fake_redis, no_renewal):
        # The holder ran past the expiry and another job took the lock; the
        # first one's release must leave the new holder's lock alone.
        from docsgpt.vectorstore.index_lock import lock_key, source_index_lock

        with source_index_lock("src-1"):
            fake_redis.kv[lock_key("src-1")] = b"someone-else"
        assert fake_redis.get(lock_key("src-1")) == b"someone-else"

    def test_release_never_deletes_a_lock_taken_between_check_and_delete(self, monkeypatch, no_renewal):
        from docsgpt.vectorstore.index_lock import lock_key, source_index_lock

        redis = _use(monkeypatch, RacingRedis())
        with source_index_lock("src-1"):
            redis.armed = True
        assert redis.others_lock_survived(lock_key("src-1"))

    def test_renewal_never_overwrites_a_lock_taken_between_check_and_set(self, monkeypatch, fast_renewal):
        from docsgpt.vectorstore.index_lock import lock_key, source_index_lock

        redis = _use(monkeypatch, RacingRedis())
        with source_index_lock("src-1"):
            redis.armed = True
            time.sleep(0.2)
            assert redis.others_lock_survived(lock_key("src-1"))

    def test_renewal_leaves_a_lock_another_job_holds(self, fake_redis, fast_renewal):
        from docsgpt.vectorstore.index_lock import lock_key, source_index_lock

        with source_index_lock("src-1"):
            fake_redis.kv[lock_key("src-1")] = b"someone-else"
            time.sleep(0.2)
            assert fake_redis.get(lock_key("src-1")) == b"someone-else"

    def test_the_lock_is_renewed_while_held(self, fake_redis, fast_renewal):
        from docsgpt.vectorstore.index_lock import lock_key, source_index_lock

        with source_index_lock("src-1"):
            time.sleep(1.3)
            assert fake_redis.get(lock_key("src-1")) is not None

    @pytest.mark.parametrize("lock_name", ["source_index_lock", "graph_extract_lock"])
    @pytest.mark.parametrize("redis", [None, _Down()], ids=["no-redis", "redis-down"])
    def test_without_a_working_redis_the_block_runs_unlocked(self, monkeypatch, lock_name, redis):
        from docsgpt.vectorstore import index_lock

        _use(monkeypatch, redis)
        ran = []
        with getattr(index_lock, lock_name)("src-1"):
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


@pytest.mark.unit
class TestTheWorkerWait:
    """A task waiting on the lock must give up before the broker redelivers it (acks_late)."""

    def test_the_default_wait_is_well_below_the_visibility_timeout(self):
        from docsgpt.core.settings import settings
        from docsgpt.vectorstore.index_lock import WORKER_WAIT_SECONDS

        assert WORKER_WAIT_SECONDS == settings.CELERY_VISIBILITY_TIMEOUT // 2 > 0


@pytest.mark.unit
class TestConnectionFetchLock:
    """One fetch at a time per connection, so parallel ingests can't share out its API budget."""

    def test_holds_its_own_key_and_releases_it(self, fake_redis):
        from docsgpt.vectorstore.index_lock import connection_fetch_lock, connection_fetch_lock_key

        assert connection_fetch_lock_key("c-1") == "docsgpt:connection_fetch_lock:c-1"
        with connection_fetch_lock("c-1"):
            assert fake_redis.get(connection_fetch_lock_key("c-1")) is not None
        assert fake_redis.get(connection_fetch_lock_key("c-1")) is None

    def test_a_second_fetch_waits_then_gives_up_naming_the_connection(self, fake_redis):
        from docsgpt.vectorstore.index_lock import SourceBusy, connection_fetch_lock

        with connection_fetch_lock("c-1"):
            with pytest.raises(SourceBusy, match="connection"):
                with connection_fetch_lock("c-1", wait_seconds=0.1, poll_seconds=0.05):
                    pass
            # Another connection is not held up.
            with connection_fetch_lock("c-2", wait_seconds=0):
                pass


@pytest.mark.unit
class TestARedeliveredJobDoesNotWait:
    """A task redelivered while its first delivery still holds the lock gives up at once, not after the wait."""

    def test_the_lock_names_its_holder(self, fake_redis):
        from docsgpt.vectorstore.index_lock import lock_key, source_index_lock

        with source_index_lock("src-1", holder="task-1"):
            assert fake_redis.get(lock_key("src-1")).decode().startswith("task-1|")

    def test_a_copy_of_the_running_job_gives_up_once_it_sees_the_lock_renewed(self, fake_redis, fast_renewal):
        from docsgpt.vectorstore.index_lock import SameJobRunning, source_index_lock

        with source_index_lock("src-1", holder="task-1"):
            started = time.monotonic()
            with pytest.raises(SameJobRunning):
                with source_index_lock("src-1", wait_seconds=30, poll_seconds=0.02, holder="task-1"):
                    pass
            assert time.monotonic() - started < 5

    def test_a_copy_of_a_dead_job_takes_the_lock_once_it_lapses(self, fake_redis, fast_renewal):
        # The first delivery died holding the lock: nothing renews it, so it lapses and the copy runs.
        from docsgpt.vectorstore.index_lock import lock_key, source_index_lock

        fake_redis.set(lock_key("src-1"), "task-1|dead", nx=True, ex=0.3)
        ran = []
        with source_index_lock("src-1", wait_seconds=5, poll_seconds=0.02, holder="task-1"):
            ran.append(True)
        assert ran == [True]

    def test_another_job_is_waited_for_as_before(self, fake_redis, fast_renewal):
        from docsgpt.vectorstore.index_lock import SameJobRunning, SourceBusy, source_index_lock

        with source_index_lock("src-1", holder="task-1"):
            started = time.monotonic()
            with pytest.raises(SourceBusy) as raised:
                with source_index_lock("src-1", wait_seconds=0.3, poll_seconds=0.02, holder="task-2"):
                    pass
            assert not isinstance(raised.value, SameJobRunning)
            assert time.monotonic() - started >= 0.3

    def test_a_job_without_a_holder_is_never_taken_for_a_copy(self, fake_redis, fast_renewal):
        from docsgpt.vectorstore.index_lock import SameJobRunning, SourceBusy, source_index_lock

        with source_index_lock("src-1"):
            with pytest.raises(SourceBusy) as raised:
                with source_index_lock("src-1", wait_seconds=0.2, poll_seconds=0.02):
                    pass
            assert not isinstance(raised.value, SameJobRunning)

    def test_a_redis_error_while_checking_the_holder_keeps_waiting(self, monkeypatch, fast_renewal):
        from docsgpt.vectorstore.index_lock import SameJobRunning, SourceBusy, source_index_lock

        class BrokenReads(LockRedis):
            def eval(self, script, *args):
                if "'pttl'" in script:
                    raise ConnectionError("redis blip")
                return super().eval(script, *args)

        _use(monkeypatch, BrokenReads())
        with source_index_lock("src-1", holder="task-1"):
            with pytest.raises(SourceBusy) as raised:
                with source_index_lock("src-1", wait_seconds=0.2, poll_seconds=0.02, holder="task-1"):
                    pass
            assert not isinstance(raised.value, SameJobRunning)


@pytest.mark.unit
class TestFinishedJobs:
    """A job that finished is remembered by its task id, so a redelivered copy of it doesn't run again."""

    def test_a_finished_job_is_remembered_for_a_day(self, fake_redis):
        from docsgpt.vectorstore.index_lock import FINISHED_JOB_TTL_SECONDS, job_finished, record_job_finished

        assert job_finished("task-1") is False
        record_job_finished("task-1")
        assert job_finished("task-1") is True
        assert job_finished("task-2") is False
        assert FINISHED_JOB_TTL_SECONDS == 86400
        assert fake_redis.pttl("docsgpt:finished_job:task-1") > 86000 * 1000

    @pytest.mark.parametrize("redis", [None, _Down()], ids=["no-redis", "redis-down"])
    def test_without_a_working_redis_nothing_is_remembered(self, monkeypatch, redis):
        from docsgpt.vectorstore.index_lock import job_finished, record_job_finished

        _use(monkeypatch, redis)
        record_job_finished("task-1")
        assert job_finished("task-1") is False

    def test_no_task_id_is_never_finished(self, fake_redis):
        from docsgpt.vectorstore.index_lock import job_finished, record_job_finished

        record_job_finished(None)
        assert job_finished(None) is False
        assert fake_redis.kv == {}


@pytest.mark.unit
class TestOwnTtl:
    def test_a_lock_gone_or_held_by_another_job_is_not_its_own(self, fake_redis):
        from docsgpt.vectorstore.index_lock import _own_ttl, lock_key

        key = lock_key("src-1")
        assert _own_ttl(fake_redis, key, "task-1") is None
        fake_redis.set(key, "task-2|x", nx=True, ex=600)
        assert _own_ttl(fake_redis, key, "task-1") is None
        assert _own_ttl(fake_redis, key, None) is None

    def test_its_own_lock_reports_its_ttl(self, fake_redis):
        from docsgpt.vectorstore.index_lock import _own_ttl, lock_key

        key = lock_key("src-1")
        fake_redis.set(key, "task-1|x", nx=True, ex=600)
        assert 0 < _own_ttl(fake_redis, key, "task-1") <= 600_000
        # A holder whose id only starts the same is someone else.
        assert _own_ttl(fake_redis, key, "task") is None

    def test_the_holder_and_its_ttl_are_read_in_one_step(self, fake_redis):
        # Two commands could read this job's value, then another job's TTL after a handover.
        from docsgpt.vectorstore.index_lock import _own_ttl, lock_key

        key = lock_key("src-1")
        fake_redis.set(key, "task-1|x", nx=True, ex=600)
        fake_redis.get = fake_redis.pttl = None  # only the script may read it
        assert 0 < _own_ttl(fake_redis, key, "task-1") <= 600_000
