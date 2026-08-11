"""Route-level coverage for submit_output's audit write (fix 4).

The audit outcome must come from the control chunk captured locally during
the parse loop, so it survives the draining (worker) process racing to delete
the invocation's Redis state — modelled here by the post-submit snapshot
returning None.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask

from application.api.devices import auth as auth_module
from application.api.devices import session as session_module


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


class _AuditSpy:
    calls: list = []

    def __init__(self, _conn):
        pass

    def record_result(self, invocation_id, **kwargs):
        _AuditSpy.calls.append((invocation_id, kwargs))


class _RaceBroker:
    """First get_invocation (ownership check) returns a live inv; the second
    (post-submit snapshot) returns ``snap`` — None models the worker having
    already deleted the hash.
    """

    def __init__(self, snap):
        self._snap = snap
        self.calls = 0

    def get_invocation(self, _invocation_id):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(device_id="dev_route", completed=True)
        return self._snap

    def submit_output_chunk(self, _invocation_id, _chunk):
        return True

    def submit_ack(self, _invocation_id, _decision, _reason=None):
        return True


CONTROL_BODY = b'{"stream":"control","exit_code":9,"duration_ms":42}\n'


def _post(app: Flask, broker, body: bytes, invocation_id: str = "inv_audit"):
    path = f"/api/devices/sessions/s/invocations/{invocation_id}/output"
    with app.test_request_context(
        path, method="POST", data=body, headers={"Authorization": "Bearer tok"}
    ):
        patches = [
            patch.object(auth_module, "DevicesRepository", _Repo),
            patch.object(auth_module, "db_readonly", _Ctx),
            patch.object(auth_module, "db_session", _Ctx),
            patch.object(session_module, "get_broker", return_value=broker),
            patch.object(session_module, "DeviceAuditLogRepository", _AuditSpy),
            patch.object(session_module, "db_session", _Ctx),
        ]
        for p in patches:
            p.start()
        try:
            return session_module.submit_output("s", invocation_id)
        finally:
            for p in patches:
                p.stop()


def test_audit_written_from_control_chunk_when_snapshot_present(app):
    _AuditSpy.calls.clear()
    snap = SimpleNamespace(started_at=None, stdout_bytes=3, stderr_bytes=0)
    resp = _post(app, _RaceBroker(snap), CONTROL_BODY)
    assert resp.status_code == 200
    assert len(_AuditSpy.calls) == 1
    inv_id, kw = _AuditSpy.calls[0]
    assert inv_id == "inv_audit"
    assert kw["exit_code"] == 9
    assert kw["duration_ms"] == 42
    assert kw["stdout_bytes"] == 3


def test_audit_written_even_when_snapshot_deleted_by_race(app):
    # snap is None: the worker already cleaned up the hash. The functional
    # outcome fields must still land, sourced from the local control chunk.
    _AuditSpy.calls.clear()
    resp = _post(app, _RaceBroker(None), CONTROL_BODY)
    assert resp.status_code == 200
    assert len(_AuditSpy.calls) == 1
    _inv_id, kw = _AuditSpy.calls[0]
    assert kw["exit_code"] == 9
    assert kw["duration_ms"] == 42
    assert kw["started_at"] is None
    assert kw["stdout_bytes"] == 0


def test_no_audit_without_control_chunk(app):
    _AuditSpy.calls.clear()
    resp = _post(app, _RaceBroker(None), b'{"stream":"stdout","chunk":"hi"}\n')
    assert resp.status_code == 200
    assert _AuditSpy.calls == []


# ---------------------------------------------------------------------------
# ack_invocation: a denial is a terminal outcome with no subsequent output,
# so it must record its own audit row (the device never POSTs output).
# ---------------------------------------------------------------------------
def _ack(app: Flask, broker, decision: str, invocation_id: str = "inv_audit",
         reason=None):
    path = f"/api/devices/sessions/s/invocations/{invocation_id}/ack"
    with app.test_request_context(
        path,
        method="POST",
        json={"decision": decision, "reason": reason},
        headers={"Authorization": "Bearer tok"},
    ):
        patches = [
            patch.object(auth_module, "DevicesRepository", _Repo),
            patch.object(auth_module, "db_readonly", _Ctx),
            patch.object(auth_module, "db_session", _Ctx),
            patch.object(session_module, "get_broker", return_value=broker),
            patch.object(session_module, "DeviceAuditLogRepository", _AuditSpy),
            patch.object(session_module, "db_session", _Ctx),
        ]
        for p in patches:
            p.start()
        try:
            return session_module.ack_invocation("s", invocation_id)
        finally:
            for p in patches:
                p.stop()


def test_denied_ack_records_terminal_audit_outcome(app):
    _AuditSpy.calls.clear()
    resp = _ack(app, _RaceBroker(None), "denied", reason="user rejected")
    assert resp.status_code == 200
    assert len(_AuditSpy.calls) == 1
    inv_id, kw = _AuditSpy.calls[0]
    assert inv_id == "inv_audit"
    assert kw["error"] == "denied"
    assert kw["finished_at"] is not None
    # exit_code is intentionally not passed (a denied command never ran), so it
    # stays NULL via record_result's COALESCE update.
    assert kw.get("exit_code") is None


def test_accepted_ack_does_not_record_outcome(app):
    # An accepted command will run and POST output; submit_output records the
    # outcome then, so ack must not write a (premature) terminal row.
    _AuditSpy.calls.clear()
    resp = _ack(app, _RaceBroker(None), "accepted")
    assert resp.status_code == 200
    assert _AuditSpy.calls == []


def test_auto_approved_ack_does_not_record_outcome(app):
    _AuditSpy.calls.clear()
    resp = _ack(app, _RaceBroker(None), "auto_approved")
    assert resp.status_code == 200
    assert _AuditSpy.calls == []
