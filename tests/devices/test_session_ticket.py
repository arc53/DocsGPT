"""Tests for poll-issued session-ticket enforcement on the SSE upgrade.

Two layers:

* Broker unit tests for ``claim_ticket`` / ``validate_ticket`` (issue, match,
  mismatch, eviction, absence).
* Route tests proving the real CLI loop still works: ``/poll`` issues a
  ticket and ``session_events`` accepts *that* ticket, while a mismatched
  ticket is rejected with ``410`` before any stream opens.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from flask import Flask

from application.api.devices import auth as auth_module
from application.api.devices import session as session_module
from application.devices.broker import DeviceBroker

from .conftest import FakeRedis


# ---------------------------------------------------------------------------
# Broker unit tests
# ---------------------------------------------------------------------------
def _queue_work(broker: DeviceBroker, device_id: str = "dev_x") -> None:
    # Queuing a command (no draining session) is what makes claim_ticket
    # hand out a ticket: the device's command list is non-empty.
    broker.dispatch_invocation(
        device_id, "user_x", {"invocation_id": "inv_1", "action": "run_command"}
    )


def test_claim_ticket_none_when_no_work(broker_env):
    broker, _fake = broker_env
    assert broker.claim_ticket("dev_x", 30) is None


def test_validate_accepts_issued_ticket(broker_env):
    broker, _fake = broker_env
    _queue_work(broker)
    ticket = broker.claim_ticket("dev_x", 30)
    assert ticket is not None
    assert broker.validate_ticket("dev_x", ticket) is True


def test_validate_rejects_wrong_ticket(broker_env):
    broker, _fake = broker_env
    _queue_work(broker)
    broker.claim_ticket("dev_x", 30)
    assert broker.validate_ticket("dev_x", "st_not_the_one") is False


def test_validate_rejects_when_no_ticket_issued(broker_env):
    broker, _fake = broker_env
    assert broker.validate_ticket("dev_x", "st_anything") is False


def test_validate_rejects_empty_session_id(broker_env):
    broker, _fake = broker_env
    _queue_work(broker)
    broker.claim_ticket("dev_x", 30)
    assert broker.validate_ticket("dev_x", "") is False


def test_validate_rejects_after_ticket_evicted(broker_env):
    # Redis enforces the TTL; once the ticket key is gone (expired/evicted),
    # validate can't resurrect it.
    broker, fake = broker_env
    _queue_work(broker)
    ticket = broker.claim_ticket("dev_x", 30)
    fake.delete("dev:ticket:dev_x")  # simulate TTL expiry
    assert broker.validate_ticket("dev_x", ticket) is False


def test_claim_ticket_reused_while_unexpired(broker_env):
    broker, _fake = broker_env
    _queue_work(broker)
    first = broker.claim_ticket("dev_x", 30)
    second = broker.claim_ticket("dev_x", 30)
    assert first == second


def test_register_session_consumes_issued_ticket_as_session_id(broker_env):
    # The issued ticket becomes the session_id, so the URL the CLI opens
    # (= the ticket) matches the live session.
    broker, fake = broker_env
    _queue_work(broker)
    ticket = broker.claim_ticket("dev_x", 30)
    sess = broker.register_session("dev_x", "user_x")
    assert sess.session_id == ticket
    # Ticket is consumed on registration.
    assert fake.get("dev:ticket:dev_x") is None


# ---------------------------------------------------------------------------
# Route tests (poll -> SSE upgrade)
# ---------------------------------------------------------------------------
@pytest.fixture
def app():
    return Flask(__name__)


def _device_row() -> dict:
    return {
        "id": "dev_route",
        "user_id": "user_route",
        "name": "laptop",
        "status": "active",
        "approval_mode": "ask",
        "machine_pubkey_fingerprint": "fp",
        "token_hash": "tokhash",
    }


class _Repo:
    def __init__(self, _conn):
        pass

    def find_by_token_hash(self, _token_hash):
        return _device_row()

    def touch_last_seen(self, _device_id):
        pass


class _Ctx:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


def _patched_auth():
    return [
        patch.object(auth_module, "DevicesRepository", _Repo),
        patch.object(auth_module, "db_readonly", _Ctx),
        patch.object(auth_module, "db_session", _Ctx),
    ]


def _call(app: Flask, view, path: str, *args):
    with app.test_request_context(
        path, method="GET", headers={"Authorization": "Bearer tok_good"}
    ):
        ctxs = _patched_auth()
        for c in ctxs:
            c.start()
        try:
            return view(*args)
        finally:
            for c in ctxs:
                c.stop()


def test_poll_to_sse_upgrade_with_issued_ticket_works(app):
    """The legitimate loop: /poll issues a ticket, session_events accepts it."""
    fake = FakeRedis()
    broker = DeviceBroker()
    with patch("application.devices.broker.get_redis_instance", return_value=fake):
        # Queue work so /poll returns a ticket rather than 202.
        broker.dispatch_invocation(
            "dev_route", "user_route",
            {"invocation_id": "inv_a", "action": "run_command"},
        )
        with patch.object(session_module, "get_broker", return_value=broker):
            poll_resp = _call(app, session_module.poll, "/api/devices/poll")
            assert poll_resp.status_code == 200
            payload = poll_resp.get_json()
            ticket = payload["session_ticket"]
            assert payload["session_url"] == f"/api/devices/sessions/{ticket}/events"
            assert payload["expires_in"] == 30

            # CLI opens the exact session_url it was handed.
            sse_resp = _call(
                app,
                session_module.session_events,
                f"/api/devices/sessions/{ticket}/events",
                ticket,
            )
            try:
                assert sse_resp.status_code == 200
                assert sse_resp.mimetype == "text/event-stream"
            finally:
                sse_resp.close()


def test_session_events_rejects_mismatched_ticket(app):
    """A fabricated/mismatched session_id is 410 Gone, no stream opened."""
    fake = FakeRedis()
    broker = DeviceBroker()
    with patch("application.devices.broker.get_redis_instance", return_value=fake):
        broker.dispatch_invocation(
            "dev_route", "user_route",
            {"invocation_id": "inv_b", "action": "run_command"},
        )
        with patch.object(session_module, "get_broker", return_value=broker):
            # Poll issues the real ticket...
            _call(app, session_module.poll, "/api/devices/poll")
            # ...but the client opens a different one.
            resp = _call(
                app,
                session_module.session_events,
                "/api/devices/sessions/st_bogus/events",
                "st_bogus",
            )
    assert resp.status_code == 410
    assert resp.get_json()["error"] == "session_ticket_invalid"


def test_session_events_rejects_when_never_polled(app):
    """Opening the SSE stream without a prior poll is rejected (410)."""
    fake = FakeRedis()
    broker = DeviceBroker()
    with patch("application.devices.broker.get_redis_instance", return_value=fake):
        with patch.object(session_module, "get_broker", return_value=broker):
            resp = _call(
                app,
                session_module.session_events,
                "/api/devices/sessions/st_anything/events",
                "st_anything",
            )
    assert resp.status_code == 410
    assert resp.get_json()["error"] == "session_ticket_invalid"
