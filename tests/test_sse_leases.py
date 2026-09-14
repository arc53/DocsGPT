"""Tests for ``docsgpt/streaming/sse_leases.py`` — the per-user SSE connection cap.

Each open stream holds its own lease in a sorted set scored by its last
refresh. A shared INCR/DECR counter with a TTL could expire under a stream
that outlived it, after which that stream's DECR took another stream's slot
or drove the count negative and the cap stopped holding.
"""

from __future__ import annotations

from types import SimpleNamespace

import anyio
import pytest

from docsgpt.streaming import sse_leases
from docsgpt.streaming.sse_leases import (
    StreamCapExceeded,
    acquire_stream_lease,
    hold_lease,
)
from tests.fake_async_redis import FakeAsyncRedis

KEY = "user:alice:sse_leases"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(sse_leases.settings, "SSE_MAX_CONCURRENT_PER_USER", 8)
    monkeypatch.setattr(sse_leases.settings, "SSE_KEEPALIVE_SECONDS", 15)


@pytest.fixture
def clock(monkeypatch):
    """Drive the module's wall and monotonic clocks by hand."""
    now = {"t": 1_000_000.0}
    fake_time = SimpleNamespace(time=lambda: now["t"], monotonic=lambda: now["t"])
    monkeypatch.setattr(sse_leases, "time", fake_time)
    return now


def _fill(redis: FakeAsyncRedis, count: int, score: float) -> None:
    redis.zsets[KEY] = {f"other-{i}": score for i in range(count)}


@pytest.mark.unit
def test_lease_ttl_outlasts_keepalive_gaps(monkeypatch):
    assert sse_leases.lease_ttl_seconds() == 60
    monkeypatch.setattr(sse_leases.settings, "SSE_KEEPALIVE_SECONDS", 30)
    # A stream yields at least every keepalive, so refreshing a third of the way
    # through the TTL always lands before expiry.
    assert sse_leases.lease_ttl_seconds() == 120


@pytest.mark.unit
@pytest.mark.asyncio
class TestAcquire:
    async def test_adds_own_lease_and_key_ttl(self, clock):
        redis = FakeAsyncRedis()
        lease = await acquire_stream_lease(redis, "alice")
        assert redis.zsets[KEY] == {lease.lease_id: clock["t"]}
        assert redis.key_ttls[KEY] == 60

    async def test_over_cap_raises_and_leaves_other_leases(self, clock):
        redis = FakeAsyncRedis()
        _fill(redis, 8, clock["t"])
        with pytest.raises(StreamCapExceeded):
            await acquire_stream_lease(redis, "alice")
        assert set(redis.zsets[KEY]) == {f"other-{i}" for i in range(8)}

    async def test_stale_leases_from_dead_streams_do_not_count(self, clock):
        redis = FakeAsyncRedis()
        _fill(redis, 8, clock["t"] - 61)
        lease = await acquire_stream_lease(redis, "alice")
        assert set(redis.zsets[KEY]) == {lease.lease_id}

    async def test_cap_disabled_takes_no_lease(self, monkeypatch):
        monkeypatch.setattr(sse_leases.settings, "SSE_MAX_CONCURRENT_PER_USER", 0)
        redis = FakeAsyncRedis()
        assert await acquire_stream_lease(redis, "alice") is None
        assert redis.zsets == {}

    async def test_no_redis_takes_no_lease(self):
        assert await acquire_stream_lease(None, "alice") is None

    async def test_redis_error_fails_open(self):
        redis = FakeAsyncRedis()
        redis.fail = ConnectionError("reset by peer")
        assert await acquire_stream_lease(redis, "alice") is None

    async def test_stalled_redis_fails_open_within_timeout(self, monkeypatch):
        monkeypatch.setattr(sse_leases, "ASYNC_REDIS_OP_TIMEOUT_SECONDS", 0.05)
        redis = FakeAsyncRedis()
        redis.hang = True
        with anyio.fail_after(2):
            assert await acquire_stream_lease(redis, "alice") is None

    async def test_timed_out_acquire_leaves_no_orphan_lease(self, monkeypatch):
        # EXEC ran on the server but its reply never arrived: the stream opens
        # without a lease, so the member it added must not keep counting.
        monkeypatch.setattr(sse_leases, "ASYNC_REDIS_OP_TIMEOUT_SECONDS", 0.05)
        redis = FakeAsyncRedis()
        redis.hang_after_execute = True
        with anyio.fail_after(2):
            assert await acquire_stream_lease(redis, "alice") is None
        assert redis.zsets == {}


@pytest.mark.unit
@pytest.mark.asyncio
class TestLeaseLifecycle:
    async def test_release_removes_only_its_own_lease(self, clock):
        redis = FakeAsyncRedis()
        first = await acquire_stream_lease(redis, "alice")
        second = await acquire_stream_lease(redis, "alice")
        await first.release()
        assert set(redis.zsets[KEY]) == {second.lease_id}
        # Releasing twice can't touch anyone else's slot either.
        await first.release()
        assert set(redis.zsets[KEY]) == {second.lease_id}

    async def test_release_is_bounded_when_redis_stalls(self, monkeypatch):
        monkeypatch.setattr(sse_leases, "ASYNC_REDIS_OP_TIMEOUT_SECONDS", 0.05)
        redis = FakeAsyncRedis()
        lease = await acquire_stream_lease(redis, "alice")
        redis.hang = True
        with anyio.fail_after(2):
            await lease.release()

    async def test_refresh_waits_a_third_of_the_ttl(self, clock):
        redis = FakeAsyncRedis()
        lease = await acquire_stream_lease(redis, "alice")
        start = clock["t"]
        clock["t"] += 19
        await lease.refresh_if_due()
        assert redis.zsets[KEY][lease.lease_id] == start
        clock["t"] += 1
        await lease.refresh_if_due()
        assert redis.zsets[KEY][lease.lease_id] == clock["t"]

    async def test_long_lived_stream_keeps_its_slot(self, clock):
        # The scenario a shared counter got wrong: a stream open far longer
        # than the TTL still counts, and newcomers can't exceed the cap.
        redis = FakeAsyncRedis()
        long_lived = await acquire_stream_lease(redis, "alice")
        for _ in range(30):  # 30 x 20s = 10 minutes, refreshing as it goes
            clock["t"] += 20
            await long_lived.refresh_if_due()
        _fill_others = {f"other-{i}": clock["t"] for i in range(7)}
        redis.zsets[KEY].update(_fill_others)
        with pytest.raises(StreamCapExceeded):
            await acquire_stream_lease(redis, "alice")
        await long_lived.release()
        assert long_lived.lease_id not in redis.zsets[KEY]
        assert len(redis.zsets[KEY]) == 7

    async def test_refresh_does_not_revive_a_pruned_lease(self, clock):
        # Refreshes failed past the TTL, a newer connect pruned the lease and
        # took the slot. Re-adding it would put the user over the cap.
        redis = FakeAsyncRedis()
        lease = await acquire_stream_lease(redis, "alice")
        redis.zsets[KEY].pop(lease.lease_id)
        _fill(redis, 8, clock["t"])
        clock["t"] += 30
        await lease.refresh_if_due()
        assert lease.lease_id not in redis.zsets[KEY]
        assert len(redis.zsets[KEY]) == 8

    async def test_refresh_does_not_undo_a_manual_clear(self, clock):
        redis = FakeAsyncRedis()
        lease = await acquire_stream_lease(redis, "alice")
        redis.zsets.clear()  # redis-cli DEL user:<id>:sse_leases
        clock["t"] += 30
        await lease.refresh_if_due()
        assert redis.zsets == {}

    async def test_refresh_failure_is_swallowed(self, clock):
        redis = FakeAsyncRedis()
        lease = await acquire_stream_lease(redis, "alice")
        redis.fail = ConnectionError("gone")
        clock["t"] += 30
        await lease.refresh_if_due()  # must not raise into the stream


@pytest.mark.unit
@pytest.mark.asyncio
class TestHoldLease:
    async def test_refreshes_between_frames_and_closes_inner_stream(self, clock):
        redis = FakeAsyncRedis()
        lease = await acquire_stream_lease(redis, "alice")
        state = {"closed": False}

        async def inner():
            try:
                for i in range(5):
                    clock["t"] += 25
                    yield f"frame-{i}"
            finally:
                state["closed"] = True

        wrapped = hold_lease(inner(), lease)
        assert await wrapped.__anext__() == "frame-0"
        assert redis.zsets[KEY][lease.lease_id] == clock["t"] - 25
        assert await wrapped.__anext__() == "frame-1"
        # Resuming after frame-0 refreshed the lease (25s > a third of the
        # TTL) before the inner stream produced frame-1 another 25s later.
        assert redis.zsets[KEY][lease.lease_id] == clock["t"] - 25
        await wrapped.aclose()
        assert state["closed"] is True

    async def test_passes_through_without_a_lease(self):
        async def inner():
            yield "a"
            yield "b"

        assert [item async for item in hold_lease(inner(), None)] == ["a", "b"]
