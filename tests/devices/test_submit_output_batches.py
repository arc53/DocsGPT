"""The output route takes multi-line NDJSON batches, and a resent batch from an outbox client counts once."""

from __future__ import annotations

import gzip
import json
from unittest.mock import patch

import pytest
from flask import Flask

from docsgpt.api.devices import auth as auth_module
from docsgpt.api.devices import session as session_module

DEVICE = {"id": "dev_b", "user_id": "u_b", "name": "box", "status": "active", "approval_mode": "full",
          "machine_pubkey_fingerprint": "fp", "token_hash": "th"}


class _Repo:
    touched: list = []

    def __init__(self, _conn):
        pass

    def find_by_token_hash(self, _token_hash):
        return dict(DEVICE)

    def touch_last_seen(self, device_id, capabilities=None):
        _Repo.touched.append((device_id, capabilities))


class _Ctx:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


class _Audit:
    calls: list = []

    def __init__(self, _conn):
        pass

    def record_result(self, invocation_id, **kwargs):
        _Audit.calls.append((invocation_id, kwargs))


@pytest.fixture
def broker(broker_env):
    broker, fake = broker_env
    broker.dispatch_invocation("dev_b", "u_b", {"invocation_id": "inv_b", "action": "run_command"})
    _Audit.calls.clear()
    _Repo.touched.clear()
    return broker, fake


def _post(broker, lines, *, caps=None, gz=False):
    body = b"".join(json.dumps(line).encode() + b"\n" for line in lines)
    headers = {"Authorization": "Bearer tok"}
    if caps is not None:
        headers["X-Device-Capabilities"] = caps
    if gz:
        body = gzip.compress(body)
        headers["Content-Encoding"] = "gzip"
    app = Flask(__name__)
    with app.test_request_context(
        "/api/devices/sessions/s/invocations/inv_b/output", method="POST", data=body, headers=headers
    ), patch.object(auth_module, "DevicesRepository", _Repo), patch.object(auth_module, "db_readonly", _Ctx), \
            patch.object(auth_module, "db_session", _Ctx), \
            patch.object(session_module, "get_broker", return_value=broker), \
            patch.object(session_module, "DeviceAuditLogRepository", _Audit), \
            patch.object(session_module, "db_session", _Ctx):
        response = session_module.submit_output("s", "inv_b")
        return response.status_code, response.get_json()


def _stream(fake):
    return [json.loads(fields[b"c"]) for _id, fields in fake.streams.get("dev:out:inv_b", [])]


BATCH = [
    {"stream": "stdout", "chunk": "a\n", "seq": 0},
    {"stream": "stderr", "chunk": "b\n", "seq": 1},
    {"stream": "stdout", "chunk": "c\n", "seq": 2},
    {"stream": "control", "exit_code": 0, "duration_ms": 5, "seq": 3, "truncated": True},
]


def test_a_batch_of_many_lines_lands_in_order(broker):
    b, fake = broker
    status, body = _post(b, BATCH, caps="cancel,outbox", gz=True)
    assert status == 200 and body == {"success": True, "received": 4, "duplicates": 0}
    assert [c["seq"] for c in _stream(fake)] == [0, 1, 2, 3]
    assert b.get_invocation("inv_b").truncated is True
    assert len(_Audit.calls) == 1 and _Audit.calls[0][1]["exit_code"] == 0
    # The request's capabilities were recorded on the device.
    assert _Repo.touched == [("dev_b", "cancel,outbox")]


def test_a_resent_batch_counts_once_and_writes_no_second_audit(broker):
    b, fake = broker
    _post(b, BATCH[:2], caps="cancel,outbox")
    status, body = _post(b, BATCH, caps="cancel,outbox")
    assert status == 200 and body == {"success": True, "received": 2, "duplicates": 2}
    status, body = _post(b, BATCH, caps="cancel,outbox")
    assert body == {"success": True, "received": 0, "duplicates": 4}
    assert [c["seq"] for c in _stream(fake)] == [0, 1, 2, 3]
    assert len(_Audit.calls) == 1


def test_a_client_without_an_outbox_is_taken_as_sent(broker):
    # Without the capability nothing is dropped by seq; only the final report is taken once.
    b, fake = broker
    _post(b, BATCH)
    status, body = _post(b, BATCH)
    assert body == {"success": True, "received": 3, "duplicates": 1}
    assert [c["stream"] for c in _stream(fake)].count("control") == 1
    assert _Repo.touched[-1] == ("dev_b", "")


def test_an_interrupted_report_is_audited_with_its_pid(broker):
    b, _ = broker
    _post(b, [{"stream": "control", "exit_code": -1, "error": "interrupted",
               "detail": "daemon restarted; process 4242 may still be running", "seq": 0}], caps="outbox")
    assert _Audit.calls[0][1]["error"] == "interrupted: daemon restarted; process 4242 may still be running"


def test_an_expired_invocation_is_404(broker):
    b, fake = broker
    fake.delete("dev:inv:inv_b")
    status, body = _post(b, BATCH, caps="outbox")
    assert status == 404 and body["error"] == "invocation_not_found"


def test_a_broker_failure_mid_batch_is_a_503_and_the_retry_completes_it(broker, monkeypatch):
    # Never a 200 for output that wasn't stored: the outbox client would drop it.
    b, fake = broker
    real_eval = fake.eval
    calls = {"n": 0}

    def flaky(script, *args):
        calls["n"] += 1
        if calls["n"] == 3:
            raise ConnectionError("redis blip")
        return real_eval(script, *args)

    monkeypatch.setattr(fake, "eval", flaky)
    status, body = _post(b, BATCH, caps="cancel,outbox")
    assert status == 503 and body["error"] == "broker_unavailable"
    assert _Audit.calls == []
    status, body = _post(b, BATCH, caps="cancel,outbox")
    assert status == 200 and body == {"success": True, "received": 2, "duplicates": 2}
    assert [c["seq"] for c in _stream(fake)] == [0, 1, 2, 3]
    assert len(_Audit.calls) == 1


def test_an_unreachable_broker_on_lookup_is_a_503_not_a_404(broker, monkeypatch):
    b, fake = broker

    def boom(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(fake, "hgetall", boom)
    status, body = _post(b, BATCH, caps="outbox")
    assert status == 503 and body["error"] == "broker_unavailable"


def test_an_invocation_that_vanishes_mid_batch_is_a_404(broker, monkeypatch):
    b, fake = broker
    real_eval = fake.eval
    calls = {"n": 0}

    def vanish(script, *args):
        calls["n"] += 1
        if calls["n"] == 2:
            fake.delete("dev:inv:inv_b")
        return real_eval(script, *args)

    monkeypatch.setattr(fake, "eval", vanish)
    status, body = _post(b, BATCH, caps="outbox")
    assert status == 404 and body["error"] == "invocation_not_found"


def test_an_ack_the_broker_cannot_store_is_a_503(broker, monkeypatch):
    b, fake = broker
    app = Flask(__name__)

    def boom(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(fake, "hmget", boom)
    with app.test_request_context(
        "/api/devices/sessions/s/invocations/inv_b/ack", method="POST", json={"decision": "accepted"},
        headers={"Authorization": "Bearer tok"},
    ), patch.object(auth_module, "DevicesRepository", _Repo), patch.object(auth_module, "db_readonly", _Ctx), \
            patch.object(auth_module, "db_session", _Ctx), patch.object(session_module, "get_broker", return_value=b):
        response = session_module.ack_invocation("s", "inv_b")
    assert response.status_code == 503 and response.headers["Retry-After"] == "5"
