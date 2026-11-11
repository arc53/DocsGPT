"""The per-user cap on running whole-source ingests (``INGEST_MAX_CONCURRENT_PER_USER``)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from celery.exceptions import Retry

from docsgpt.api.user import ingest_slots
from docsgpt.core.settings import settings


class FakeRedis:
    """The sorted-set commands the slots use; fakeredis is not a test dependency."""

    def __init__(self) -> None:
        self.sets: dict = {}

    def zadd(self, key, mapping, xx=False):
        members = self.sets.setdefault(key, {})
        added = 0
        for member, score in mapping.items():
            if xx and member not in members:
                continue
            added += member not in members
            members[member] = float(score)
        return added

    def zremrangebyscore(self, key, low, high):
        members = self.sets.get(key, {})
        top = float(high)
        gone = [m for m, score in members.items() if score <= top]
        for member in gone:
            del members[member]
        return len(gone)

    def zcard(self, key):
        return len(self.sets.get(key, {}))

    def zscore(self, key, member):
        return self.sets.get(key, {}).get(member)

    def zrem(self, key, member):
        return 1 if self.sets.get(key, {}).pop(member, None) is not None else 0

    def expire(self, key, seconds):
        return key in self.sets

    def exists(self, key):
        return int(bool(self.sets.get(key)))

    def pipeline(self, transaction=True):
        return _Pipeline(self)


class _Pipeline:
    def __init__(self, client) -> None:
        self.client = client
        self.calls: list = []

    def __getattr__(self, name):
        def _queue(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self

        return _queue

    def execute(self):
        return [getattr(self.client, name)(*args, **kwargs) for name, args, kwargs in self.calls]


@pytest.fixture
def redis(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(ingest_slots, "get_redis_instance", lambda: client)
    return client


@pytest.fixture
def cap(monkeypatch):
    def _set(value: int) -> None:
        monkeypatch.setattr(settings, "INGEST_MAX_CONCURRENT_PER_USER", value)

    _set(1)
    return _set


@pytest.fixture
def requeued(monkeypatch) -> list:
    """Every deferral: ``(task id, countdown)``."""
    calls: list = []
    monkeypatch.setattr(ingest_slots, "_requeue", lambda task, countdown: calls.append((task.request.id, countdown)))
    return calls


@pytest.fixture
def heartbeats(monkeypatch) -> list:
    beats: list = []
    monkeypatch.setattr(ingest_slots, "_keep_progress_alive", lambda source_id: beats.append(source_id))
    return beats


def _task(task_id: str) -> SimpleNamespace:
    """A bound-task stand-in running from the broker (not called directly)."""
    return SimpleNamespace(request=SimpleNamespace(id=task_id, called_directly=False, is_eager=False, retries=0))


def _body(calls: list, inner=None):
    @ingest_slots.with_ingest_slot
    def body(self, source_id=None, user=None, idempotency_key=None):
        calls.append(self.request.id)
        return inner(self) if inner else {"ok": True}

    return body


@pytest.mark.unit
class TestIngestSlots:
    def test_a_users_second_ingest_is_deferred_when_the_cap_is_one(self, redis, cap, requeued, heartbeats):
        ran: list = []

        def second_ingest(_self):
            with pytest.raises(Retry):
                _body(ran)(_task("t2"), source_id="s2", user="alice")
            return {"ok": True}

        _body(ran, inner=second_ingest)(_task("t1"), source_id="s1", user="alice")

        assert ran == ["t1"]
        assert [task_id for task_id, _ in requeued] == ["t2"]
        countdown = requeued[0][1]
        assert ingest_slots.DEFER_SECONDS <= countdown <= ingest_slots.DEFER_SECONDS + ingest_slots.DEFER_JITTER_SECONDS
        # A deferred resume keeps its progress row fresh, so the reconciler doesn't resume it again.
        assert heartbeats == ["s2"]

    def test_another_users_ingest_runs(self, redis, cap, requeued):
        ran: list = []

        def other_user(_self):
            _body(ran)(_task("t2"), user="bob")
            return {"ok": True}

        _body(ran, inner=other_user)(_task("t1"), user="alice")

        assert ran == ["t1", "t2"]
        assert requeued == []

    def test_the_slot_is_given_back_when_the_task_ends_or_raises(self, redis, cap, requeued):
        ran: list = []

        def boom(_self):
            raise RuntimeError("embed failed")

        with pytest.raises(RuntimeError):
            _body(ran, inner=boom)(_task("t1"), user="alice")
        _body(ran)(_task("t2"), user="alice")

        assert ran == ["t1", "t2"]
        assert requeued == []
        assert redis.zcard(ingest_slots.slots_key("alice")) == 0

    def test_a_killed_workers_slot_frees_itself(self, redis, cap, requeued, monkeypatch):
        # Held by a task whose worker died: never renewed, never released.
        redis.zadd(ingest_slots.slots_key("alice"), {"dead": 1_000.0})
        monkeypatch.setattr(ingest_slots.time, "time", lambda: 1_000.0 + ingest_slots.SLOT_TTL_SECONDS + 1)
        ran: list = []

        _body(ran)(_task("t1"), user="alice")

        assert ran == ["t1"]
        assert requeued == []

    def test_a_redelivered_task_keeps_its_own_slot(self, redis, cap, requeued):
        redis.zadd(ingest_slots.slots_key("alice"), {"t1": ingest_slots.time.time()})
        ran: list = []

        _body(ran)(_task("t1"), user="alice")

        assert ran == ["t1"]

    def test_the_slot_is_renewed_while_the_task_runs(self, redis, cap, requeued, monkeypatch):
        monkeypatch.setattr(ingest_slots, "SLOT_RENEW_SECONDS", 0.01)
        scores: list = []

        def slow(_self):
            first = redis.zscore(ingest_slots.slots_key("alice"), "t1")
            ingest_slots.time.sleep(0.1)
            scores.extend([first, redis.zscore(ingest_slots.slots_key("alice"), "t1")])
            return {"ok": True}

        _body([], inner=slow)(_task("t1"), user="alice")

        assert scores[1] > scores[0]

    @pytest.mark.parametrize("value", [0])
    def test_zero_disables_the_cap(self, redis, cap, requeued, value):
        cap(value)
        ran: list = []

        def nested(_self):
            _body(ran)(_task("t2"), user="alice")
            return {"ok": True}

        _body(ran, inner=nested)(_task("t1"), user="alice")

        assert ran == ["t1", "t2"]
        assert redis.exists(ingest_slots.slots_key("alice")) == 0

    def test_no_redis_runs_every_task(self, cap, requeued, monkeypatch):
        monkeypatch.setattr(ingest_slots, "get_redis_instance", lambda: None)
        ran: list = []

        _body(ran)(_task("t1"), user="alice")

        assert ran == ["t1"]

    def test_a_direct_call_is_not_gated(self, redis, cap, requeued):
        ran: list = []
        task = _task("t1")
        task.request.called_directly = True
        redis.zadd(ingest_slots.slots_key("alice"), {"other": ingest_slots.time.time()})

        _body(ran)(task, user="alice")

        assert ran == ["t1"]


@pytest.mark.unit
class TestDeferralSkipsTheIdempotencyGuard:
    def test_a_deferred_ingest_claims_no_lease_and_spends_no_attempt(self, redis, cap, requeued, monkeypatch):
        """The guard counts attempts for the poison check; waiting for a slot is not an attempt."""
        from docsgpt.api.user import idempotency, tasks

        claims = MagicMock(return_value=1)
        monkeypatch.setattr(idempotency, "_try_claim_lease", claims)
        monkeypatch.setattr(ingest_slots, "_keep_progress_alive", lambda source_id: None)
        redis.zadd(ingest_slots.slots_key("alice"), {"running": ingest_slots.time.time()})

        task = tasks.ingest_remote
        task.push_request(id="t2", called_directly=False, is_eager=False, retries=0)
        try:
            with pytest.raises(Retry):
                task.run(
                    source_data="https://github.com/x/y", job_name="g", user="alice", loader="github",
                    idempotency_key="alice:k", source_id="00000000-0000-0000-0000-000000000001",
                )
        finally:
            task.pop_request()

        claims.assert_not_called()
        assert requeued == [("t2", requeued[0][1])]

    def test_every_whole_source_ingest_task_is_gated(self):
        from docsgpt.api.user import tasks

        for task in (
            tasks.ingest, tasks.ingest_remote, tasks.ingest_connector_task, tasks.reingest_source_task,
            tasks.sync_source,
        ):
            assert getattr(task.run, "_ingest_slot_gated", False), task.name


@pytest.mark.unit
class TestRequeue:
    def test_the_task_goes_back_on_its_queue_without_spending_a_retry(self):
        task = MagicMock()
        task.request.retries = 2

        ingest_slots._requeue(task, 37)

        task.signature_from_request.assert_called_once_with(task.request, countdown=37, retries=2)
        task.signature_from_request.return_value.apply_async.assert_called_once_with()
