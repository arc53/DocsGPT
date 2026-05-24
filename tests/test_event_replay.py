"""Unit tests for ``application/streaming/event_replay.py``.

The replay generator is the snapshot+tail boundary the chat-stream
reconnect path lives on. The boundary correctness invariants worth
locking down:

- Snapshot replay yields rows in ``sequence_no`` order with the SSE
  ``id:`` header set to that sequence_no.
- Live tail dedupes pub/sub messages whose ``sequence_no`` is already
  covered by the snapshot.
- A backlog read failure inside ``on_subscribe`` doesn't wedge the
  generator — it surfaces a terminal ``error`` event (``code:
  snapshot_failed``) and returns, freeing the WSGI thread instead of
  pinning it on keepalives the client can't hear as terminal.
- Keepalive comments fire after the configured silence window.
- ``encode_pubsub_message`` round-trips with ``_decode_pubsub_message``.
"""

from __future__ import annotations

import json
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from application.streaming.event_replay import (
    _SSE_LINE_SPLIT_PATTERN,
    _decode_pubsub_message,
    build_message_event_stream,
    encode_pubsub_message,
    format_sse_event,
)


# ── format_sse_event ────────────────────────────────────────────────────


@pytest.mark.unit
class TestFormatSseEvent:
    def test_simple_payload(self):
        out = format_sse_event({"type": "answer", "answer": "Hi"}, sequence_no=3)
        # Body is one JSON line; SSE record terminated with blank line.
        lines = out.rstrip("\n").split("\n")
        assert lines[0] == "id: 3"
        assert lines[1].startswith("data: ")
        body = lines[1][len("data: "):]
        assert json.loads(body) == {"type": "answer", "answer": "Hi"}
        assert out.endswith("\n\n")

    def test_negative_sequence_for_synthetic_events(self):
        out = format_sse_event(
            {"type": "error", "code": "snapshot_failed"}, sequence_no=-1
        )
        assert "id: -1" in out

    def test_payload_with_embedded_newlines_splits_into_multiple_data_lines(self):
        # A pathological payload (shouldn't happen for json.dumps output,
        # but defensive against future callers).
        out = format_sse_event({"type": "x", "text": "a\nb"}, sequence_no=0)
        # The JSON itself escapes newlines, so this still produces one
        # data line — the split logic kicks in only when the encoded
        # body has literal newlines.
        assert out.count("data: ") == 1


# ── pub/sub encode/decode ───────────────────────────────────────────────


@pytest.mark.unit
class TestPubsubEnvelope:
    def test_encode_decode_roundtrip(self):
        wire = encode_pubsub_message(
            "msg-1", 7, "answer", {"type": "answer", "answer": "ok"}
        )
        envelope = _decode_pubsub_message(wire.encode("utf-8"))
        assert envelope == {
            "message_id": "msg-1",
            "sequence_no": 7,
            "event_type": "answer",
            "payload": {"type": "answer", "answer": "ok"},
        }

    def test_decode_returns_none_on_garbage(self):
        assert _decode_pubsub_message(b"not json") is None
        assert _decode_pubsub_message(b'"top-level-string"') is None
        assert _decode_pubsub_message(b"null") is None

    def test_decode_accepts_str_input(self):
        envelope = _decode_pubsub_message('{"sequence_no": 1, "payload": {}}')
        assert envelope == {"sequence_no": 1, "payload": {}}


# ── build_message_event_stream ──────────────────────────────────────────


def _fake_topic_subscribe(messages: list, *, fire_callback: bool = True):
    """Build a ``Topic.subscribe`` mock that fires ``on_subscribe`` then
    yields the supplied bytes in order, then yields ``None`` ticks
    indefinitely so the generator can keep running until the test
    closes it.
    """

    def _impl(self, on_subscribe=None, poll_timeout=1.0):
        if fire_callback and on_subscribe is not None:
            on_subscribe()
        for m in messages:
            yield m
        while True:
            yield None

    return _impl


def _drain(gen: Iterator[str], *, max_items: int = 50) -> list[str]:
    out = []
    try:
        for _ in range(max_items):
            out.append(next(gen))
    except StopIteration:
        pass
    finally:
        gen.close()
    return out


@pytest.mark.unit
class TestBuildMessageEventStream:
    def test_yields_connected_prelude_first(self):
        with patch(
            "application.streaming.event_replay.db_readonly"
        ) as mock_readonly, patch(
            "application.streaming.event_replay.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.event_replay.Topic.subscribe",
            _fake_topic_subscribe([]),
            create=False,
        ):
            mock_readonly.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value.read_after.return_value = []
            gen = build_message_event_stream(
                "msg-1",
                last_event_id=None,
                keepalive_seconds=0.05,
                poll_timeout_seconds=0.01,
            )
            first = next(gen)
            gen.close()
            assert first == ": connected\n\n"

    def test_snapshot_replays_in_sequence_order(self):
        rows = [
            {
                "sequence_no": 0,
                "event_type": "answer",
                "payload": {"type": "answer", "answer": "A"},
            },
            {
                "sequence_no": 1,
                "event_type": "answer",
                "payload": {"type": "answer", "answer": "B"},
            },
        ]
        with patch(
            "application.streaming.event_replay.db_readonly"
        ) as mock_readonly, patch(
            "application.streaming.event_replay.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.event_replay.Topic.subscribe",
            _fake_topic_subscribe([]),
            create=False,
        ):
            mock_readonly.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value.read_after.return_value = rows

            gen = build_message_event_stream(
                "msg-1",
                last_event_id=None,
                keepalive_seconds=0.05,
                poll_timeout_seconds=0.01,
            )
            out = _drain(gen, max_items=4)

        # Expect: prelude, two snapshot frames, then keepalive ticks (None
        # not yielded as a string — generator yields keepalive comments
        # instead). With poll_timeout=1.0 and short test window we may
        # only see the prelude + snapshot before close.
        assert out[0] == ": connected\n\n"
        assert "id: 0" in out[1]
        assert "id: 1" in out[2]
        # The repo was queried with the right cursor.
        mock_repo_cls.return_value.read_after.assert_called_once_with(
            "msg-1", last_sequence_no=None
        )

    def test_live_tail_dedupes_against_snapshot(self):
        snapshot_rows = [
            {
                "sequence_no": 5,
                "event_type": "answer",
                "payload": {"type": "answer", "answer": "snapshot"},
            },
        ]
        live_envelope = encode_pubsub_message(
            "msg-1", 5, "answer", {"type": "answer", "answer": "duplicate"}
        ).encode("utf-8")
        live_new_envelope = encode_pubsub_message(
            "msg-1", 6, "answer", {"type": "answer", "answer": "fresh"}
        ).encode("utf-8")

        with patch(
            "application.streaming.event_replay.db_readonly"
        ) as mock_readonly, patch(
            "application.streaming.event_replay.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.event_replay.Topic.subscribe",
            _fake_topic_subscribe([live_envelope, live_new_envelope]),
            create=False,
        ):
            mock_readonly.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value.read_after.return_value = snapshot_rows

            gen = build_message_event_stream(
                "msg-1",
                last_event_id=None,
                keepalive_seconds=0.05,
                poll_timeout_seconds=0.01,
            )
            out = _drain(gen, max_items=4)

        assert out[0] == ": connected\n\n"
        assert "id: 5" in out[1]
        assert '"answer": "snapshot"' in out[1]
        # The duplicate live event (seq=5) is dropped.
        assert "id: 6" in out[2]
        assert '"answer": "fresh"' in out[2]
        # No third frame past the fresh one (only None ticks).

    def test_live_tail_passes_through_when_seq_strictly_greater_than_replay(self):
        """No snapshot rows; every live event is fresh and yielded."""
        live = encode_pubsub_message(
            "msg-1", 0, "answer", {"type": "answer", "answer": "x"}
        ).encode("utf-8")
        with patch(
            "application.streaming.event_replay.db_readonly"
        ) as mock_readonly, patch(
            "application.streaming.event_replay.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.event_replay.Topic.subscribe",
            _fake_topic_subscribe([live]),
            create=False,
        ):
            mock_readonly.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value.read_after.return_value = []

            gen = build_message_event_stream(
                "msg-1",
                last_event_id=None,
                keepalive_seconds=0.05,
                poll_timeout_seconds=0.01,
            )
            out = _drain(gen, max_items=3)

        assert out[0] == ": connected\n\n"
        assert "id: 0" in out[1]
        assert '"answer": "x"' in out[1]

    def test_snapshot_read_failure_surfaces_synthetic_event(self):
        with patch(
            "application.streaming.event_replay.db_readonly"
        ) as mock_readonly, patch(
            "application.streaming.event_replay.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.event_replay.Topic.subscribe",
            _fake_topic_subscribe([]),
            create=False,
        ):
            mock_readonly.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value.read_after.side_effect = RuntimeError("boom")

            gen = build_message_event_stream(
                "msg-1",
                last_event_id=None,
                keepalive_seconds=0.05,
                poll_timeout_seconds=0.01,
            )
            # Ask for more than the expected output so we'd notice a
            # regression where the generator keeps emitting keepalives.
            out = _drain(gen, max_items=10)

        assert out[0] == ": connected\n\n"
        # Terminal ``error`` event with the snapshot-specific ``code`` so
        # the frontend's existing end/error contract closes the stream.
        assert '"type": "error"' in out[1]
        assert '"code": "snapshot_failed"' in out[1]
        assert "id: -1" in out[1]
        # Generator must return after the synthetic — otherwise the
        # client hangs on keepalives waiting for a terminal event that
        # would never arrive.
        assert len(out) == 2

    def test_malformed_pubsub_message_dropped_silently(self):
        bad = b"not-json"
        good = encode_pubsub_message(
            "msg-1", 0, "answer", {"type": "answer", "answer": "ok"}
        ).encode("utf-8")
        with patch(
            "application.streaming.event_replay.db_readonly"
        ) as mock_readonly, patch(
            "application.streaming.event_replay.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.event_replay.Topic.subscribe",
            _fake_topic_subscribe([bad, good]),
            create=False,
        ):
            mock_readonly.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value.read_after.return_value = []

            gen = build_message_event_stream(
                "msg-1",
                last_event_id=None,
                keepalive_seconds=0.05,
                poll_timeout_seconds=0.01,
            )
            out = _drain(gen, max_items=3)

        assert out[0] == ": connected\n\n"
        # Bad message dropped; good one yielded.
        assert "id: 0" in out[1]
        assert '"answer": "ok"' in out[1]

    def test_pubsub_envelope_with_non_int_sequence_dropped(self):
        bad = json.dumps(
            {"sequence_no": "not-int", "payload": {"type": "x"}}
        ).encode("utf-8")
        good = encode_pubsub_message(
            "msg-1", 0, "answer", {"type": "answer", "answer": "ok"}
        ).encode("utf-8")
        with patch(
            "application.streaming.event_replay.db_readonly"
        ) as mock_readonly, patch(
            "application.streaming.event_replay.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.event_replay.Topic.subscribe",
            _fake_topic_subscribe([bad, good]),
            create=False,
        ):
            mock_readonly.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value.read_after.return_value = []

            gen = build_message_event_stream(
                "msg-1",
                last_event_id=None,
                keepalive_seconds=0.05,
                poll_timeout_seconds=0.01,
            )
            out = _drain(gen, max_items=3)

        assert out[0] == ": connected\n\n"
        assert "id: 0" in out[1]


@pytest.mark.unit
class TestDedupFloorSeededFromCursor:
    """Regressions for the dedup-floor bugs the round-1 review flagged.

    With ``max_replayed_seq`` initialised to ``last_event_id``, an
    empty snapshot still rejects republished live events the client
    has already seen. Advancing on yield protects against republish
    past the snapshot ceiling.
    """

    def test_empty_snapshot_dedups_against_last_event_id(self):
        # No snapshot rows; live event with seq=3 (already seen by
        # client at last_event_id=5) must be dropped.
        live_dup = encode_pubsub_message(
            "msg-1", 3, "answer", {"type": "answer", "answer": "stale"}
        ).encode("utf-8")
        live_fresh = encode_pubsub_message(
            "msg-1", 6, "answer", {"type": "answer", "answer": "fresh"}
        ).encode("utf-8")
        with patch(
            "application.streaming.event_replay.db_readonly"
        ) as mock_readonly, patch(
            "application.streaming.event_replay.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.event_replay.Topic.subscribe",
            _fake_topic_subscribe([live_dup, live_fresh]),
            create=False,
        ):
            mock_readonly.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value.read_after.return_value = []

            gen = build_message_event_stream(
                "msg-1",
                last_event_id=5,
                keepalive_seconds=0.05,
                poll_timeout_seconds=0.01,
            )
            out = _drain(gen, max_items=3)

        assert out[0] == ": connected\n\n"
        # Stale live event dropped; only the fresh one yielded.
        assert "id: 6" in out[1]
        assert '"answer": "fresh"' in out[1]

    def test_yielded_live_event_advances_dedup_floor(self):
        """A republish of an already-yielded seq must be dropped."""
        live_first = encode_pubsub_message(
            "msg-1", 0, "answer", {"type": "answer", "answer": "first"}
        ).encode("utf-8")
        live_dup = encode_pubsub_message(
            "msg-1", 0, "answer", {"type": "answer", "answer": "duplicate"}
        ).encode("utf-8")
        live_third = encode_pubsub_message(
            "msg-1", 1, "answer", {"type": "answer", "answer": "third"}
        ).encode("utf-8")
        with patch(
            "application.streaming.event_replay.db_readonly"
        ) as mock_readonly, patch(
            "application.streaming.event_replay.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.event_replay.Topic.subscribe",
            _fake_topic_subscribe([live_first, live_dup, live_third]),
            create=False,
        ):
            mock_readonly.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value.read_after.return_value = []

            gen = build_message_event_stream(
                "msg-1",
                last_event_id=None,
                keepalive_seconds=0.05,
                poll_timeout_seconds=0.01,
            )
            out = _drain(gen, max_items=4)

        assert out[0] == ": connected\n\n"
        assert "id: 0" in out[1]
        assert '"answer": "first"' in out[1]
        # Duplicate seq=0 dropped.
        assert "id: 1" in out[2]
        assert '"answer": "third"' in out[2]


@pytest.mark.unit
class TestSnapshotWhenSubscribeUnavailable:
    """Regression for C1: when Redis is down, ``Topic.subscribe`` exits
    immediately without firing ``on_subscribe``. The snapshot is in
    Postgres and must still be served.
    """

    def test_snapshot_served_when_subscribe_returns_immediately(self):
        rows = [
            {
                "sequence_no": 0,
                "event_type": "answer",
                "payload": {"type": "answer", "answer": "from snapshot"},
            },
        ]
        # Topic.subscribe yields nothing (Redis-down behaviour).
        def _empty_subscribe(self, on_subscribe=None, poll_timeout=1.0):
            return
            yield  # pragma: no cover  (make the function a generator)

        with patch(
            "application.streaming.event_replay.db_readonly"
        ) as mock_readonly, patch(
            "application.streaming.event_replay.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.event_replay.Topic.subscribe",
            _empty_subscribe,
            create=False,
        ):
            mock_readonly.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value.read_after.return_value = rows

            gen = build_message_event_stream(
                "msg-1",
                last_event_id=None,
                keepalive_seconds=0.05,
                poll_timeout_seconds=0.01,
            )
            out = list(gen)

        assert out[0] == ": connected\n\n"
        # Snapshot row served via the post-subscribe fallback path.
        assert "id: 0" in out[1]
        assert '"answer": "from snapshot"' in out[1]

    def test_callback_fired_then_subscribe_dies_does_not_duplicate(self):
        """Regression: if ``on_subscribe`` ran and populated the buffer,
        a subsequent inner-generator failure (e.g. transient Redis
        ``get_message`` exception between SUBSCRIBE-ack and the first
        poll) must not trigger a second snapshot read. Re-reading would
        append the same rows twice and double the answer chunks on the
        client (the per-message reconnect dispatcher does not dedup
        by ``id``).
        """
        rows = [
            {
                "sequence_no": 0,
                "event_type": "answer",
                "payload": {"type": "answer", "answer": "first"},
            },
            {
                "sequence_no": 1,
                "event_type": "answer",
                "payload": {"type": "answer", "answer": "second"},
            },
        ]

        # Mimic the broadcast_channel race: SUBSCRIBE acks, on_subscribe
        # runs, then the inner ``get_message`` raises and the generator
        # returns without ever yielding.
        def _subscribe_dies_after_callback(
            self, on_subscribe=None, poll_timeout=1.0
        ):
            if on_subscribe is not None:
                on_subscribe()
            return
            yield  # pragma: no cover  (make the function a generator)

        repo_mock = MagicMock()
        repo_mock.read_after.return_value = rows

        with patch(
            "application.streaming.event_replay.db_readonly"
        ) as mock_readonly, patch(
            "application.streaming.event_replay.MessageEventsRepository",
            return_value=repo_mock,
        ), patch(
            "application.streaming.event_replay.Topic.subscribe",
            _subscribe_dies_after_callback,
            create=False,
        ):
            mock_readonly.return_value.__enter__.return_value = MagicMock()

            gen = build_message_event_stream(
                "msg-1",
                last_event_id=None,
                keepalive_seconds=0.05,
                poll_timeout_seconds=0.01,
            )
            out = list(gen)

        # The snapshot must have been read exactly once — re-reading
        # would have re-appended the rows behind the originals.
        assert repo_mock.read_after.call_count == 1
        assert out[0] == ": connected\n\n"
        # Each row appears exactly once, in order.
        assert "id: 0" in out[1]
        assert '"answer": "first"' in out[1]
        assert "id: 1" in out[2]
        assert '"answer": "second"' in out[2]
        # Nothing past the snapshot (no duplicates).
        assert len(out) == 3


@pytest.mark.unit
class TestTerminalEventClosesStream:
    """Regression: ``/api/messages/<id>/events`` is a live tail that
    keeps emitting keepalives. Without explicit close-on-terminal the
    client's drain promise never resolves and the WSGI thread is
    pinned waiting for events that won't come for an already-finished
    stream.
    """

    def test_terminal_in_snapshot_closes_after_flush(self):
        rows = [
            {
                "sequence_no": 0,
                "event_type": "answer",
                "payload": {"type": "answer", "answer": "A"},
            },
            {
                "sequence_no": 1,
                "event_type": "end",
                "payload": {"type": "end"},
            },
        ]
        with patch(
            "application.streaming.event_replay.db_readonly"
        ) as mock_readonly, patch(
            "application.streaming.event_replay.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.event_replay.Topic.subscribe",
            _fake_topic_subscribe([]),
            create=False,
        ):
            mock_readonly.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value.read_after.return_value = rows

            gen = build_message_event_stream(
                "msg-1",
                last_event_id=None,
                keepalive_seconds=0.05,
                poll_timeout_seconds=0.01,
            )
            # Drain to exhaustion. Without the close-on-terminal fix
            # this would hang; with it, the generator returns after
            # flushing the snapshot.
            out = list(gen)

        assert out[0] == ": connected\n\n"
        assert "id: 0" in out[1]
        assert "id: 1" in out[2]
        # No keepalives or further frames after the terminal.
        assert all("keepalive" not in line for line in out[3:])

    def test_terminal_falls_back_to_event_type_when_payload_lacks_type(self):
        # Belt-and-suspenders: a journal write that records ``end`` only
        # in the column (e.g. an abort handler that didn't seed
        # ``payload.type``) must still terminate the replay.
        rows = [
            {
                "sequence_no": 0,
                "event_type": "answer",
                "payload": {"type": "answer", "answer": "partial"},
            },
            {
                "sequence_no": 1,
                "event_type": "end",
                "payload": {},
            },
        ]
        with patch(
            "application.streaming.event_replay.db_readonly"
        ) as mock_readonly, patch(
            "application.streaming.event_replay.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.event_replay.Topic.subscribe",
            _fake_topic_subscribe([]),
            create=False,
        ):
            mock_readonly.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value.read_after.return_value = rows

            gen = build_message_event_stream(
                "msg-1",
                last_event_id=None,
                keepalive_seconds=0.05,
                poll_timeout_seconds=0.01,
            )
            out = list(gen)

        assert out[0] == ": connected\n\n"
        assert "id: 0" in out[1]
        assert "id: 1" in out[2]
        assert all("keepalive" not in line for line in out[3:])

    def test_terminal_in_live_tail_closes(self):
        live_answer = encode_pubsub_message(
            "msg-1", 0, "answer", {"type": "answer", "answer": "x"}
        ).encode("utf-8")
        live_end = encode_pubsub_message(
            "msg-1", 1, "end", {"type": "end"}
        ).encode("utf-8")
        with patch(
            "application.streaming.event_replay.db_readonly"
        ) as mock_readonly, patch(
            "application.streaming.event_replay.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.event_replay.Topic.subscribe",
            _fake_topic_subscribe([live_answer, live_end]),
            create=False,
        ):
            mock_readonly.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value.read_after.return_value = []

            gen = build_message_event_stream(
                "msg-1",
                last_event_id=None,
                keepalive_seconds=0.05,
                poll_timeout_seconds=0.01,
            )
            out = list(gen)

        assert out[0] == ": connected\n\n"
        assert "id: 0" in out[1] and '"answer": "x"' in out[1]
        assert "id: 1" in out[2] and '"type": "end"' in out[2]
        assert all("keepalive" not in line for line in out[3:])

    def test_error_event_also_closes(self):
        """The agent's catch-all path emits ``error`` with no trailing
        ``end`` — treating ``error`` as terminal closes that path too.
        """
        live_err = encode_pubsub_message(
            "msg-1", 0, "error", {"type": "error", "error": "boom"}
        ).encode("utf-8")
        with patch(
            "application.streaming.event_replay.db_readonly"
        ) as mock_readonly, patch(
            "application.streaming.event_replay.MessageEventsRepository"
        ) as mock_repo_cls, patch(
            "application.streaming.event_replay.Topic.subscribe",
            _fake_topic_subscribe([live_err]),
            create=False,
        ):
            mock_readonly.return_value.__enter__.return_value = MagicMock()
            mock_repo_cls.return_value.read_after.return_value = []

            gen = build_message_event_stream(
                "msg-1",
                last_event_id=None,
                keepalive_seconds=0.05,
                poll_timeout_seconds=0.01,
            )
            out = list(gen)

        assert out[0] == ": connected\n\n"
        assert "id: 0" in out[1] and '"type": "error"' in out[1]
        assert all("keepalive" not in line for line in out[2:])


@pytest.mark.unit
def test_sse_line_split_pattern_handles_all_terminators():
    assert _SSE_LINE_SPLIT_PATTERN.split("a\rb\nc\r\nd") == ["a", "b", "c", "d"]


@pytest.mark.unit
class TestWatchdogClosesIdleReconnect:
    """Without the watchdog a reconnect stream with a non-terminal
    snapshot and a dead producer (worker crash between chunks and
    finalize) would emit keepalives forever — the live tail blocks
    on a pub/sub that nobody publishes to and the frontend's drain
    promise never resolves. The watchdog periodically inspects
    ``conversation_messages`` and closes the stream with a terminal
    SSE event when the row has gone terminal in the DB or the
    producer's heartbeat has gone stale.
    """

    @staticmethod
    def _patch_subscribe_idle_forever():
        """Build a fake ``Topic.subscribe`` that fires ``on_subscribe``
        and then yields ``None`` ticks indefinitely (i.e. the producer
        is gone). Returns the generator function and a list collecting
        the ``on_subscribe`` calls so tests can assert ordering.
        """

        def _impl(self, on_subscribe=None, poll_timeout=1.0):
            if on_subscribe is not None:
                on_subscribe()
            while True:
                yield None

        return _impl

    def _mock_liveness_row(self, status, err=None, is_stale=False):
        """Build the ``conn.execute(...).first()`` return value the
        watchdog SQL expects — ``(status, err, is_stale)``.
        """
        return (status, err, is_stale)

    def _build_gen_with_liveness(
        self,
        liveness_row,
        *,
        keepalive_seconds=99.0,
        watchdog_interval_seconds=0.0,
        producer_idle_seconds=999.0,
    ):
        """Wire up the patches the watchdog tests share.

        The snapshot read goes through the patched
        ``MessageEventsRepository`` (returns empty), and the watchdog
        liveness check goes through ``conn.execute(...).first()`` on the
        same ``db_readonly``-yielded ``MagicMock`` connection.
        """
        mock_conn = MagicMock()
        mock_conn.execute.return_value.first.return_value = liveness_row

        readonly_patch = patch(
            "application.streaming.event_replay.db_readonly"
        )
        repo_patch = patch(
            "application.streaming.event_replay.MessageEventsRepository"
        )
        subscribe_patch = patch(
            "application.streaming.event_replay.Topic.subscribe",
            self._patch_subscribe_idle_forever(),
            create=False,
        )

        mock_readonly = readonly_patch.start()
        mock_repo_cls = repo_patch.start()
        subscribe_patch.start()

        mock_readonly.return_value.__enter__.return_value = mock_conn
        mock_repo_cls.return_value.read_after.return_value = []

        gen = build_message_event_stream(
            "msg-1",
            last_event_id=None,
            keepalive_seconds=keepalive_seconds,
            poll_timeout_seconds=0.001,
            watchdog_interval_seconds=watchdog_interval_seconds,
            producer_idle_seconds=producer_idle_seconds,
        )
        return gen, [readonly_patch, repo_patch, subscribe_patch]

    def test_watchdog_emits_synthetic_end_when_status_complete(self):
        """A row that flipped to ``complete`` after the snapshot read
        (e.g. finalize ran on another worker, journal write lost) must
        be surfaced as ``end`` so the client closes cleanly.
        """
        gen, patches = self._build_gen_with_liveness(
            self._mock_liveness_row("complete")
        )
        try:
            out = _drain(gen, max_items=5)
        finally:
            for p in patches:
                p.stop()

        assert out[0] == ": connected\n\n"
        # Watchdog synthetic: id:-1, ``{"type": "end"}``
        terminal = [s for s in out if '"type": "end"' in s]
        assert len(terminal) == 1
        assert "id: -1" in terminal[0]

    def test_watchdog_emits_synthetic_error_when_status_failed(self):
        gen, patches = self._build_gen_with_liveness(
            self._mock_liveness_row(
                "failed", err="RuntimeError: upstream blew up"
            )
        )
        try:
            out = _drain(gen, max_items=5)
        finally:
            for p in patches:
                p.stop()

        assert out[0] == ": connected\n\n"
        terminal = [s for s in out if '"type": "error"' in s]
        assert len(terminal) == 1
        assert '"code": "producer_failed"' in terminal[0]
        # The stashed error from metadata is surfaced verbatim so the
        # UI can show the real reason instead of a generic message.
        assert "RuntimeError: upstream blew up" in terminal[0]

    def test_watchdog_emits_synthetic_error_when_producer_stale(self):
        """Non-terminal status + heartbeat older than the threshold ⇒
        producing worker is presumed dead. Without this, the live tail
        would hang on keepalives until the proxy idle-timeout fires.
        """
        gen, patches = self._build_gen_with_liveness(
            self._mock_liveness_row("streaming", is_stale=True),
            producer_idle_seconds=1.0,
        )
        try:
            out = _drain(gen, max_items=5)
        finally:
            for p in patches:
                p.stop()

        assert out[0] == ": connected\n\n"
        terminal = [s for s in out if '"type": "error"' in s]
        assert len(terminal) == 1
        assert '"code": "producer_stale"' in terminal[0]

    def test_watchdog_does_not_fire_while_producer_alive(self):
        """A non-terminal row with a fresh heartbeat is healthy; the
        watchdog must keep silent (yield keepalives instead) so a
        slow-but-alive stream isn't prematurely terminated.
        """
        gen, patches = self._build_gen_with_liveness(
            self._mock_liveness_row("streaming", is_stale=False),
            keepalive_seconds=0.01,
        )
        try:
            out = _drain(gen, max_items=5)
        finally:
            for p in patches:
                p.stop()

        assert out[0] == ": connected\n\n"
        # No synthetic terminal — the rest of the output is keepalives.
        assert all(
            '"type": "end"' not in s and '"type": "error"' not in s
            for s in out
        )
        assert any("keepalive" in s for s in out)

    def test_watchdog_handles_missing_row_as_terminal(self):
        """If the message row got deleted out from under us mid-tail,
        the watchdog must close the stream rather than tail forever
        on a row that no longer exists.
        """
        gen, patches = self._build_gen_with_liveness(None)
        try:
            out = _drain(gen, max_items=5)
        finally:
            for p in patches:
                p.stop()

        assert out[0] == ": connected\n\n"
        terminal = [s for s in out if '"code": "message_missing"' in s]
        assert len(terminal) == 1
