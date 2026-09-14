"""Tests for docsgpt/api/events/routes.py — the native-async ``GET /api/events``.

The route is a Starlette endpoint served on the event loop. Tests drive it
through Starlette's ``TestClient`` with the async Redis client faked
(``tests/fake_async_redis.py``: real sorted sets for connection leases, mocks
for streams) and ``AsyncTopic.subscribe`` replaced. Fake subscriptions end
after a few frames so the stream finishes and the client returns the body; a
mid-stream client disconnect and the shutdown path go through
``tests/asgi_stream.py``.
"""

from __future__ import annotations

import inspect
import json
import time
from typing import Any, Callable, Optional
from unittest.mock import AsyncMock, patch

import anyio
import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from docsgpt.api.events import routes as events_module
from docsgpt.cache import PUBSUB_SOCKET_TIMEOUT_SECONDS
from docsgpt.core.shutdown import begin_shutdown, reset_shutdown
from tests.asgi_stream import stream_then_disconnect
from tests.fake_async_redis import FakeAsyncRedis

_AUTH = "docsgpt.api.asgi_auth.handle_auth"
_AREDIS = "docsgpt.api.events.routes.get_async_redis_instance"
_SUBSCRIBE = "docsgpt.api.events.routes.AsyncTopic.subscribe"
_LEASES = "user:alice:sse_leases"
ALICE = {"sub": "alice"}
OLD_CURSOR = "1735682300000-0"


def _app() -> Starlette:
    return Starlette(routes=events_module.event_stream_routes)


def _get(headers: dict | None = None, params: dict | None = None):
    return TestClient(_app()).get("/api/events", headers=headers or {}, params=params or {})


def _redis() -> FakeAsyncRedis:
    return FakeAsyncRedis()


def _subscribe(
    *payloads: Any,
    fire_callback: bool = True,
    record: dict | None = None,
    probe: Optional[Callable[[], None]] = None,
):
    """``AsyncTopic.subscribe`` stand-in: ack, one idle tick, the payloads, then end."""

    async def _impl(self, on_subscribe=None, poll_timeout=1.0, **kwargs):
        if record is not None:
            record.update(kwargs, poll_timeout=poll_timeout, topic=self.name)
        if probe is not None:
            probe()
        if fire_callback and on_subscribe is not None:
            result = on_subscribe()
            if inspect.isawaitable(result):
                await result
        yield None
        for payload in payloads:
            yield payload

    return _impl


def _subscribe_dies_after_callback():
    """SUBSCRIBE acks and the callback runs, then the connection drops before any poll."""

    async def _impl(self, on_subscribe=None, poll_timeout=1.0, **kwargs):
        if on_subscribe is not None:
            result = on_subscribe()
            if inspect.isawaitable(result):
                await result
        return
        yield  # pragma: no cover — make the function an async generator

    return _impl


def _endless_subscribe(state: dict):
    """A subscription that idles until cancelled; records its own teardown."""

    async def _impl(self, on_subscribe=None, poll_timeout=1.0, **kwargs):
        if on_subscribe is not None:
            result = on_subscribe()
            if inspect.isawaitable(result):
                await result
        try:
            while True:
                await anyio.sleep(0.01)
                yield None
        finally:
            state["closed"] = True

    return _impl


def _stored(payload: dict) -> bytes:
    return json.dumps(payload).encode()


@pytest.fixture(autouse=True)
def _baseline(monkeypatch):
    """Hermetic defaults: push on, cap 8, no async Redis, clean shutdown flag."""
    monkeypatch.setattr(events_module.settings, "AUTH_TYPE", None)
    monkeypatch.setattr(events_module.settings, "ENABLE_SSE_PUSH", True)
    monkeypatch.setattr(events_module.settings, "SSE_MAX_CONCURRENT_PER_USER", 8)
    monkeypatch.setattr(events_module.settings, "SSE_KEEPALIVE_SECONDS", 15)
    monkeypatch.setattr(events_module.settings, "EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW", 30)
    monkeypatch.setattr(events_module.settings, "EVENTS_REPLAY_BUDGET_WINDOW_SECONDS", 60)
    monkeypatch.setattr(events_module.settings, "EVENTS_REPLAY_MAX_AGE_HOURS", 0)
    monkeypatch.setattr(events_module.settings, "EVENTS_REPLAY_MAX_PER_REQUEST", 200)
    monkeypatch.setattr(
        "docsgpt.streaming.async_broadcast_channel.get_async_redis_instance",
        AsyncMock(return_value=None),
    )
    reset_shutdown()
    with patch(_AREDIS, AsyncMock(return_value=None)):
        yield
    reset_shutdown()


# ── auth gate ───────────────────────────────────────────────────────────


@pytest.mark.unit
class TestAuthGate:
    def test_401_when_no_token(self):
        with patch(_AUTH, return_value=None):
            r = _get()
        assert r.status_code == 401
        assert r.json() == {"success": False, "message": "Authentication required"}

    def test_401_when_token_has_no_sub(self):
        with patch(_AUTH, return_value={"email": "x@y.z"}):
            r = _get()
        assert r.status_code == 401

    def test_401_passes_decoder_error_through(self):
        err = {"message": "Authentication error: token expired", "error": "token_expired"}
        with patch(_AUTH, return_value=err):
            r = _get()
        assert r.status_code == 401
        assert r.json() == err

    def test_401_when_oidc_session_revoked(self, monkeypatch):
        monkeypatch.setattr(events_module.settings, "AUTH_TYPE", "oidc")
        with patch(_AUTH, return_value={"sub": "alice", "iat": 1}), patch(
            "docsgpt.api.asgi_auth.oidc_session_denied", return_value=True
        ):
            r = _get()
        assert r.status_code == 401
        assert r.json()["error"] == "token_revoked"


# ── streaming response shape ────────────────────────────────────────────


@pytest.mark.unit
class TestStreamShape:
    def test_event_stream_headers_and_prelude(self):
        with patch(_AUTH, return_value=ALICE):
            r = _get()
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["x-accel-buffering"] == "no"
        assert r.headers["x-sse-transport"] == "async"
        assert r.text.startswith(": connected\n\n")

    def test_push_disabled_skips_redis_entirely(self, monkeypatch):
        monkeypatch.setattr(events_module.settings, "ENABLE_SSE_PUSH", False)
        redis = _redis()
        with patch(_AUTH, return_value=ALICE), patch(_AREDIS, AsyncMock(return_value=redis)):
            r = _get()
        assert r.status_code == 200
        assert r.text == ": connected\n\n: push_disabled\n\n"
        redis.incr.assert_not_awaited()
        assert redis.zsets == {}

    def test_subscribes_to_user_topic_with_liveness_probe(self):
        record: dict = {}
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=_redis())
        ), patch(_SUBSCRIBE, _subscribe(record=record)):
            _get()
        assert record["topic"] == "user:alice"
        assert record["poll_timeout"] == events_module.SUBSCRIBE_POLL_INTERVAL_SECONDS
        assert record["liveness_timeout"] == PUBSUB_SOCKET_TIMEOUT_SECONDS

    def test_keepalive_emitted_on_idle_ticks(self, monkeypatch):
        monkeypatch.setattr(events_module.settings, "SSE_KEEPALIVE_SECONDS", 0)
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=_redis())
        ), patch(_SUBSCRIBE, _subscribe()):
            r = _get()
        assert ": keepalive\n\n" in r.text


# ── concurrency cap (per-connection leases) ─────────────────────────────


@pytest.mark.unit
class TestConcurrencyCap:
    def test_429_when_user_already_holds_the_cap(self):
        redis = _redis()
        redis.zsets[_LEASES] = {f"tab-{i}": time.time() for i in range(8)}
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ), patch(_SUBSCRIBE, _subscribe()):
            r = _get()
        assert r.status_code == 429
        assert r.json() == {"success": False, "message": "Too many concurrent SSE connections"}
        # The rejected attempt removed its own lease and nobody else's.
        assert set(redis.zsets[_LEASES]) == {f"tab-{i}" for i in range(8)}

    def test_leases_left_by_dead_streams_age_out(self):
        redis = _redis()
        redis.zsets[_LEASES] = {f"crashed-{i}": time.time() - 3600 for i in range(8)}
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ), patch(_SUBSCRIBE, _subscribe()):
            r = _get()
        assert r.status_code == 200
        assert redis.zsets == {}

    def test_cap_disabled_takes_no_lease(self, monkeypatch):
        monkeypatch.setattr(events_module.settings, "SSE_MAX_CONCURRENT_PER_USER", 0)
        redis = _redis()
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ), patch(_SUBSCRIBE, _subscribe()):
            r = _get()
        assert r.status_code == 200
        assert redis.zsets == {}

    def test_redis_errors_fail_open(self):
        redis = _redis()
        redis.fail = ConnectionError("reset by peer")
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ), patch(_SUBSCRIBE, _subscribe()):
            r = _get()
        assert r.status_code == 200

    def test_lease_held_while_streaming_and_released_at_end(self):
        redis = _redis()
        seen: dict = {}

        def _count_leases():
            seen["during"] = len(redis.zsets.get(_LEASES, {}))

        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ), patch(_SUBSCRIBE, _subscribe(probe=_count_leases)):
            r = _get()
        assert r.status_code == 200
        assert seen["during"] == 1
        assert redis.zsets == {}

    def test_redis_unavailable_serves_stream_without_cap(self):
        with patch(_AUTH, return_value=ALICE):
            r = _get()
        assert r.status_code == 200
        assert r.text.startswith(": connected")


# ── disconnect and shutdown (raw ASGI) ──────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
class TestStreamLifecycle:
    async def test_client_disconnect_releases_lease_and_closes_subscription(self, monkeypatch):
        monkeypatch.setattr(events_module.settings, "SSE_KEEPALIVE_SECONDS", 0)
        redis = _redis()
        state: dict = {}
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ), patch(_SUBSCRIBE, _endless_subscribe(state)):
            # Prelude + one keepalive proves the subscription is live before
            # the tab closes.
            status, _, chunks = await stream_then_disconnect(
                _app(), "/api/events", chunks_before_disconnect=2
            )
        assert status == 200
        assert chunks[0] == b": connected\n\n"
        assert state.get("closed") is True
        assert redis.zsets == {}

    async def test_disconnect_before_first_frame_still_releases_lease(self):
        # The tab closes as the response starts: the body generator may never
        # run, so its own cleanup can't be what frees the slot.
        redis = _redis()
        state: dict = {}
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ), patch(_SUBSCRIBE, _endless_subscribe(state)):
            status, _, _ = await stream_then_disconnect(
                _app(), "/api/events", chunks_before_disconnect=0
            )
        assert status == 200
        assert redis.zsets == {}

    async def test_shutdown_ends_stream_and_releases_lease(self):
        redis = _redis()
        state: dict = {}
        begin_shutdown()
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ), patch(_SUBSCRIBE, _endless_subscribe(state)):
            status, _, chunks = await stream_then_disconnect(
                _app(), "/api/events", chunks_before_disconnect=10**6, timeout=3
            )
        assert status == 200
        assert b"".join(chunks) == b": connected\n\n"
        assert state.get("closed") is True
        assert redis.zsets == {}


# ── replay + live tail ──────────────────────────────────────────────────


@pytest.mark.unit
class TestReplayAndTail:
    def test_replay_yields_xrange_entries_with_injected_id(self):
        redis = _redis()
        redis.xrange = AsyncMock(
            return_value=[
                (
                    b"1735682400000-0",
                    {b"event": _stored({"type": "source.ingest.progress", "payload": {"current": 25}})},
                ),
            ]
        )
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ), patch(_SUBSCRIBE, _subscribe()):
            r = _get(headers={"Last-Event-ID": OLD_CURSOR})
        body = r.text
        assert body.startswith(": connected\n\n")
        assert "id: 1735682400000-0" in body
        data_line = next(line for line in body.split("\n") if line.startswith("data: "))
        envelope = json.loads(data_line[len("data: "):])
        assert envelope["id"] == "1735682400000-0"
        assert envelope["payload"] == {"current": 25}
        assert "backlog.truncated" not in body
        assert redis.xrange.await_args.kwargs["min"] == f"({OLD_CURSOR}"

    def test_query_param_cursor_is_honoured(self):
        redis = _redis()
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ), patch(_SUBSCRIBE, _subscribe()):
            _get(params={"last_event_id": OLD_CURSOR})
        assert redis.xrange.await_args.kwargs["min"] == f"({OLD_CURSOR}"

    def test_snapshot_flushed_when_subscribe_dies_after_callback(self):
        redis = _redis()
        redis.xrange = AsyncMock(
            return_value=[
                (b"1735682400000-0", {b"event": _stored({"type": "notification", "payload": {"text": "from snapshot"}})}),
            ]
        )
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ), patch(_SUBSCRIBE, _subscribe_dies_after_callback()):
            r = _get(headers={"Last-Event-ID": OLD_CURSOR})
        assert "id: 1735682400000-0" in r.text
        assert "from snapshot" in r.text
        redis.xrange.assert_awaited_once()

    def test_invalid_last_event_id_emits_truncation_notice(self):
        redis = _redis()
        redis.xinfo_stream = AsyncMock(return_value={"first-entry": [b"1-0", []]})
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ), patch(_SUBSCRIBE, _subscribe()):
            r = _get(headers={"Last-Event-ID": "definitely-not-an-id"})
        assert "backlog.truncated" in r.text
        # A corrupt cursor is a fresh session: nothing to replay.
        redis.xrange.assert_not_awaited()

    def test_live_tail_rejects_malformed_event_id_for_dedupe(self):
        """A pub/sub envelope with a non-Streams ``id`` must not seed the dedup
        floor, or a bogus lex-greater id would pin every later event below it.
        The event itself still ships, just without an ``id:`` line."""
        redis = _redis()
        redis.xrange = AsyncMock(
            return_value=[(b"1735682400000-0", {b"event": _stored({"type": "x", "payload": {"step": "replay"}})})]
        )
        live_bogus = _stored({"id": "definitely-not-an-id", "type": "x", "payload": {"step": "live-bogus"}})
        live_real = _stored({"id": "1735682500000-0", "type": "x", "payload": {"step": "live-real"}})
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ), patch(_SUBSCRIBE, _subscribe(live_bogus, live_real)):
            r = _get(headers={"Last-Event-ID": OLD_CURSOR})
        body = r.text
        assert "live-real" in body
        assert "id: 1735682500000-0" in body
        assert "live-bogus" in body
        assert "id: definitely-not-an-id" not in body

    def test_live_event_already_covered_by_snapshot_is_dropped(self):
        redis = _redis()
        redis.xrange = AsyncMock(
            return_value=[(b"1735682400000-0", {b"event": _stored({"type": "x", "payload": {"step": "replay"}})})]
        )
        duplicate = _stored({"id": "1735682400000-0", "type": "x", "payload": {"step": "replay"}})
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ), patch(_SUBSCRIBE, _subscribe(duplicate)):
            r = _get(headers={"Last-Event-ID": OLD_CURSOR})
        assert r.text.count("id: 1735682400000-0") == 1

    def test_non_json_live_payload_passes_through_without_id(self):
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=_redis())
        ), patch(_SUBSCRIBE, _subscribe(b"plain text")):
            r = _get()
        assert "data: plain text\n\n" in r.text


# ── replay budget and helpers ───────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
class TestReplayBudget:
    async def test_budget_disabled(self, monkeypatch):
        monkeypatch.setattr(events_module.settings, "EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW", 0)
        assert await events_module._allow_replay(_redis(), "alice", OLD_CURSOR) is True

    async def test_redis_unavailable_fails_open(self):
        assert await events_module._allow_replay(None, "alice", OLD_CURSOR) is True

    async def test_no_cursor_never_consumes_budget(self, monkeypatch):
        """Fresh sessions start live and must never 429 on the replay budget,
        no matter how many tabs open at once."""
        monkeypatch.setattr(events_module.settings, "EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW", 3)
        redis = _redis()
        for _ in range(50):
            assert await events_module._allow_replay(redis, "alice", None) is True
        redis.incr.assert_not_awaited()

    async def test_passes_until_budget_exhausted(self, monkeypatch):
        monkeypatch.setattr(events_module.settings, "EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW", 3)
        redis = _redis()
        counter = {"v": 0}

        def _incr(_key):
            counter["v"] += 1
            return counter["v"]

        redis.incr = AsyncMock(side_effect=_incr)
        results = [await events_module._allow_replay(redis, "alice", OLD_CURSOR) for _ in range(4)]
        assert results == [True, True, True, False]
        # TTL re-seeded on every INCR so a failed seeding EXPIRE can't wedge the key.
        assert redis.expire.await_count == 4
        assert all(call.args == ("user:alice:replay_count", 60) for call in redis.expire.await_args_list)

    async def test_fail_open_on_redis_error(self):
        redis = _redis()
        redis.incr = AsyncMock(side_effect=Exception("redis down"))
        assert await events_module._allow_replay(redis, "alice", OLD_CURSOR) is True

    async def test_fail_open_when_redis_stalls(self, monkeypatch):
        monkeypatch.setattr(events_module, "_REDIS_OP_TIMEOUT_SECONDS", 0.05)
        redis = _redis()

        async def _stalled(_key):
            await anyio.sleep_forever()

        redis.incr = AsyncMock(side_effect=_stalled)
        with anyio.fail_after(2):
            assert await events_module._allow_replay(redis, "alice", OLD_CURSOR) is True

    async def test_recovers_when_seeding_expire_raises(self):
        redis = _redis()
        counter = {"v": 0}

        def _incr(_key):
            counter["v"] += 1
            return counter["v"]

        redis.incr = AsyncMock(side_effect=_incr)
        redis.expire = AsyncMock(side_effect=[Exception("expire blip"), True])
        assert await events_module._allow_replay(redis, "alice", OLD_CURSOR) is True
        assert await events_module._allow_replay(redis, "alice", OLD_CURSOR) is True
        assert redis.expire.await_count == 2

    async def test_replay_backlog_passes_count_to_xrange(self):
        redis = _redis()
        assert await events_module._replay_backlog(redis, "alice", None, 200) == []
        assert redis.xrange.await_args.kwargs["count"] == 200

    async def test_replay_backlog_skips_entries_without_event(self):
        redis = _redis()
        redis.xrange = AsyncMock(
            return_value=[
                (b"1-0", {b"other": b"x"}),
                (b"2-0", {b"event": b"not json"}),
            ]
        )
        lines = await events_module._replay_backlog(redis, "alice", "0-0", 200)
        assert [entry_id for entry_id, _ in lines] == ["2-0"]
        assert lines[0][1] == "id: 2-0\ndata: not json\n\n"

    async def test_replay_backlog_returns_nothing_on_xrange_error(self):
        redis = _redis()
        redis.xrange = AsyncMock(side_effect=Exception("WRONGTYPE"))
        assert await events_module._replay_backlog(redis, "alice", "0-0", 200) == []

    async def test_oldest_retained_id(self):
        redis = _redis()
        redis.xinfo_stream = AsyncMock(return_value={"first-entry": [b"5-0", [b"event", b"{}"]]})
        assert await events_module._oldest_retained_id(redis, "alice") == "5-0"

    async def test_oldest_retained_id_bytes_keys(self):
        redis = _redis()
        redis.xinfo_stream = AsyncMock(return_value={b"first-entry": [b"6-0", []]})
        assert await events_module._oldest_retained_id(redis, "alice") == "6-0"

    async def test_oldest_retained_id_none_on_error_or_empty(self):
        redis = _redis()
        assert await events_module._oldest_retained_id(redis, "alice") is None
        redis.xinfo_stream = AsyncMock(return_value={"first-entry": None})
        assert await events_module._oldest_retained_id(redis, "alice") is None


@pytest.mark.unit
class TestReplayBudgetRoute:
    def test_returns_429_when_replay_budget_exhausted(self):
        """The route refuses rather than serving live-tail only: id-bearing
        live frames would advance the client's cursor past the un-replayed
        window. The 429 keeps the cursor pinned for the next attempt."""
        redis = _redis()
        redis.incr = AsyncMock(return_value=31)
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ), patch(_SUBSCRIBE, _subscribe()):
            r = _get(headers={"Last-Event-ID": OLD_CURSOR})
        assert r.status_code == 429
        assert r.json() == {"success": False, "message": "Replay budget exhausted"}
        # The connection lease is released so a denied request doesn't hold a slot.
        assert redis.zsets == {}


# ── format helpers ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestFormatHelpers:
    def test_format_sse_two_terminating_newlines(self):
        out = events_module._format_sse("hello", event_id="1-0")
        assert out.endswith("\n\n")
        assert out.rstrip("\n").split("\n") == ["id: 1-0", "data: hello"]

    @pytest.mark.parametrize(
        "candidate, expected",
        [
            ("1234", "1234"),
            ("1234-5", "1234-5"),
            ("  1234-0  ", "1234-0"),
            (None, None),
            ("", None),
            ("   ", None),
            ("nope", None),
            ("1234-foo", None),
        ],
    )
    def test_normalize_last_event_id(self, candidate, expected):
        assert events_module._normalize_last_event_id(candidate) == expected


# ── replay policy: fresh sessions start live, snapshots are age-capped ──


@pytest.mark.unit
class TestReplayPolicy:
    def test_replay_floor_id_disabled_when_setting_zero(self, monkeypatch):
        monkeypatch.setattr(events_module.settings, "EVENTS_REPLAY_MAX_AGE_HOURS", 0)
        assert events_module._replay_floor_id() is None

    def test_replay_floor_id_is_ms_stream_id(self, monkeypatch):
        monkeypatch.setattr(events_module.settings, "EVENTS_REPLAY_MAX_AGE_HOURS", 48)
        with patch("docsgpt.api.events.routes.time.time", return_value=1_800_000_000.0):
            floor = events_module._replay_floor_id()
        assert floor == f"{(1_800_000_000 - 48 * 3600) * 1000}-0"

    @pytest.mark.asyncio
    async def test_replay_backlog_uses_cursor_when_newer_than_floor(self):
        redis = _redis()
        with patch("docsgpt.api.events.routes._replay_floor_id", return_value="1000-0"):
            await events_module._replay_backlog(redis, "alice", "2000-0", 200)
        assert redis.xrange.await_args.kwargs["min"] == "(2000-0"

    @pytest.mark.asyncio
    async def test_replay_backlog_clamps_start_to_age_floor(self):
        redis = _redis()
        with patch("docsgpt.api.events.routes._replay_floor_id", return_value="5000-0"):
            await events_module._replay_backlog(redis, "alice", "2000-0", 200)
        # Entries past their shelf life are never shipped.
        assert redis.xrange.await_args.kwargs["min"] == "5000-0"

    def test_no_cursor_connect_never_replays(self):
        redis = _redis()
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ), patch(_SUBSCRIBE, _subscribe()):
            r = _get()
        assert r.text.startswith(": connected")
        redis.xrange.assert_not_awaited()

    def test_cursor_older_than_floor_emits_truncation_notice(self):
        """An age-clamped snapshot has a gap the client can't see from entry
        ids alone, so it must get the truncation notice and refetch state."""
        redis = _redis()
        with patch(_AUTH, return_value=ALICE), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ), patch(_SUBSCRIBE, _subscribe()), patch.object(
            events_module, "_replay_floor_id", return_value="9999999999999-0"
        ):
            r = _get(headers={"Last-Event-ID": "1735682400000-0"})
        assert "backlog.truncated" in r.text
