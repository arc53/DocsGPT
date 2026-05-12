"""Unit tests for the SSE substrate (publisher + Topic + route helpers).

Round-trip integration tests against a real / fake Redis live in
``tests/test_events_integration.py`` (Phase 1E). The tests here lock in
the closure-mutated, race-sensitive bits the route relies on so future
refactors can't regress them silently.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from application.api.events.routes import (
    _SSE_LINE_SPLIT,
    _format_sse,
    _normalize_last_event_id,
)
from application.events.keys import (
    connection_counter_key,
    stream_id_compare,
    stream_key,
    topic_name,
)
from application.events.publisher import publish_user_event
from application.streaming.broadcast_channel import Topic


# ── keys ────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestKeys:
    def test_stream_key(self):
        assert stream_key("alice") == "user:alice:stream"

    def test_topic_name(self):
        assert topic_name("alice") == "user:alice"

    def test_connection_counter_key(self):
        assert connection_counter_key("alice") == "user:alice:sse_count"


# ── stream_id_compare ───────────────────────────────────────────────────


@pytest.mark.unit
class TestStreamIdCompare:
    def test_equal(self):
        assert stream_id_compare("1234-0", "1234-0") == 0

    def test_seq_ordering(self):
        assert stream_id_compare("1234-0", "1234-1") == -1
        assert stream_id_compare("1234-1", "1234-0") == 1

    def test_ms_ordering(self):
        assert stream_id_compare("1234-0", "5678-0") == -1
        assert stream_id_compare("5678-0", "1234-0") == 1

    def test_digit_count_does_not_break_int_compare(self):
        # String compare would say "9" > "100"; integer compare must not.
        assert stream_id_compare("9-0", "100-0") == -1
        assert stream_id_compare("100-0", "9-0") == 1

    def test_missing_seq_treated_as_zero(self):
        assert stream_id_compare("1234", "1234-0") == 0

    def test_malformed_input_raises(self):
        # Callers must pre-validate; the function refuses to silently
        # lex-compare garbage because a malformed id that sorts
        # lex-greater would pin dedup forever.
        with pytest.raises(ValueError):
            stream_id_compare("foo", "bar")
        with pytest.raises(ValueError):
            stream_id_compare("123-0", "foo")
        with pytest.raises(ValueError):
            stream_id_compare("foo", "123-0")


# ── _format_sse ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestFormatSse:
    def test_simple_payload(self):
        assert _format_sse("hello") == "data: hello\n\n"

    def test_with_event_id(self):
        assert _format_sse("hello", event_id="42-0") == "id: 42-0\ndata: hello\n\n"

    def test_lf_split(self):
        assert _format_sse("a\nb") == "data: a\ndata: b\n\n"

    def test_crlf_split(self):
        assert _format_sse("a\r\nb") == "data: a\ndata: b\n\n"

    def test_cr_only_split(self):
        # WHATWG SSE treats CR alone as a line terminator. Must match.
        assert _format_sse("a\rb") == "data: a\ndata: b\n\n"

    def test_mixed_terminators(self):
        # Each variant in one payload — all should split.
        out = _format_sse("a\rb\nc\r\nd")
        assert out == "data: a\ndata: b\ndata: c\ndata: d\n\n"

    def test_empty_payload(self):
        # WHATWG: empty data field is dispatched as a message with data="".
        assert _format_sse("") == "data: \n\n"

    def test_terminator_regex_compiles(self):
        # Defensive: ensure the regex itself is well-formed.
        assert _SSE_LINE_SPLIT.split("a\r\nb\rc\nd") == ["a", "b", "c", "d"]


# ── _normalize_last_event_id ────────────────────────────────────────────


@pytest.mark.unit
class TestNormalizeLastEventId:
    def test_none(self):
        assert _normalize_last_event_id(None) is None

    def test_empty_string(self):
        assert _normalize_last_event_id("") is None

    def test_whitespace_only(self):
        assert _normalize_last_event_id("   ") is None

    def test_stripped_valid_id(self):
        assert _normalize_last_event_id("  1234-0  ") == "1234-0"

    def test_ms_only(self):
        assert _normalize_last_event_id("1234567890") == "1234567890"

    def test_ms_seq(self):
        assert _normalize_last_event_id("1234567890-0") == "1234567890-0"

    def test_high_seq(self):
        assert _normalize_last_event_id("1-99999") == "1-99999"

    def test_garbage_rejected(self):
        for bad in ("foo", "foo-bar", "1234-foo", "-1", "1234-", "1-2-3", "0x1234"):
            assert _normalize_last_event_id(bad) is None, bad


# ── publisher ───────────────────────────────────────────────────────────


@pytest.mark.unit
class TestPublishUserEvent:
    def setup_method(self):
        # Reset the cache singleton so the patched mock gets used.
        import application.cache as cache_mod

        cache_mod._redis_instance = None
        cache_mod._redis_creation_failed = False

    def teardown_method(self):
        import application.cache as cache_mod

        cache_mod._redis_instance = None
        cache_mod._redis_creation_failed = False

    def test_returns_none_on_missing_user_id(self):
        assert publish_user_event("", "x.y", {}) is None

    def test_returns_none_on_missing_event_type(self):
        assert publish_user_event("alice", "", {}) is None

    @patch("application.events.publisher.get_redis_instance")
    @patch("application.events.publisher.settings")
    def test_returns_none_when_push_disabled(self, mock_settings, mock_redis):
        mock_settings.ENABLE_SSE_PUSH = False
        mock_settings.EVENTS_STREAM_MAXLEN = 1000
        result = publish_user_event("alice", "src.ingest.progress", {"current": 1})
        assert result is None
        # Must not even reach Redis when the master switch is off.
        mock_redis.assert_not_called()

    @patch("application.events.publisher.get_redis_instance")
    @patch("application.events.publisher.settings")
    def test_returns_none_when_redis_unavailable(self, mock_settings, mock_redis):
        mock_settings.ENABLE_SSE_PUSH = True
        mock_settings.EVENTS_STREAM_MAXLEN = 1000
        mock_redis.return_value = None
        assert publish_user_event("alice", "x.y", {}) is None

    @patch("application.events.publisher.get_redis_instance")
    @patch("application.events.publisher.settings")
    def test_returns_none_on_unserializable_payload(
        self, mock_settings, mock_redis
    ):
        # Set object can't be JSON-encoded; the publisher must catch
        # this *before* hitting Redis, with a single warning log.
        mock_settings.ENABLE_SSE_PUSH = True
        mock_settings.EVENTS_STREAM_MAXLEN = 1000
        result = publish_user_event(
            "alice", "x.y", {"bad": {1, 2, 3}}  # type: ignore[arg-type]
        )
        assert result is None
        mock_redis.assert_not_called()

    @patch("application.events.publisher.Topic")
    @patch("application.events.publisher.get_redis_instance")
    @patch("application.events.publisher.settings")
    def test_xadd_and_publish_both_invoked_on_happy_path(
        self, mock_settings, mock_redis, mock_topic_cls
    ):
        mock_settings.ENABLE_SSE_PUSH = True
        mock_settings.EVENTS_STREAM_MAXLEN = 750
        mock_client = MagicMock()
        mock_client.xadd.return_value = b"1735682400000-0"
        mock_redis.return_value = mock_client
        mock_topic = MagicMock()
        mock_topic_cls.return_value = mock_topic

        result = publish_user_event(
            "alice",
            "source.ingest.progress",
            {"current": 30, "total": 100},
            scope={"kind": "source", "id": "abc"},
        )

        assert result == "1735682400000-0"

        # XADD: stream key, MAXLEN, approximate — and the envelope before
        # the id was known.
        mock_client.xadd.assert_called_once()
        args, kwargs = mock_client.xadd.call_args
        assert args[0] == "user:alice:stream"
        assert kwargs.get("maxlen") == 750
        assert kwargs.get("approximate") is True
        # The envelope inside the XADD does NOT carry an ``id`` yet (it
        # only exists after Redis returns), so the publish-time envelope
        # is the source of truth for ``id``.
        stored_event = json.loads(args[1]["event"])
        assert "id" not in stored_event
        assert stored_event["type"] == "source.ingest.progress"
        assert stored_event["topic"] == "user:alice"
        assert stored_event["payload"] == {"current": 30, "total": 100}
        assert stored_event["scope"] == {"kind": "source", "id": "abc"}

        # PUBLISH: same envelope plus the ``id`` from XADD.
        mock_topic_cls.assert_called_once_with("user:alice")
        mock_topic.publish.assert_called_once()
        published = json.loads(mock_topic.publish.call_args[0][0])
        assert published["id"] == "1735682400000-0"
        assert published["type"] == "source.ingest.progress"

    @patch("application.events.publisher.Topic")
    @patch("application.events.publisher.get_redis_instance")
    @patch("application.events.publisher.settings")
    def test_xadd_failure_skips_live_publish(
        self, mock_settings, mock_redis, mock_topic_cls
    ):
        """If the durable journal write fails there is no canonical id
        to ship. Publishing an id-less envelope would put a record on
        the wire that bypasses the SSE route's dedup floor and breaks
        ``Last-Event-ID`` semantics for any reconnect — so we drop the
        live publish too. Best-effort delivery means dropping
        consistently, not delivering inconsistent state.
        """
        mock_settings.ENABLE_SSE_PUSH = True
        mock_settings.EVENTS_STREAM_MAXLEN = 1000
        mock_client = MagicMock()
        mock_client.xadd.side_effect = Exception("redis went down")
        mock_redis.return_value = mock_client
        mock_topic = MagicMock()
        mock_topic_cls.return_value = mock_topic

        result = publish_user_event("alice", "x.y", {"k": 1})

        # Backlog write failed → publisher returns None and skips the
        # live publish so subscribers never see an id-less envelope.
        assert result is None
        mock_topic.publish.assert_not_called()


# ── Topic ───────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestTopic:
    @patch("application.streaming.broadcast_channel.get_redis_instance")
    def test_publish_returns_zero_when_redis_unavailable(self, mock_redis):
        mock_redis.return_value = None
        assert Topic("user:alice").publish("hi") == 0

    @patch("application.streaming.broadcast_channel.get_redis_instance")
    def test_publish_calls_redis_publish(self, mock_redis):
        client = MagicMock()
        client.publish.return_value = 3
        mock_redis.return_value = client
        result = Topic("user:alice").publish("hi")
        assert result == 3
        client.publish.assert_called_once_with("user:alice", "hi")

    @patch("application.streaming.broadcast_channel.get_redis_instance")
    def test_publish_swallows_exceptions(self, mock_redis):
        client = MagicMock()
        client.publish.side_effect = Exception("boom")
        mock_redis.return_value = client
        # Must not raise.
        assert Topic("user:alice").publish("hi") == 0

    @patch("application.streaming.broadcast_channel.get_redis_instance")
    def test_subscribe_returns_immediately_when_redis_unavailable(
        self, mock_redis
    ):
        mock_redis.return_value = None
        # Generator should produce nothing, not raise.
        assert list(Topic("user:alice").subscribe(poll_timeout=0.01)) == []

    @patch("application.streaming.broadcast_channel.get_redis_instance")
    def test_subscribe_yields_none_on_poll_timeout(self, mock_redis):
        client = MagicMock()
        pubsub = MagicMock()
        # Two timeouts (None) then a real message — caller breaks after.
        pubsub.get_message.side_effect = [None, None, {"type": "message", "data": b"x"}]
        client.pubsub.return_value = pubsub
        mock_redis.return_value = client

        gen = Topic("user:alice").subscribe(poll_timeout=0.01)
        first = next(gen)
        second = next(gen)
        third = next(gen)
        assert first is None
        assert second is None
        assert third == b"x"
        gen.close()

    @patch("application.streaming.broadcast_channel.get_redis_instance")
    def test_subscribe_fires_on_subscribe_after_ack(self, mock_redis):
        client = MagicMock()
        pubsub = MagicMock()
        pubsub.get_message.side_effect = [
            {"type": "subscribe", "data": 1},
            {"type": "message", "data": b"hi"},
        ]
        client.pubsub.return_value = pubsub
        mock_redis.return_value = client

        callback_calls = []

        def cb():
            callback_calls.append(1)

        gen = Topic("user:alice").subscribe(on_subscribe=cb, poll_timeout=0.01)
        # The "subscribe" message is consumed without yielding; the next
        # value yielded is the actual data message.
        msg = next(gen)
        assert msg == b"hi"
        assert callback_calls == [1]
        gen.close()

    @patch("application.streaming.broadcast_channel.get_redis_instance")
    def test_subscribe_cleans_up_on_generator_close(self, mock_redis):
        client = MagicMock()
        pubsub = MagicMock()
        pubsub.get_message.side_effect = [
            {"type": "subscribe", "data": 1},
            None,  # one tick so we stay in the loop
        ]
        client.pubsub.return_value = pubsub
        mock_redis.return_value = client

        gen = Topic("user:alice").subscribe(poll_timeout=0.01)
        next(gen)  # advance into the subscribe-confirmation
        gen.close()  # client disconnect

        pubsub.unsubscribe.assert_called_once_with("user:alice")
        pubsub.close.assert_called_once()

    @patch("application.streaming.broadcast_channel.get_redis_instance")
    def test_subscribe_skips_unsubscribe_if_subscribe_never_acked(
        self, mock_redis
    ):
        client = MagicMock()
        pubsub = MagicMock()
        pubsub.subscribe.side_effect = Exception("connection lost")
        client.pubsub.return_value = pubsub
        mock_redis.return_value = client

        # The generator must not yield, must not raise, and must not call
        # unsubscribe (we never confirmed a subscription).
        list(Topic("user:alice").subscribe(poll_timeout=0.01))
        pubsub.unsubscribe.assert_not_called()
        pubsub.close.assert_called_once()
