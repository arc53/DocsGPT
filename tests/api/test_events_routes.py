"""Tests for application/api/events/routes.py — the SSE endpoint.

The SSE generator runs in a separate thread under the WSGI test client;
we drive it with mocked Redis (the ``pubsub.get_message`` and ``xrange``
sequences) and read the response body until we have enough records to
assert on, then close the response to terminate the generator.
"""

from __future__ import annotations

import json
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, request


def _make_app():
    """Mount the events blueprint on a bare Flask app + JWT shim.

    The shim mimics ``application/app.py`` populating
    ``request.decoded_token`` so the SSE handler's auth gate sees a
    user-id without requiring the full app stack.
    """
    from application.api.events.routes import events

    app = Flask(__name__)
    app.register_blueprint(events)
    app.config["TESTING"] = True

    @app.before_request
    def _shim_auth():  # noqa: D401
        header = request.headers.get("X-Test-Sub")
        request.decoded_token = {"sub": header} if header else None

    return app


class _FakePubSub:
    """Minimal Redis pub/sub stand-in for the SSE handler.

    ``messages`` is a list of message dicts the generator should see in
    order. After exhausting it, ``get_message`` returns ``None`` (poll
    timeout) so the generator stays alive emitting keepalives until the
    test closes the response.
    """

    def __init__(self, messages: list[dict[str, Any]]):
        self._messages = list(messages)
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.closed = False
        self._lock = threading.Lock()

    def subscribe(self, name: str):
        self.subscribed.append(name)

    def unsubscribe(self, name: str):
        self.unsubscribed.append(name)

    def close(self):
        self.closed = True

    def get_message(self, timeout: float = 0):
        with self._lock:
            if self._messages:
                return self._messages.pop(0)
        return None


def _drain_until(response, predicate, max_chunks: int = 200) -> bytes:
    """Consume the streamed response until ``predicate(buf)`` is true.

    Returns the accumulated bytes. Closes the response so the generator
    exits cleanly via GeneratorExit.
    """
    buf = b""
    iterator = response.iter_encoded()
    for _ in range(max_chunks):
        try:
            chunk = next(iterator)
        except StopIteration:
            break
        if not chunk:
            continue
        buf += chunk
        if predicate(buf):
            break
    response.close()
    return buf


# ── auth gate ───────────────────────────────────────────────────────────


class TestAuthGate:
    def test_rejects_when_no_decoded_token(self):
        app = _make_app()
        with app.test_client() as c:
            r = c.get("/api/events")
        assert r.status_code == 401

    def test_rejects_when_decoded_token_missing_sub(self):
        from application.api.events import routes as events_module

        app = _make_app()

        # Clear the shim's behavior — supply a decoded_token without sub.
        @app.before_request
        def _override():
            request.decoded_token = {"email": "x@y.z"}

        with patch.object(events_module, "get_redis_instance", return_value=None):
            with app.test_client() as c:
                r = c.get("/api/events")
        assert r.status_code == 401


# ── streaming response shape ────────────────────────────────────────────


class TestStreamShape:
    def test_returns_event_stream_mimetype_and_no_buffering_header(self):
        from application.api.events import routes as events_module

        app = _make_app()
        with patch.object(events_module, "get_redis_instance", return_value=None):
            with app.test_client() as c:
                r = c.get("/api/events", headers={"X-Test-Sub": "alice"})
                assert r.status_code == 200
                assert r.mimetype == "text/event-stream"
                assert r.headers.get("Cache-Control") == "no-store"
                assert r.headers.get("X-Accel-Buffering") == "no"
                # Drain enough to see the prelude comment then close.
                body = _drain_until(r, lambda b: b": connected" in b)
                assert b": connected" in body

    def test_emits_push_disabled_when_setting_off(self):
        from application.api.events import routes as events_module

        app = _make_app()
        with patch.object(events_module, "get_redis_instance", return_value=None), \
             patch.object(events_module.settings, "ENABLE_SSE_PUSH", False):
            with app.test_client() as c:
                r = c.get("/api/events", headers={"X-Test-Sub": "alice"})
                body = _drain_until(r, lambda b: b": push_disabled" in b)
                assert b": push_disabled" in body
                assert b": connected" in body  # prelude still emitted


# ── concurrency cap ─────────────────────────────────────────────────────


class TestConcurrencyCap:
    def test_returns_429_when_user_over_cap(self):
        from application.api.events import routes as events_module

        app = _make_app()
        redis_client = MagicMock()
        # First INCR returns 9 (over cap of 8).
        redis_client.incr.return_value = 9

        with patch.object(events_module, "get_redis_instance", return_value=redis_client), \
             patch.object(events_module.settings, "SSE_MAX_CONCURRENT_PER_USER", 8):
            with app.test_client() as c:
                r = c.get("/api/events", headers={"X-Test-Sub": "alice"})
        assert r.status_code == 429
        # DECR fired to release the over-cap increment.
        redis_client.decr.assert_called_once_with("user:alice:sse_count")

    def test_skips_cap_when_zero_disabled(self):
        from application.api.events import routes as events_module

        app = _make_app()
        redis_client = MagicMock()

        with patch.object(events_module, "get_redis_instance", return_value=redis_client), \
             patch.object(events_module.settings, "SSE_MAX_CONCURRENT_PER_USER", 0), \
             patch.object(events_module, "Topic") as mock_topic_cls:
            mock_topic = MagicMock()
            mock_topic.subscribe.return_value = iter([])
            mock_topic_cls.return_value = mock_topic
            redis_client.xinfo_stream.side_effect = Exception("no stream")
            redis_client.xrange.return_value = []
            with app.test_client() as c:
                r = c.get("/api/events", headers={"X-Test-Sub": "alice"})
                assert r.status_code == 200
                # Concurrency counter not touched when cap is 0. The
                # replay-budget INCR is unrelated and may still fire.
                incr_keys = [
                    call.args[0] for call in redis_client.incr.call_args_list
                ]
                assert "user:alice:sse_count" not in incr_keys
                _drain_until(r, lambda b: b": connected" in b)


# ── replay + live tail ──────────────────────────────────────────────────


class TestReplayAndTail:
    def test_replay_yields_xrange_entries_with_injected_id(self):
        from application.api.events import routes as events_module

        app = _make_app()
        redis_client = MagicMock()
        redis_client.incr.return_value = 1
        # Empty stream (no truncation).
        redis_client.xinfo_stream.side_effect = Exception("nope")
        # XRANGE returns one stored envelope (without ``id``); the route
        # injects the entry id on the way out.
        stored_event = json.dumps(
            {
                "type": "source.ingest.progress",
                "ts": "2026-04-28T00:00:00.000Z",
                "user_id": "alice",
                "topic": "user:alice",
                "scope": {"kind": "source", "id": "src-1"},
                "payload": {"current": 25, "total": 100},
            }
        ).encode()
        redis_client.xrange.return_value = [
            (b"1735682400000-0", {b"event": stored_event}),
        ]

        # Topic.subscribe yields an immediate timeout so the generator
        # keeps running long enough to flush replay; subsequent calls
        # also return None.
        from application.api.events.routes import _SSE_LINE_SPLIT  # noqa: F401

        # Fake the broadcast Topic to invoke on_subscribe immediately
        # then yield None ticks until close.
        def _fake_subscribe(self, on_subscribe=None, poll_timeout=1.0):
            if on_subscribe is not None:
                on_subscribe()
            while True:
                yield None

        with patch.object(events_module, "get_redis_instance", return_value=redis_client), \
             patch.object(
                 events_module.Topic, "subscribe", _fake_subscribe, create=False
             ):
            with app.test_client() as c:
                r = c.get(
                    "/api/events",
                    headers={"X-Test-Sub": "alice", "Last-Event-ID": "1735682300000-0"},
                )
                body = _drain_until(
                    r,
                    lambda b: b'"current": 25' in b or b'"current":25' in b,
                    max_chunks=80,
                )
                # Replay yields the entry id as the SSE id field.
                assert b"id: 1735682400000-0" in body
                # Envelope was rewritten to include the injected id.
                assert b'"id": "1735682400000-0"' in body or b'"id":"1735682400000-0"' in body
                # The connect log fires before replay.
                assert b": connected" in body

    def test_snapshot_flushed_when_subscribe_dies_after_callback(self):
        """Regression: if ``on_subscribe`` populated ``replay_lines`` but
        ``Topic.subscribe`` exits before yielding once (transient Redis
        hiccup between SUBSCRIBE-ack and the first poll), the snapshot
        must still reach the client. Prior to the fix the in-loop flush
        was the only flush, so the backlog was silently dropped.
        """
        from application.api.events import routes as events_module

        app = _make_app()
        redis_client = MagicMock()
        redis_client.incr.return_value = 1
        redis_client.xinfo_stream.side_effect = Exception("nope")
        stored_event = json.dumps(
            {
                "type": "notification",
                "payload": {"text": "from snapshot"},
            }
        ).encode()
        redis_client.xrange.return_value = [
            (b"1735682400000-0", {b"event": stored_event}),
        ]

        # Mimic the broadcast_channel race: SUBSCRIBE acks, on_subscribe
        # runs, then the next get_message raises and the generator
        # returns without ever yielding.
        def _subscribe_dies_after_callback(
            self, on_subscribe=None, poll_timeout=1.0
        ):
            if on_subscribe is not None:
                on_subscribe()
            return
            yield  # pragma: no cover  (make the function a generator)

        with patch.object(events_module, "get_redis_instance", return_value=redis_client), \
             patch.object(
                 events_module.Topic,
                 "subscribe",
                 _subscribe_dies_after_callback,
                 create=False,
             ):
            with app.test_client() as c:
                r = c.get(
                    "/api/events",
                    headers={
                        "X-Test-Sub": "alice",
                        "Last-Event-ID": "1735682300000-0",
                    },
                )
                body = _drain_until(
                    r,
                    lambda b: b"from snapshot" in b,
                    max_chunks=80,
                )
                # Snapshot frame must have been flushed via the post-loop
                # safety net even though Topic.subscribe exited before
                # the in-loop flush could fire.
                assert b"id: 1735682400000-0" in body
                assert b"from snapshot" in body
                # XRANGE was issued exactly once (no double-flush).
                redis_client.xrange.assert_called_once()

    def test_invalid_last_event_id_emits_truncation_notice(self):
        from application.api.events import routes as events_module

        app = _make_app()
        redis_client = MagicMock()
        redis_client.incr.return_value = 1
        redis_client.xinfo_stream.return_value = {"first-entry": [b"1-0", []]}
        redis_client.xrange.return_value = []

        def _fake_subscribe(self, on_subscribe=None, poll_timeout=1.0):
            if on_subscribe is not None:
                on_subscribe()
            while True:
                yield None

        with patch.object(events_module, "get_redis_instance", return_value=redis_client), \
             patch.object(events_module.Topic, "subscribe", _fake_subscribe, create=False):
            with app.test_client() as c:
                r = c.get(
                    "/api/events",
                    headers={"X-Test-Sub": "alice", "Last-Event-ID": "definitely-not-an-id"},
                )
                body = _drain_until(
                    r, lambda b: b"backlog.truncated" in b, max_chunks=80
                )
                assert b"backlog.truncated" in body

    def test_live_tail_rejects_malformed_event_id_for_dedupe(self):
        """A pub/sub envelope carrying a non-Redis-Streams ``id`` must not
        seed the dedup floor. Otherwise an adversarial or buggy publisher
        could ship ``id="9999999999999-9"`` (lex-greater than any real
        id) and pin every subsequent legitimate event below the floor,
        silently dropping the user's notifications.

        The event itself should still be delivered to the client — we
        just refuse to use the bogus id for ordering, so it ships
        without an SSE ``id:`` header and ``max_replayed_id`` stays put.
        """
        from application.api.events import routes as events_module

        app = _make_app()
        redis_client = MagicMock()
        redis_client.incr.return_value = 1
        redis_client.xinfo_stream.side_effect = Exception("nope")
        # Snapshot covers ids up to 1735682400000-0; max_replayed_id
        # becomes that value after the in-loop flush.
        replay_event = json.dumps({
            "type": "source.ingest.progress",
            "payload": {"step": "replay"},
        }).encode()
        redis_client.xrange.return_value = [
            (b"1735682400000-0", {b"event": replay_event}),
        ]

        live_bogus = json.dumps({
            "id": "definitely-not-an-id",
            "type": "source.ingest.completed",
            "payload": {"step": "live-bogus"},
        })
        live_real = json.dumps({
            "id": "1735682500000-0",
            "type": "source.ingest.completed",
            "payload": {"step": "live-real"},
        })

        def _fake_subscribe(self, on_subscribe=None, poll_timeout=1.0):
            # ``Topic.subscribe`` already unpacks redis-py pubsub dicts
            # and yields the raw ``data`` bytes (or ``None`` on poll
            # timeout). Mirror that contract.
            if on_subscribe is not None:
                on_subscribe()
            yield live_bogus.encode()
            yield live_real.encode()
            while True:
                yield None

        with patch.object(
            events_module, "get_redis_instance", return_value=redis_client
        ), patch.object(
            events_module.Topic, "subscribe", _fake_subscribe, create=False
        ):
            with app.test_client() as c:
                r = c.get(
                    "/api/events",
                    headers={
                        "X-Test-Sub": "alice",
                        "Last-Event-ID": "1735682300000-0",
                    },
                )
                body = _drain_until(
                    r, lambda b: b"live-real" in b, max_chunks=80
                )

                # Live-real arrived (its id is strictly greater than the
                # replayed snapshot's id), with its valid id surfaced as
                # the SSE ``id:`` header so the frontend can advance.
                assert b"live-real" in body
                assert b"id: 1735682500000-0" in body

                # The bogus-id event was still delivered to the client,
                # but no ``id: definitely-not-an-id`` line was emitted —
                # the malformed id never reached the SSE wire and so
                # could not pin the dedup floor.
                assert b"live-bogus" in body
                assert b"id: definitely-not-an-id" not in body


# ── format helpers (already covered in test_events_substrate but
#    duplicated here as a smoke for the route's surface) ─────────────────


class TestReplayRateLimit:
    """Phase 4B: enumeration defenses on the per-user backlog."""

    def test_allow_replay_returns_true_when_budget_disabled(self):
        from application.api.events.routes import _allow_replay

        with patch("application.api.events.routes.settings") as mock_settings:
            mock_settings.EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW = 0
            mock_settings.EVENTS_REPLAY_BUDGET_WINDOW_SECONDS = 60
            assert _allow_replay(MagicMock(), "alice", "1735682400000-0") is True

    def test_allow_replay_returns_true_when_redis_unavailable(self):
        from application.api.events.routes import _allow_replay

        with patch("application.api.events.routes.settings") as mock_settings:
            mock_settings.EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW = 5
            mock_settings.EVENTS_REPLAY_BUDGET_WINDOW_SECONDS = 60
            assert _allow_replay(None, "alice", "1735682400000-0") is True

    def test_allow_replay_skips_incr_when_no_cursor_and_empty_backlog(self):
        """Fresh client with no cursor and an empty user stream cannot
        do snapshot work — INCR'ing the counter would needlessly
        burn budget. Catches the React-StrictMode dev-burst case where
        double-mounted components would otherwise 429 in 5 connects.
        """
        from application.api.events.routes import _allow_replay

        with patch("application.api.events.routes.settings") as mock_settings:
            mock_settings.EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW = 3
            mock_settings.EVENTS_REPLAY_BUDGET_WINDOW_SECONDS = 60
            redis = MagicMock()
            redis.xlen.return_value = 0

            # 5 connects in a row, all with no cursor — none consume
            # budget because the backlog is empty.
            for _ in range(5):
                assert _allow_replay(redis, "alice", None) is True

            redis.xlen.assert_called()
            redis.incr.assert_not_called()

    def test_allow_replay_incrs_when_no_cursor_but_backlog_present(self):
        """A no-cursor connect against a non-empty backlog *will* do
        snapshot work, so it consumes budget normally.
        """
        from application.api.events.routes import _allow_replay

        with patch("application.api.events.routes.settings") as mock_settings:
            mock_settings.EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW = 5
            mock_settings.EVENTS_REPLAY_BUDGET_WINDOW_SECONDS = 60
            redis = MagicMock()
            redis.xlen.return_value = 42
            redis.incr.return_value = 1

            assert _allow_replay(redis, "alice", None) is True
            redis.incr.assert_called_once()

    def test_allow_replay_passes_until_budget_exhausted(self):
        from application.api.events.routes import _allow_replay

        with patch("application.api.events.routes.settings") as mock_settings:
            mock_settings.EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW = 3
            mock_settings.EVENTS_REPLAY_BUDGET_WINDOW_SECONDS = 60
            redis = MagicMock()
            counter = {"v": 0}

            def _incr(_key):
                counter["v"] += 1
                return counter["v"]

            redis.incr.side_effect = _incr

            # Cursor set → XLEN short-circuit doesn't fire, INCR always runs.
            cursor = "1735682400000-0"
            # First three pass.
            assert _allow_replay(redis, "alice", cursor) is True
            assert _allow_replay(redis, "alice", cursor) is True
            assert _allow_replay(redis, "alice", cursor) is True
            # Fourth refused.
            assert _allow_replay(redis, "alice", cursor) is False
            # TTL only seeded on the first INCR (when count == 1).
            redis.expire.assert_called_once()

    def test_allow_replay_fail_open_on_redis_error(self):
        from application.api.events.routes import _allow_replay

        with patch("application.api.events.routes.settings") as mock_settings:
            mock_settings.EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW = 5
            mock_settings.EVENTS_REPLAY_BUDGET_WINDOW_SECONDS = 60
            redis = MagicMock()
            redis.incr.side_effect = Exception("redis down")
            assert _allow_replay(redis, "alice", "1735682400000-0") is True

    def test_replay_backlog_passes_count_to_xrange(self):
        from application.api.events.routes import _replay_backlog

        redis = MagicMock()
        redis.xrange.return_value = []
        # Drain the iterator so xrange is actually called.
        list(_replay_backlog(redis, "alice", None, 200))
        redis.xrange.assert_called_once()
        kwargs = redis.xrange.call_args.kwargs
        assert kwargs.get("count") == 200

    def test_returns_429_when_replay_budget_exhausted(self):
        """Route refuses the connection rather than serving live tail
        only. Earlier behavior silently skipped replay and let the
        client advance ``lastEventId`` via id-bearing live frames,
        permanently stranding the un-replayed window. The 429 keeps
        the cursor pinned so the next reconnect (after the budget
        window slides) can replay normally.
        """
        from application.api.events import routes as events_module

        app = _make_app()
        redis_client = MagicMock()

        def _incr(key):
            if key == "user:alice:sse_count":
                return 1
            # Budget counter: report over-limit.
            return 31

        redis_client.incr.side_effect = _incr

        with patch.object(
            events_module, "get_redis_instance", return_value=redis_client
        ), patch.object(
            events_module.settings,
            "EVENTS_REPLAY_BUDGET_REQUESTS_PER_WINDOW",
            30,
        ):
            with app.test_client() as c:
                r = c.get(
                    "/api/events",
                    headers={
                        "X-Test-Sub": "alice",
                        "Last-Event-ID": "1735682300000-0",
                    },
                )
        assert r.status_code == 429
        # Concurrency slot is released so a budget-denied request
        # doesn't permanently consume a connection from the cap.
        redis_client.decr.assert_called_once_with("user:alice:sse_count")


class TestFormatHelpers:
    def test_format_sse_two_terminating_newlines(self):
        from application.api.events.routes import _format_sse

        out = _format_sse("hello", event_id="1-0")
        assert out.endswith("\n\n")
        # Exactly one ``id:`` and one ``data:``.
        lines = out.rstrip("\n").split("\n")
        assert lines == ["id: 1-0", "data: hello"]

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
        from application.api.events.routes import _normalize_last_event_id

        assert _normalize_last_event_id(candidate) == expected
