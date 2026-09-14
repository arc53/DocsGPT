"""Tests for poll-issued session-ticket enforcement on the SSE upgrade.

Two layers:

* Broker unit tests for ``claim_ticket`` / ``validate_ticket`` /
  ``redeem_ticket`` (issue, match, mismatch, eviction, absence, single use).
* Route tests proving the real CLI loop still works: ``/poll`` (Flask) issues
  a ticket and the native-async stream accepts *that* ticket, while a
  mismatched ticket is rejected with ``410`` before any stream opens.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from flask import Flask
from starlette.applications import Starlette
from starlette.testclient import TestClient

from docsgpt.api.devices import auth as auth_module
from docsgpt.api.devices import session as session_module
from docsgpt.api.devices import session_events as session_events_module
from docsgpt.devices.broker import DeviceBroker

from .conftest import AsyncFakeRedis, FakeRedis


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


def test_redeem_ticket_opens_session_under_the_ticket(broker_env):
    broker, fake = broker_env
    _queue_work(broker)
    ticket = broker.claim_ticket("dev_x", 30)
    sess = broker.redeem_ticket("dev_x", "user_x", ticket)
    assert sess.session_id == ticket
    assert broker.get_session(ticket) is sess
    assert fake.get("dev:ticket:dev_x") is None


def test_redeem_ticket_succeeds_only_once(broker_env):
    # Two requests racing with one ticket: the loser must not open a session
    # that replaces the winner's live stream.
    broker, _fake = broker_env
    _queue_work(broker)
    ticket = broker.claim_ticket("dev_x", 30)
    first = broker.redeem_ticket("dev_x", "user_x", ticket)
    assert broker.redeem_ticket("dev_x", "user_x", ticket) is None
    assert not first.closed.is_set()
    assert broker._sessions_by_device["dev_x"] is first


def test_redeem_ticket_rejects_other_ticket_and_keeps_issued_one(broker_env):
    broker, fake = broker_env
    _queue_work(broker)
    ticket = broker.claim_ticket("dev_x", 30)
    assert broker.redeem_ticket("dev_x", "user_x", "st_not_the_one") is None
    assert broker.redeem_ticket("dev_x", "user_x", "") is None
    assert fake.get("dev:ticket:dev_x") == ticket.encode()
    assert "dev_x" not in broker._sessions_by_device


def test_redeem_ticket_rejects_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr("docsgpt.devices.broker.get_redis_instance", lambda: None)
    broker = DeviceBroker()
    assert broker.redeem_ticket("dev_x", "user_x", "st_anything") is None
    assert "dev_x" not in broker._sessions_by_device


# ---------------------------------------------------------------------------
# Route tests (poll -> SSE upgrade)
# ---------------------------------------------------------------------------
@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture(autouse=True)
def _short_idle(monkeypatch):
    # An idle stream ends on its own, so the test client returns.
    monkeypatch.setattr(
        session_events_module.settings, "REMOTE_DEVICE_SESSION_IDLE_SECONDS", 0.1
    )


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


def _open_stream(session_id: str):
    client = TestClient(Starlette(routes=session_events_module.device_session_routes))
    ctxs = _patched_auth()
    for c in ctxs:
        c.start()
    try:
        return client.get(
            f"/api/devices/sessions/{session_id}/events",
            headers={"Authorization": "Bearer tok_good"},
        )
    finally:
        for c in ctxs:
            c.stop()


def _broker_patches(fake: FakeRedis, broker: DeviceBroker):
    return [
        patch("docsgpt.devices.broker.get_redis_instance", return_value=fake),
        patch(
            "docsgpt.devices.broker.get_async_redis_instance",
            AsyncMock(return_value=AsyncFakeRedis(fake)),
        ),
        patch.object(session_module, "get_broker", return_value=broker),
        patch.object(session_events_module, "get_broker", return_value=broker),
    ]


@pytest.fixture
def wired_broker():
    fake = FakeRedis()
    broker = DeviceBroker()
    patches = _broker_patches(fake, broker)
    for p in patches:
        p.start()
    try:
        yield broker, fake
    finally:
        for p in patches:
            p.stop()


def test_poll_to_sse_upgrade_with_issued_ticket_works(app, wired_broker):
    """The legitimate loop: /poll issues a ticket, the stream accepts it."""
    broker, _fake = wired_broker
    # Queue work so /poll returns a ticket rather than 202.
    broker.dispatch_invocation(
        "dev_route", "user_route",
        {"invocation_id": "inv_a", "action": "run_command"},
    )
    poll_resp = _call(app, session_module.poll, "/api/devices/poll")
    assert poll_resp.status_code == 200
    payload = poll_resp.get_json()
    ticket = payload["session_ticket"]
    assert payload["session_url"] == f"/api/devices/sessions/{ticket}/events"
    assert payload["expires_in"] == 30

    # CLI opens the exact session_url it was handed.
    sse_resp = _open_stream(ticket)
    assert sse_resp.status_code == 200
    assert sse_resp.headers["content-type"].startswith("text/event-stream")
    assert "event: invocation" in sse_resp.text
    assert '"invocation_id": "inv_a"' in sse_resp.text


def test_session_events_rejects_mismatched_ticket(app, wired_broker):
    """A fabricated/mismatched session_id is 410 Gone, no stream opened."""
    broker, fake = wired_broker
    broker.dispatch_invocation(
        "dev_route", "user_route",
        {"invocation_id": "inv_b", "action": "run_command"},
    )
    # Poll issues the real ticket...
    _call(app, session_module.poll, "/api/devices/poll")
    issued = fake.get("dev:ticket:dev_route")
    # ...but the client opens a different one.
    resp = _open_stream("st_bogus")
    assert resp.status_code == 410
    assert resp.json()["error"] == "session_ticket_invalid"
    # No session registered, so the real ticket is still unclaimed.
    assert fake.get("dev:ticket:dev_route") == issued
    assert "dev_route" not in broker._sessions_by_device


def test_session_events_rejects_when_never_polled(wired_broker):
    """Opening the SSE stream without a prior poll is rejected (410)."""
    resp = _open_stream("st_anything")
    assert resp.status_code == 410
    assert resp.json()["error"] == "session_ticket_invalid"
