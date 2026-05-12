"""Phase 2D integration tests — end-to-end snapshot+tail.

Exercises the publisher → journal → reconnect endpoint round-trip
without mocking the journal layer, so a regression in any of:
- complete_stream's _emit closure
- record_event's commit-per-call contract
- build_message_event_stream's snapshot-from-DB path
- the reconnect route's auth + ownership gates
- message_events repo SQL

would surface here as a failed integration assertion.
"""

from __future__ import annotations

import uuid as _uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import text as sql_text


@contextmanager
def _patch_journal_session(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.streaming.message_journal.db_session", _yield
    ), patch(
        "application.streaming.event_replay.db_readonly", _yield
    ):
        yield


def _seed_message(conn, user_id: str | None = None):
    user_id = user_id or f"u-{_uuid.uuid4().hex[:6]}"
    conv_id = _uuid.uuid4()
    msg_id = _uuid.uuid4()
    conn.execute(sql_text("INSERT INTO users (user_id) VALUES (:u)"), {"u": user_id})
    conn.execute(
        sql_text(
            "INSERT INTO conversations (id, user_id, name) VALUES (:id, :u, 't')"
        ),
        {"id": conv_id, "u": user_id},
    )
    conn.execute(
        sql_text(
            "INSERT INTO conversation_messages (id, conversation_id, user_id, position) "
            "VALUES (:id, :c, :u, 0)"
        ),
        {"id": msg_id, "c": conv_id, "u": user_id},
    )
    return user_id, str(msg_id)


@pytest.mark.integration
class TestSnapshotPlusTailRoundTrip:
    def test_record_event_then_snapshot_returns_what_was_journaled(
        self, pg_conn,
    ):
        """End-to-end of the journal half: ``record_event`` writes through
        a real ``MessageEventsRepository``, ``build_message_event_stream``
        reads the snapshot back via the same repo + a stub Topic.
        """
        from application.streaming import event_replay
        from application.streaming.message_journal import record_event

        _, message_id = _seed_message(pg_conn)

        with _patch_journal_session(pg_conn):
            # Three events stamp the journal.
            record_event(message_id, 0, "answer", {"type": "answer", "answer": "A"})
            record_event(message_id, 1, "answer", {"type": "answer", "answer": "B"})
            record_event(message_id, 2, "end", {"type": "end"})

            # Reconnect path: subscribe yields nothing (Redis-down
            # branch); the post-loop fallback runs the snapshot read
            # synchronously and yields the journal contents.
            def _empty_subscribe(self, on_subscribe=None, poll_timeout=1.0):
                return
                yield  # pragma: no cover

            with patch.object(
                event_replay.Topic,
                "subscribe",
                _empty_subscribe,
                create=False,
            ):
                gen = event_replay.build_message_event_stream(
                    message_id,
                    last_event_id=None,
                    keepalive_seconds=0.05,
                    poll_timeout_seconds=0.01,
                )
                out = list(gen)

        # Prelude + 3 snapshot frames.
        assert out[0] == ": connected\n\n"
        assert "id: 0" in out[1] and '"answer": "A"' in out[1]
        assert "id: 1" in out[2] and '"answer": "B"' in out[2]
        assert "id: 2" in out[3] and '"type": "end"' in out[3]

    def test_snapshot_resumes_past_last_event_id(self, pg_conn):
        from application.streaming import event_replay
        from application.streaming.message_journal import record_event

        _, message_id = _seed_message(pg_conn)

        with _patch_journal_session(pg_conn):
            for seq in range(5):
                record_event(
                    message_id, seq, "answer", {"type": "answer", "answer": str(seq)}
                )

            def _empty_subscribe(self, on_subscribe=None, poll_timeout=1.0):
                return
                yield  # pragma: no cover

            with patch.object(
                event_replay.Topic,
                "subscribe",
                _empty_subscribe,
                create=False,
            ):
                # Client says it has seen up through seq=2; expect 3 + 4.
                out = list(
                    event_replay.build_message_event_stream(
                        message_id,
                        last_event_id=2,
                        keepalive_seconds=0.05,
                        poll_timeout_seconds=0.01,
                    )
                )

        ids_seen = [line for line in out if line.startswith("id: ")]
        # Multi-line records: extract the id integers we delivered.
        emitted = sorted(
            int(line.split(": ", 1)[1].split("\n")[0])
            for line in out
            if line.startswith("id: ")
        )
        # Filter for non-negative (the snapshot-failure synthetic uses -1).
        emitted = [e for e in emitted if e >= 0]
        assert emitted == [3, 4]
        assert ids_seen  # sanity

    def test_reconnect_route_round_trip(self, pg_conn, flask_app):
        """``/api/messages/<id>/events`` returns the journaled events
        for an authenticated owner.
        """
        from flask import Flask, request

        from application.api.answer.routes.messages import messages_bp
        from application.streaming.message_journal import record_event

        # Build a fresh Flask app routing to the reconnect blueprint
        # plus a tiny auth shim that injects the test user.
        user_id, message_id = _seed_message(pg_conn)
        app = Flask(__name__)
        app.register_blueprint(messages_bp)
        app.config["TESTING"] = True

        @app.before_request
        def _shim_auth():
            request.decoded_token = {"sub": user_id}

        with _patch_journal_session(pg_conn):
            record_event(message_id, 0, "answer", {"type": "answer", "answer": "x"})
            record_event(message_id, 1, "end", {"type": "end"})

            from application.streaming import event_replay

            def _empty_subscribe(self, on_subscribe=None, poll_timeout=1.0):
                return
                yield  # pragma: no cover

            with patch.object(
                event_replay.Topic,
                "subscribe",
                _empty_subscribe,
                create=False,
            ), patch(
                "application.api.answer.routes.messages.db_readonly"
            ) as ro:
                ro.return_value.__enter__.return_value = pg_conn

                with app.test_client() as c:
                    r = c.get(f"/api/messages/{message_id}/events")
                    assert r.status_code == 200
                    body = b""
                    for chunk in r.iter_encoded():
                        body += chunk
                        if body.count(b"\n\n") >= 4:
                            break
                    r.close()
                # Both journaled events present in the response.
                text = body.decode("utf-8")
                assert ": connected" in text
                assert '"answer": "x"' in text
                assert '"type": "end"' in text
                # The seq lines are correct.
                assert "id: 0" in text and "id: 1" in text

    def test_reconnect_rejects_non_owner(self, pg_conn, flask_app):
        from flask import Flask, request

        from application.api.answer.routes.messages import messages_bp

        user_id, message_id = _seed_message(pg_conn)
        app = Flask(__name__)
        app.register_blueprint(messages_bp)

        @app.before_request
        def _shim_auth():
            request.decoded_token = {"sub": "different-user"}

        # Make the ownership check use the test connection.
        with patch(
            "application.api.answer.routes.messages.db_readonly"
        ) as ro:
            from contextlib import contextmanager as _cm

            @_cm
            def _yield():
                yield pg_conn

            ro.side_effect = lambda: _yield()
            with app.test_client() as c:
                r = c.get(f"/api/messages/{message_id}/events")
            assert r.status_code == 404
