"""The shared last-use stamp of sandbox sessions (docsgpt/sandbox/activity.py)."""

import pytest

from docsgpt.sandbox import activity
from docsgpt.sandbox.activity import SharedActivity


class _FakeRedis:
    def __init__(self) -> None:
        self.store = {}
        self.sets = 0

    def set(self, key, value, ex=None):
        self.sets += 1
        self.store[key] = value.encode()

    def get(self, key):
        return self.store.get(key)


class _DownRedis:
    def set(self, *a, **k):
        raise ConnectionError("redis down")

    def get(self, *a, **k):
        raise ConnectionError("redis down")


@pytest.fixture()
def clocks(monkeypatch):
    now = {"wall": 1_000_000.0, "mono": 50.0}
    monkeypatch.setattr(activity.time, "time", lambda: now["wall"])
    monkeypatch.setattr(activity.time, "monotonic", lambda: now["mono"])
    return now


def test_a_touch_is_read_back_by_any_process(clocks):
    redis = _FakeRedis()
    SharedActivity(lambda: redis).touch("conv")
    clocks["wall"] += 300
    assert SharedActivity(lambda: redis).idle_seconds("conv") == pytest.approx(300)


def test_every_touch_is_written(clocks):
    # A skipped write would make the stamp older than the last use, and an
    # overstated idle time is what deletes a sandbox another process uses.
    redis = _FakeRedis()
    shared = SharedActivity(lambda: redis)
    shared.touch("conv")
    shared.touch("conv")
    assert redis.sets == 2


def test_an_unknown_session_or_no_redis_reads_as_unknown(clocks):
    assert SharedActivity(lambda: _FakeRedis()).idle_seconds("conv") is None
    assert SharedActivity(lambda: None).idle_seconds("conv") is None
    SharedActivity(lambda: None).touch("conv")  # no Redis configured: a no-op


def test_a_redis_outage_never_raises_and_backs_off(clocks):
    calls = {"n": 0}

    def _getter():
        calls["n"] += 1
        return _DownRedis()

    shared = SharedActivity(_getter)
    shared.touch("conv")
    assert shared.idle_seconds("conv") is None
    shared.touch("conv")
    assert calls["n"] == 1  # no connect timeout on every op while Redis is down
    clocks["mono"] += 31
    shared.touch("conv")
    assert calls["n"] == 2


def test_a_garbled_stamp_reads_as_unknown(clocks):
    redis = _FakeRedis()
    redis.store["sandbox:last_access:conv"] = b"not a number"
    assert SharedActivity(lambda: redis).idle_seconds("conv") is None


def test_shared_activity_is_one_per_process():
    assert activity.shared_activity() is activity.shared_activity()
