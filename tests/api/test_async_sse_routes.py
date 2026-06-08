"""Tests for ``application/api/async_sse.py``.

Native-async reconnect endpoint: GET /api/messages/<id>/events. Auth gate,
ownership gate, malformed-id rejection, Last-Event-ID normalisation, and the
SSE response shape (headers + ``: connected`` prelude). The route is a
Starlette endpoint, so it's driven through Starlette's TestClient over a
minimal app built from ``async_sse_routes``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from application.api.async_sse import (
    _MESSAGE_ID_RE,
    _normalise_last_event_id,
    async_sse_routes,
)
from application.core.settings import settings

VALID_UUID = "67d65e8f-e7fb-4df1-9e6e-99ea6c830206"

_AUTH = "application.api.async_sse.handle_auth"
_OWNS = "application.api.async_sse._user_owns_message"
_STREAM = "application.api.async_sse.build_message_event_stream_async"
_AREDIS = "application.api.async_sse.get_async_redis_instance"


def _client() -> TestClient:
    return TestClient(Starlette(routes=async_sse_routes))


@pytest.fixture(autouse=True)
def _no_redis_by_default():
    """Disable the per-user cap (no Redis) so gate tests stay hermetic.

    Cap-specific tests override this with their own mock Redis.
    """
    with patch(_AREDIS, AsyncMock(return_value=None)):
        yield


def _mock_redis(incr_value: int) -> AsyncMock:
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=incr_value)
    redis.expire = AsyncMock(return_value=True)
    redis.decr = AsyncMock(return_value=incr_value - 1)
    return redis


def _fake_stream(record: dict | None = None):
    """Async builder stub: records the cursor, yields the prelude, returns."""

    async def _gen(message_id, last_event_id=None, **kwargs):
        if record is not None:
            record["message_id"] = message_id
            record["last_event_id"] = last_event_id
        yield ": connected\n\n"

    return _gen


# ── pure helpers ─────────────────────────────────────────────────────────


@pytest.mark.unit
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
        # snapshot-failure synthetic terminal event.
        assert _normalise_last_event_id("-1") is None

    def test_non_numeric_rejected(self):
        for bad in ("foo", "1.5", "1e3", "abc-123", "null"):
            assert _normalise_last_event_id(bad) is None, bad


@pytest.mark.unit
class TestMessageIdRegex:
    def test_canonical_uuid_accepted(self):
        assert _MESSAGE_ID_RE.match(VALID_UUID)

    def test_uppercase_uuid_accepted(self):
        assert _MESSAGE_ID_RE.match(VALID_UUID.upper())

    def test_no_dashes_rejected(self):
        assert not _MESSAGE_ID_RE.match(VALID_UUID.replace("-", ""))

    def test_legacy_mongo_id_rejected(self):
        assert not _MESSAGE_ID_RE.match("507f1f77bcf86cd799439011")


# ── auth gate ──────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestAuthGate:
    def test_401_when_handle_auth_returns_none(self):
        with patch(_AUTH, return_value=None):
            r = _client().get(f"/api/messages/{VALID_UUID}/events")
        assert r.status_code == 401

    def test_401_when_decoded_token_missing_sub(self):
        with patch(_AUTH, return_value={"email": "x@y"}):
            r = _client().get(f"/api/messages/{VALID_UUID}/events")
        assert r.status_code == 401

    def test_401_when_handle_auth_returns_error(self):
        with patch(_AUTH, return_value={"error": "invalid_token"}):
            r = _client().get(f"/api/messages/{VALID_UUID}/events")
        assert r.status_code == 401


# ── message-id validation ───────────────────────────────────────────────────


@pytest.mark.unit
class TestMessageIdValidation:
    def test_400_on_malformed_id(self):
        with patch(_AUTH, return_value={"sub": "alice"}):
            r = _client().get("/api/messages/not-a-uuid/events")
        assert r.status_code == 400


# ── ownership gate ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestOwnershipGate:
    def test_404_when_user_does_not_own_message(self):
        with patch(_AUTH, return_value={"sub": "alice"}), patch(
            _OWNS, return_value=False
        ):
            r = _client().get(f"/api/messages/{VALID_UUID}/events")
        assert r.status_code == 404

    def test_200_when_user_owns_message(self):
        with patch(_AUTH, return_value={"sub": "alice"}), patch(
            _OWNS, return_value=True
        ), patch(_STREAM, _fake_stream()):
            r = _client().get(f"/api/messages/{VALID_UUID}/events")
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("text/event-stream")
        assert r.headers.get("Cache-Control") == "no-store"
        assert r.headers.get("X-Accel-Buffering") == "no"
        assert r.headers.get("X-SSE-Transport") == "async"
        assert ": connected" in r.text


# ── Last-Event-ID parsing ───────────────────────────────────────────────────


@pytest.mark.unit
class TestLastEventIdParsing:
    def test_header_passes_through_to_builder(self):
        captured: dict = {}
        with patch(_AUTH, return_value={"sub": "alice"}), patch(
            _OWNS, return_value=True
        ), patch(_STREAM, _fake_stream(captured)):
            _client().get(
                f"/api/messages/{VALID_UUID}/events",
                headers={"Last-Event-ID": "12"},
            )
        assert captured["message_id"] == VALID_UUID
        assert captured["last_event_id"] == 12

    def test_query_param_fallback(self):
        captured: dict = {}
        with patch(_AUTH, return_value={"sub": "alice"}), patch(
            _OWNS, return_value=True
        ), patch(_STREAM, _fake_stream(captured)):
            _client().get(f"/api/messages/{VALID_UUID}/events?last_event_id=5")
        assert captured["last_event_id"] == 5

    def test_invalid_cursor_normalised_to_none(self):
        captured: dict = {}
        with patch(_AUTH, return_value={"sub": "alice"}), patch(
            _OWNS, return_value=True
        ), patch(_STREAM, _fake_stream(captured)):
            _client().get(
                f"/api/messages/{VALID_UUID}/events",
                headers={"Last-Event-ID": "definitely-not-a-number"},
            )
        assert captured["last_event_id"] is None


# ── per-user concurrent-connection cap ──────────────────────────────────────


@pytest.mark.unit
class TestConnectionCap:
    def _cap(self) -> int:
        return int(settings.SSE_MAX_CONCURRENT_PER_USER) or 8

    def test_429_when_over_cap(self):
        cap = self._cap()
        redis = _mock_redis(incr_value=cap + 1)  # post-incr count exceeds cap
        with patch(_AUTH, return_value={"sub": "alice"}), patch(
            _OWNS, return_value=True
        ), patch(_STREAM, _fake_stream()), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ):
            r = _client().get(f"/api/messages/{VALID_UUID}/events")
        assert r.status_code == 429
        # The increment is rolled back so a rejected attempt doesn't wedge
        # the counter at the cap forever.
        redis.decr.assert_awaited_once()

    def test_200_and_slot_released_when_under_cap(self):
        redis = _mock_redis(incr_value=1)
        with patch(_AUTH, return_value={"sub": "alice"}), patch(
            _OWNS, return_value=True
        ), patch(_STREAM, _fake_stream()), patch(
            _AREDIS, AsyncMock(return_value=redis)
        ):
            r = _client().get(f"/api/messages/{VALID_UUID}/events")
        assert r.status_code == 200
        assert ": connected" in r.text
        redis.incr.assert_awaited_once()
        # Slot released when the stream finishes (terminal/close).
        redis.decr.assert_awaited_once()

    def test_cap_skipped_when_redis_unavailable(self):
        # The autouse fixture already makes get_async_redis_instance -> None;
        # the stream is served (fail-open, like /api/events).
        with patch(_AUTH, return_value={"sub": "alice"}), patch(
            _OWNS, return_value=True
        ), patch(_STREAM, _fake_stream()):
            r = _client().get(f"/api/messages/{VALID_UUID}/events")
        assert r.status_code == 200
