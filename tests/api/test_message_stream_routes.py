"""Tests for ``application/api/answer/routes/messages.py``.

Phase 2 reconnect endpoint: GET /api/messages/<id>/events. Auth gate,
ownership gate, malformed-id rejection, Last-Event-ID normalisation,
and a smoke test that the SSE response shape matches the user-events
endpoint.
"""

from __future__ import annotations

from unittest.mock import patch

from flask import Flask, request

from application.api.answer.routes.messages import (
    _MESSAGE_ID_RE,
    _normalise_last_event_id,
    messages_bp,
)


def _make_app(decoded_token=None):
    app = Flask(__name__)
    app.register_blueprint(messages_bp)
    app.config["TESTING"] = True

    @app.before_request
    def _shim_auth():
        request.decoded_token = decoded_token

    return app


VALID_UUID = "67d65e8f-e7fb-4df1-9e6e-99ea6c830206"


class TestNormaliseLastEventId:
    def test_none_passthrough(self):
        assert _normalise_last_event_id(None) is None

    def test_empty_string(self):
        assert _normalise_last_event_id("") is None

    def test_whitespace_only(self):
        assert _normalise_last_event_id("   ") is None

    def test_valid_int(self):
        assert _normalise_last_event_id("42") == 42

    def test_stripped_whitespace(self):
        assert _normalise_last_event_id("  7  ") == 7

    def test_zero_is_valid(self):
        assert _normalise_last_event_id("0") == 0

    def test_negative_rejected(self):
        # We expose only non-negative cursors; -1 is reserved for the
        # snapshot-failure synthetic terminal event and shouldn't
        # round-trip back.
        assert _normalise_last_event_id("-1") is None

    def test_non_numeric_rejected(self):
        for bad in ("foo", "1.5", "1e3", "abc-123", "null"):
            assert _normalise_last_event_id(bad) is None, bad


class TestMessageIdRegex:
    def test_canonical_uuid_accepted(self):
        assert _MESSAGE_ID_RE.match(VALID_UUID)

    def test_uppercase_uuid_accepted(self):
        assert _MESSAGE_ID_RE.match(VALID_UUID.upper())

    def test_no_dashes_rejected(self):
        assert not _MESSAGE_ID_RE.match(VALID_UUID.replace("-", ""))

    def test_legacy_mongo_id_rejected(self):
        # 24-char hex with no dashes — a Mongo objectid-shaped string
        # that happened to leak through somewhere.
        assert not _MESSAGE_ID_RE.match("507f1f77bcf86cd799439011")


class TestAuthGate:
    def test_401_when_no_decoded_token(self):
        app = _make_app(decoded_token=None)
        with app.test_client() as c:
            r = c.get(f"/api/messages/{VALID_UUID}/events")
        assert r.status_code == 401

    def test_401_when_decoded_token_missing_sub(self):
        app = _make_app(decoded_token={"email": "x@y"})
        with app.test_client() as c:
            r = c.get(f"/api/messages/{VALID_UUID}/events")
        assert r.status_code == 401


class TestMessageIdValidation:
    def test_400_on_malformed_id(self):
        app = _make_app(decoded_token={"sub": "alice"})
        with app.test_client() as c:
            r = c.get("/api/messages/not-a-uuid/events")
        assert r.status_code == 400


class TestOwnershipGate:
    def test_404_when_user_does_not_own_message(self):
        from application.api.answer.routes import messages as messages_module

        app = _make_app(decoded_token={"sub": "alice"})
        with patch.object(
            messages_module, "_user_owns_message", return_value=False
        ):
            with app.test_client() as c:
                r = c.get(f"/api/messages/{VALID_UUID}/events")
        assert r.status_code == 404

    def test_200_when_user_owns_message(self):
        from application.api.answer.routes import messages as messages_module

        app = _make_app(decoded_token={"sub": "alice"})

        # Have build_message_event_stream yield just the prelude then
        # exit so the test can drain the response without blocking on
        # a live pubsub subscription.
        def _fake_builder(message_id, last_event_id=None, **kwargs):
            yield ": connected\n\n"

        with patch.object(
            messages_module, "_user_owns_message", return_value=True
        ), patch.object(
            messages_module, "build_message_event_stream", _fake_builder
        ):
            with app.test_client() as c:
                r = c.get(f"/api/messages/{VALID_UUID}/events")
                assert r.status_code == 200
                assert r.mimetype == "text/event-stream"
                assert r.headers.get("Cache-Control") == "no-store"
                assert r.headers.get("X-Accel-Buffering") == "no"
                body = b""
                for chunk in r.iter_encoded():
                    body += chunk
                    if b": connected" in body:
                        break
                r.close()
                assert b": connected" in body


class TestLastEventIdParsing:
    def test_header_passes_through_to_builder(self):
        from application.api.answer.routes import messages as messages_module

        captured = {}

        def _fake_builder(message_id, last_event_id=None, **kwargs):
            captured["message_id"] = message_id
            captured["last_event_id"] = last_event_id
            yield ": connected\n\n"

        app = _make_app(decoded_token={"sub": "alice"})
        with patch.object(
            messages_module, "_user_owns_message", return_value=True
        ), patch.object(
            messages_module, "build_message_event_stream", _fake_builder
        ):
            with app.test_client() as c:
                r = c.get(
                    f"/api/messages/{VALID_UUID}/events",
                    headers={"Last-Event-ID": "12"},
                )
                # Drain a tick.
                next(iter(r.iter_encoded()), None)
                r.close()
        assert captured["message_id"] == VALID_UUID
        assert captured["last_event_id"] == 12

    def test_query_param_fallback(self):
        from application.api.answer.routes import messages as messages_module

        captured = {}

        def _fake_builder(message_id, last_event_id=None, **kwargs):
            captured["last_event_id"] = last_event_id
            yield ": connected\n\n"

        app = _make_app(decoded_token={"sub": "alice"})
        with patch.object(
            messages_module, "_user_owns_message", return_value=True
        ), patch.object(
            messages_module, "build_message_event_stream", _fake_builder
        ):
            with app.test_client() as c:
                r = c.get(
                    f"/api/messages/{VALID_UUID}/events?last_event_id=5"
                )
                next(iter(r.iter_encoded()), None)
                r.close()
        assert captured["last_event_id"] == 5

    def test_invalid_cursor_normalised_to_none(self):
        from application.api.answer.routes import messages as messages_module

        captured = {}

        def _fake_builder(message_id, last_event_id=None, **kwargs):
            captured["last_event_id"] = last_event_id
            yield ": connected\n\n"

        app = _make_app(decoded_token={"sub": "alice"})
        with patch.object(
            messages_module, "_user_owns_message", return_value=True
        ), patch.object(
            messages_module, "build_message_event_stream", _fake_builder
        ):
            with app.test_client() as c:
                r = c.get(
                    f"/api/messages/{VALID_UUID}/events",
                    headers={"Last-Event-ID": "definitely-not-a-number"},
                )
                next(iter(r.iter_encoded()), None)
                r.close()
        assert captured["last_event_id"] is None
