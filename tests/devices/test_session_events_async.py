"""Tests for the native-async device SSE stream.

``GET /api/devices/sessions/{session_id}/events`` runs on the event loop: the
device-token check runs in a worker thread, commands arrive through the
broker's async ``BLPOP``, and an idle stream holds no thread. Streams here end
on their own (idle timeout, superseded session, shutdown) so the client
returns; a mid-stream disconnect goes through ``tests/asgi_stream.py``.
Ticket rejection (410) and the poll→stream loop live in test_session_ticket.py.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from types import SimpleNamespace

import pytest
from flask import Flask
from starlette.applications import Starlette
from starlette.testclient import TestClient

from docsgpt.api.devices import auth as auth_module
from docsgpt.api.devices import session_events as events_module
from docsgpt.core.shutdown import begin_shutdown, reset_shutdown
from tests.asgi_stream import stream_then_disconnect

from .conftest import AsyncFakeRedis

TOKEN = "tok_good"
DEVICE = {
    "id": "dev_async",
    "user_id": "user_async",
    "name": "laptop",
    "status": "active",
    "approval_mode": "ask",
    "machine_pubkey_fingerprint": "fp",
}
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class _Ctx:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _baseline(monkeypatch):
    monkeypatch.setattr(events_module.settings, "SSE_KEEPALIVE_SECONDS", 15)
    monkeypatch.setattr(events_module.settings, "REMOTE_DEVICE_SESSION_IDLE_SECONDS", 0.2)
    monkeypatch.setattr(auth_module.settings, "REMOTE_DEVICE_REQUIRE_SIGNATURE", False)
    reset_shutdown()
    yield
    reset_shutdown()


@pytest.fixture
def device(monkeypatch):
    """Resolve ``TOKEN`` to a device row without Postgres; other tokens are unknown."""
    row = dict(DEVICE)
    touched: list = []

    class _Repo:
        def __init__(self, _conn):
            pass

        def find_by_token_hash(self, token_hash):
            return row if token_hash == auth_module.hash_session_token(TOKEN) else None

        def touch_last_seen(self, device_id):
            touched.append(device_id)

    monkeypatch.setattr(auth_module, "DevicesRepository", _Repo)
    monkeypatch.setattr(auth_module, "db_readonly", _Ctx)
    monkeypatch.setattr(auth_module, "db_session", _Ctx)
    return SimpleNamespace(row=row, touched=touched)


@pytest.fixture
def broker(async_broker_env, monkeypatch):
    broker, fake = async_broker_env
    monkeypatch.setattr(events_module, "get_broker", lambda: broker)
    return broker, fake


def _app() -> Starlette:
    return Starlette(routes=events_module.device_session_routes)


def _path(session_id: str) -> str:
    return f"/api/devices/sessions/{session_id}/events"


def _open(session_id: str, headers: dict | None = None):
    return TestClient(_app()).get(_path(session_id), headers=headers if headers is not None else AUTH)


def _queue(broker, invocation_id: str = "inv_1") -> None:
    broker.dispatch_invocation(
        DEVICE["id"],
        DEVICE["user_id"],
        {"invocation_id": invocation_id, "action": "run_command", "command": "ls"},
    )


def _ticket(broker, invocation_id: str = "inv_1") -> str:
    _queue(broker, invocation_id)
    return broker.claim_ticket(DEVICE["id"], 30)


def _records(body: str) -> list[dict]:
    """Parse SSE records into ``{event, id, data}`` dicts, dropping comments."""
    out = []
    for block in body.split("\n\n"):
        fields = {}
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            name, _, value = line.partition(": ")
            fields[name] = value
        if fields:
            if "data" in fields:
                fields["data"] = json.loads(fields["data"])
            out.append(fields)
    return out


# ── auth ────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestAuth:
    def test_401_without_token(self, device, broker):
        r = _open("st_x", headers={})
        assert r.status_code == 401
        assert r.json() == {"success": False, "error": "missing_token"}

    def test_401_for_unknown_token(self, device, broker):
        r = _open("st_x", headers={"Authorization": "Bearer tok_other"})
        assert r.status_code == 401
        assert r.json() == {"success": False, "error": "invalid_token"}

    def test_valid_token_touches_last_seen(self, device, broker):
        b, _ = broker
        ticket = _ticket(b)
        assert _open(ticket).status_code == 200
        assert device.touched == [DEVICE["id"]]


# ── stream ──────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestStream:
    def test_delivers_queued_invocation_then_ends_idle_session(self, device, broker):
        b, fake = broker
        ticket = _ticket(b)
        r = _open(ticket)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"] == "no-cache"
        assert r.headers["x-accel-buffering"] == "no"
        records = _records(r.text)
        assert [rec["event"] for rec in records] == ["invocation", "session_end"]
        assert records[0]["id"] == "1"
        assert records[0]["data"]["invocation_id"] == "inv_1"
        assert records[0]["data"]["command"] == "ls"
        assert records[1]["id"] == "2"
        assert records[1]["data"] == {"reason": "inactivity_timeout"}
        # The ticket became the session id and the session is gone once the stream ends.
        assert fake.get(f"dev:ticket:{DEVICE['id']}") is None
        assert b.get_session(ticket) is None

    def test_delivers_commands_in_queue_order(self, device, broker):
        b, _ = broker
        ticket = _ticket(b, "inv_1")
        _queue(b, "inv_2")
        records = _records(_open(ticket).text)
        invocations = [rec for rec in records if rec["event"] == "invocation"]
        assert [rec["data"]["invocation_id"] for rec in invocations] == ["inv_1", "inv_2"]
        assert [rec["id"] for rec in records] == ["1", "2", "3"]

    def test_heartbeat_comment_while_idle(self, device, broker, monkeypatch):
        monkeypatch.setattr(events_module.settings, "SSE_KEEPALIVE_SECONDS", 0.05)
        monkeypatch.setattr(events_module.settings, "REMOTE_DEVICE_SESSION_IDLE_SECONDS", 0.3)
        b, _ = broker
        r = _open(_ticket(b))
        assert ": heartbeat\n\n" in r.text

    def test_reaped_invocation_is_not_delivered(self, device, broker):
        b, fake = broker
        ticket = _ticket(b)
        fake.delete("dev:inv:inv_1")
        records = _records(_open(ticket).text)
        assert [rec["event"] for rec in records] == ["session_end"]
        assert records[0]["id"] == "1"

    def test_output_activity_keeps_session_alive(self, device, broker, monkeypatch):
        # submit_output_chunk (a Flask thread) bumps last_activity_at; the async
        # idle check must read it rather than a stale copy.
        monkeypatch.setattr(events_module.settings, "REMOTE_DEVICE_SESSION_IDLE_SECONDS", 0.3)
        b, _ = broker
        ticket = _ticket(b)
        original = b.next_command_async
        started = time.time()

        async def _poll_while_output_flows(sess, timeout=1.0):
            if time.time() - started < 0.6:
                sess.last_activity_at = time.time()
            return await original(sess, timeout=timeout)

        monkeypatch.setattr(b, "next_command_async", _poll_while_output_flows)
        r = _open(ticket)
        assert time.time() - started >= 0.6
        assert [rec["event"] for rec in _records(r.text)] == ["invocation", "session_end"]


@pytest.mark.unit
@pytest.mark.asyncio
class TestStreamLifecycle:
    async def test_reconnect_ends_superseded_stream_and_keeps_new_session(
        self, device, broker, monkeypatch
    ):
        monkeypatch.setattr(events_module.settings, "REMOTE_DEVICE_SESSION_IDLE_SECONDS", 30)
        b, _ = broker
        ticket = _ticket(b)
        replacement: dict = {}
        original = b.next_command_async

        async def _reconnect_then_poll(sess, timeout=1.0):
            envelope = await original(sess, timeout=timeout)
            if not replacement:
                # The CLI reconnected on another request: its session replaces this one.
                replacement["sess"] = b.register_session(DEVICE["id"], DEVICE["user_id"])
            return envelope

        monkeypatch.setattr(b, "next_command_async", _reconnect_then_poll)
        status, _, chunks = await stream_then_disconnect(
            _app(), _path(ticket), headers=AUTH, chunks_before_disconnect=10**6, timeout=3
        )
        assert status == 200
        assert [rec["event"] for rec in _records(b"".join(chunks).decode())] == ["invocation"]
        assert b.get_session(ticket) is None
        assert b.get_session(replacement["sess"].session_id) is replacement["sess"]

    async def test_shutdown_ends_stream(self, device, broker, monkeypatch):
        monkeypatch.setattr(events_module.settings, "REMOTE_DEVICE_SESSION_IDLE_SECONDS", 30)
        b, _ = broker
        ticket = _ticket(b)
        begin_shutdown()
        status, _, chunks = await stream_then_disconnect(
            _app(), _path(ticket), headers=AUTH, chunks_before_disconnect=10**6, timeout=3
        )
        assert status == 200
        assert b"".join(chunks) == b""
        assert b.get_session(ticket) is None

    async def test_client_disconnect_closes_session(self, device, broker, monkeypatch):
        monkeypatch.setattr(events_module.settings, "REMOTE_DEVICE_SESSION_IDLE_SECONDS", 30)
        b, _ = broker
        ticket = _ticket(b)
        status, _, chunks = await stream_then_disconnect(
            _app(), _path(ticket), headers=AUTH, chunks_before_disconnect=1, timeout=3
        )
        assert status == 200
        assert chunks[0].startswith(b"event: invocation\n")
        assert b.get_session(ticket) is None
        assert DEVICE["id"] not in b._sessions_by_device


# ── machine-key signatures ──────────────────────────────────────────────


def _signed_headers(path: str, *, sign_path: str | None = None) -> tuple[str, dict]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    raw_pub = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    fingerprint = hashlib.sha256(raw_pub).hexdigest()
    ts = str(int(time.time()))
    payload = auth_module._canonical_payload("GET", sign_path or path, ts, b"")
    headers = {
        **AUTH,
        "X-Device-Signature": base64.b64encode(key.sign(payload.encode("utf-8"))).decode(),
        "X-Device-Timestamp": ts,
        "X-Device-Machine-Key": fingerprint,
        "X-Device-Machine-Pubkey": base64.b64encode(raw_pub).decode(),
    }
    return fingerprint, headers


@pytest.mark.unit
class TestSignature:
    def test_signed_stream_request_accepted(self, device, broker, monkeypatch):
        monkeypatch.setattr(auth_module.settings, "REMOTE_DEVICE_REQUIRE_SIGNATURE", True)
        b, _ = broker
        ticket = _ticket(b)
        fingerprint, headers = _signed_headers(_path(ticket))
        device.row["machine_pubkey_fingerprint"] = fingerprint
        r = _open(ticket, headers=headers)
        assert r.status_code == 200
        assert "event: invocation" in r.text

    def test_signature_for_another_path_rejected(self, device, broker, monkeypatch):
        monkeypatch.setattr(auth_module.settings, "REMOTE_DEVICE_REQUIRE_SIGNATURE", True)
        b, fake = broker
        ticket = _ticket(b)
        fingerprint, headers = _signed_headers(_path(ticket), sign_path="/api/devices/poll")
        device.row["machine_pubkey_fingerprint"] = fingerprint
        r = _open(ticket, headers=headers)
        assert r.status_code == 401
        assert r.json() == {"success": False, "error": "invalid_signature"}
        # Rejected before the session opened: the ticket is still unclaimed.
        assert fake.get(f"dev:ticket:{DEVICE['id']}") == ticket.encode()

    def test_missing_signature_rejected(self, device, broker, monkeypatch):
        monkeypatch.setattr(auth_module.settings, "REMOTE_DEVICE_REQUIRE_SIGNATURE", True)
        b, _ = broker
        r = _open(_ticket(b))
        assert r.status_code == 401
        assert r.json() == {"success": False, "error": "missing_signature"}


# ── broker async poll ───────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
class TestNextCommandAsync:
    async def test_returns_queued_envelope(self, async_broker_env):
        b, _ = async_broker_env
        _queue(b)
        sess = b.register_session(DEVICE["id"], DEVICE["user_id"])
        envelope = await b.next_command_async(sess, timeout=0.01)
        assert envelope["invocation_id"] == "inv_1"

    async def test_none_when_queue_empty(self, async_broker_env):
        b, _ = async_broker_env
        sess = b.register_session(DEVICE["id"], DEVICE["user_id"])
        assert await b.next_command_async(sess, timeout=0.01) is None

    @pytest.mark.parametrize("raw", [b"not json", b'["not", "a", "dict"]'])
    async def test_drops_malformed_envelope(self, async_broker_env, raw):
        b, fake = async_broker_env
        fake.rpush(f"dev:cmd:{DEVICE['id']}", raw)
        sess = b.register_session(DEVICE["id"], DEVICE["user_id"])
        assert await b.next_command_async(sess, timeout=0.01) is None
        assert fake.llen(f"dev:cmd:{DEVICE['id']}") == 0

    async def test_drops_reaped_invocation(self, async_broker_env):
        b, fake = async_broker_env
        _queue(b)
        fake.delete("dev:inv:inv_1")
        sess = b.register_session(DEVICE["id"], DEVICE["user_id"])
        assert await b.next_command_async(sess, timeout=0.01) is None

    async def test_none_when_async_redis_unavailable(self, async_broker_env, monkeypatch):
        b, _ = async_broker_env

        async def _no_redis():
            return None

        monkeypatch.setattr("docsgpt.devices.broker.get_async_redis_instance", _no_redis)
        sess = b.register_session(DEVICE["id"], DEVICE["user_id"])
        assert await b.next_command_async(sess, timeout=0.01) is None

    async def test_none_when_blpop_fails(self, async_broker_env, fake_redis, monkeypatch):
        b, _ = async_broker_env

        class _Broken(AsyncFakeRedis):
            async def blpop(self, key, timeout=0):
                raise ConnectionError("reset by peer")

        broken = _Broken(fake_redis)

        async def _get():
            return broken

        monkeypatch.setattr("docsgpt.devices.broker.get_async_redis_instance", _get)
        sess = b.register_session(DEVICE["id"], DEVICE["user_id"])
        assert await b.next_command_async(sess, timeout=0.01) is None


@pytest.mark.unit
def test_flask_blueprint_leaves_session_stream_to_asgi():
    from docsgpt.api.devices import devices_bp

    app = Flask(__name__)
    app.register_blueprint(devices_bp)
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/devices/sessions/<session_id>/events" not in rules
    assert "/api/devices/poll" in rules
    assert "/api/devices/sessions/<session_id>/invocations/<invocation_id>/ack" in rules
    assert "/api/devices/sessions/<session_id>/invocations/<invocation_id>/output" in rules
