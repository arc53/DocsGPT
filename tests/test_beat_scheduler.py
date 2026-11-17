from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from celery import Celery
from celery.signals import beat_init
from celery.utils.imports import symbol_by_name
from redbeat.schedulers import RedBeatScheduler
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from redis.exceptions import LockError, LockNotOwnedError, MasterDownError, ReadOnlyError

from docsgpt import beat_scheduler
from docsgpt.beat_scheduler import DocsGPTScheduler, standby_seconds


# What Redis answers while it is down, failing over, or a replica has lost its primary.
REDIS_OUTAGES = [
    RedisConnectionError("Connection refused"),
    RedisTimeoutError("Timeout reading from socket"),
    ReadOnlyError("You can't write against a read only replica."),
    MasterDownError("MASTERDOWN Link with MASTER is down and replica-serve-stale-data is set to 'no'."),
]


class FakeRedis:
    """The one lock key, with an expiry on a clock the test moves."""

    def __init__(self):
        self.now = 0.0
        self.token = None
        self.expires_at = 0.0

    def holder(self):
        return self.token if self.now < self.expires_at else None


class FakeLock:
    """redis-py's Lock with RedBeat's extend script: extend sets the expiry, and fails once the lock is gone."""

    def __init__(self, redis, timeout):
        self.redis = redis
        self.timeout = timeout
        self.token = None

    def acquire(self, blocking=True):
        assert blocking is False, "beat must not wait for the lock"
        if self.redis.holder() is not None:
            return False
        self.token = object()
        self.redis.token = self.token
        self.redis.expires_at = self.redis.now + self.timeout
        return True

    def extend(self, seconds):
        if self.token is None:
            raise LockError("Cannot extend an unlocked lock")
        if self.redis.holder() is not self.token:
            raise LockNotOwnedError("Cannot extend a lock that's no longer owned")
        self.redis.expires_at = self.redis.now + seconds
        return True


@pytest.fixture
def redis():
    return FakeRedis()


class FakeSchedule:
    """RedBeat's sorted set of entries, as whole-second due times, for the one read the scheduler makes."""

    def __init__(self):
        self.due_at = []
        self.error = None

    def zrangebyscore(self, key, min, max, start=None, num=None, withscores=False):
        assert key == "redbeat:test::schedule" and (start, num, withscores) == (0, 1, True)
        if self.error:
            raise self.error
        after = float(min.removeprefix("("))
        later = sorted(score for score in self.due_at if score > after)
        return [("redbeat:test:entry", later[0])] if later else []


@pytest.fixture
def schedule(monkeypatch):
    fake = FakeSchedule()
    monkeypatch.setattr(beat_scheduler, "get_redis", lambda app: fake)
    return fake


@pytest.fixture
def scheduler(monkeypatch, redis, schedule):
    app = Celery("beat-test", set_as_current=False)
    app.conf.redbeat_key_prefix = "redbeat:test:"
    sched = DocsGPTScheduler(app, lazy=True, lock_timeout=90)
    monkeypatch.setattr(sched, "_new_lock", lambda: FakeLock(redis, sched.lock_timeout))
    # No entries: RedBeat's own tick then just extends the lock and returns max_interval.
    monkeypatch.setattr(RedBeatScheduler, "schedule", property(lambda self: {}))
    return sched


def _schedule_must_not_be_read(monkeypatch):
    def fail(self):
        raise AssertionError("a beat without the lock sent tasks")

    monkeypatch.setattr(RedBeatScheduler, "schedule", property(fail))


@pytest.mark.unit
def test_the_first_tick_takes_the_lock(scheduler, redis):
    assert scheduler.tick() == scheduler.max_interval
    assert scheduler.holding_lock
    assert redis.holder() is scheduler.lock.token


@pytest.mark.unit
def test_a_beat_paused_past_its_lock_timeout_takes_the_lock_back(scheduler, redis, caplog):
    scheduler.tick()
    redis.now += 600  # the Mac slept for ten minutes; the lock expired

    assert scheduler.tick() == scheduler.max_interval

    assert scheduler.holding_lock
    assert redis.holder() is scheduler.lock.token
    assert "Lost the scheduler lock" in caplog.text


@pytest.mark.unit
def test_a_beat_whose_lock_another_took_stands_by(scheduler, redis, monkeypatch):
    scheduler.tick()
    redis.now += 600
    other = FakeLock(redis, 90)
    assert other.acquire(blocking=False)
    _schedule_must_not_be_read(monkeypatch)

    assert scheduler.tick() == standby_seconds(90, scheduler.max_interval) == 15

    assert not scheduler.holding_lock
    assert redis.holder() is other.token


@pytest.mark.unit
def test_a_lock_left_by_a_dead_beat_is_taken_once_it_expires(scheduler, redis, monkeypatch):
    dead = FakeLock(redis, 90)
    dead.acquire(blocking=False)
    redis.now += 80

    _schedule_must_not_be_read(monkeypatch)
    assert scheduler.tick() == 15
    assert not scheduler.holding_lock

    redis.now += 15
    monkeypatch.setattr(RedBeatScheduler, "schedule", property(lambda self: {}))
    assert scheduler.tick() == scheduler.max_interval
    assert scheduler.holding_lock


@pytest.mark.unit
@pytest.mark.parametrize("outage", REDIS_OUTAGES, ids=lambda exc: type(exc).__name__)
def test_redis_going_away_during_a_tick_stands_by(scheduler, monkeypatch, outage):
    scheduler.tick()

    def down(seconds):
        raise outage

    monkeypatch.setattr(scheduler.lock, "extend", down)
    _schedule_must_not_be_read(monkeypatch)

    assert scheduler.tick() == 15
    assert scheduler.holding_lock  # kept: the next tick extends it, or finds it lost and takes it back


@pytest.mark.unit
@pytest.mark.parametrize("outage", REDIS_OUTAGES, ids=lambda exc: type(exc).__name__)
def test_redis_going_away_while_reading_the_schedule_stands_by(scheduler, monkeypatch, outage):
    scheduler.tick()
    reads = []

    def down(self):
        reads.append(1)
        raise outage

    monkeypatch.setattr(RedBeatScheduler, "schedule", property(down))

    assert scheduler.tick() == 15
    assert reads == [1]
    assert scheduler.holding_lock

    # Redis is back: the next tick schedules again.
    monkeypatch.setattr(RedBeatScheduler, "schedule", property(lambda self: {}))
    assert scheduler.tick() == scheduler.max_interval


@pytest.mark.unit
def test_a_read_only_replica_during_failover_stands_by(scheduler, redis, monkeypatch):
    def read_only(blocking=True):
        raise ReadOnlyError("You can't write against a read only replica.")

    lock = FakeLock(redis, 90)
    monkeypatch.setattr(lock, "acquire", read_only)
    monkeypatch.setattr(scheduler, "_new_lock", lambda: lock)

    assert scheduler.tick() == 15
    assert not scheduler.holding_lock


@pytest.mark.unit
@pytest.mark.parametrize("outage", REDIS_OUTAGES, ids=lambda exc: type(exc).__name__)
def test_setup_schedule_waits_for_redis(scheduler, monkeypatch, outage):
    calls = []

    def setup(self):
        calls.append(1)
        if len(calls) < 8:
            raise outage

    sleeps = []
    monkeypatch.setattr(RedBeatScheduler, "setup_schedule", setup)
    monkeypatch.setattr(scheduler, "sleep", sleeps.append)

    scheduler.setup_schedule()

    assert len(calls) == 8
    assert sleeps == [1, 2, 4, 8, 16, 30, 30]  # doubling, capped at STARTUP_RETRY_MAX_SECONDS


# 2026-11-16 07:37:13.25 UTC: prod's beat sent its two 5-minute tasks, slept 300 s past a task due 3 s later,
# and lost its 90 s lock (error-review ledger #91).
NOW = datetime(2026, 11, 16, 7, 37, 13, 250000, tzinfo=timezone.utc)


@pytest.mark.unit
def test_a_tick_never_sleeps_past_the_next_entry(scheduler, schedule, monkeypatch):
    # RedBeat looks one entry ahead. When that entry is itself due it is sent, and the only intervals left are
    # the sent entries' own: here max_interval, as with no entries.
    monkeypatch.setattr(scheduler.app, "now", lambda: NOW)
    schedule.due_at = [NOW.timestamp() + 600, int(NOW.timestamp()) + 3]

    assert scheduler.tick() == pytest.approx(2.75)


@pytest.mark.unit
def test_a_tick_keeps_redbeats_interval_when_nothing_is_due_sooner(scheduler, schedule, monkeypatch):
    monkeypatch.setattr(scheduler.app, "now", lambda: NOW)
    schedule.due_at = [NOW.timestamp() + 600]

    assert scheduler.tick() == scheduler.max_interval


@pytest.mark.unit
def test_an_entry_due_this_second_is_left_to_redbeat(scheduler, schedule, monkeypatch):
    # Scores are whole seconds. RedBeat already read everything up to this second, so only later ones count.
    monkeypatch.setattr(scheduler.app, "now", lambda: NOW)
    schedule.due_at = [int(NOW.timestamp()), int(NOW.timestamp()) - 3600]

    assert scheduler.tick() == scheduler.max_interval


@pytest.mark.unit
def test_an_entry_due_in_a_second_the_tick_crossed_is_not_slept_past(scheduler, schedule, monkeypatch):
    # RedBeat read the schedule at 13.25 s, so it saw neither this entry nor (it peeks at one) the one after.
    # Sending took until 14.75 s, past the entry's whole second.
    clock = {"now": NOW}
    monkeypatch.setattr(scheduler.app, "now", lambda: clock["now"])

    def read_schedule(self):
        clock["now"] = NOW + timedelta(seconds=1.5)
        return {}

    monkeypatch.setattr(RedBeatScheduler, "schedule", property(read_schedule))
    schedule.due_at = [NOW.timestamp() + 600, int(NOW.timestamp()) + 1]

    # Overdue already: tick again at once, which reads it as due.
    assert scheduler.tick() == 0.0
    # That tick started in the entry's second, so it does not count the entry again, even one RedBeat
    # found not quite due by its exact time (left in place here): no spinning on 0.
    assert scheduler.tick() == scheduler.max_interval


@pytest.mark.unit
@pytest.mark.parametrize("outage", REDIS_OUTAGES, ids=lambda exc: type(exc).__name__)
def test_redis_going_away_while_reading_the_next_entry_stands_by(scheduler, schedule, outage):
    scheduler.tick()
    schedule.error = outage

    assert scheduler.tick() == 15
    assert scheduler.holding_lock


@pytest.mark.unit
def test_beat_init_no_longer_waits_for_the_lock(monkeypatch):
    get_redis = MagicMock()
    monkeypatch.setattr("redbeat.schedulers.get_redis", get_redis)
    service = MagicMock()
    service.scheduler.lock_key = "redbeat:test::lock"

    beat_init.send(sender=service)

    get_redis.assert_not_called()


@pytest.mark.unit
def test_celery_runs_this_scheduler():
    from docsgpt import celeryconfig

    assert symbol_by_name(celeryconfig.beat_scheduler) is beat_scheduler.DocsGPTScheduler
