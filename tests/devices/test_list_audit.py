"""Tests for ``GET /api/devices/<id>/audit`` ``limit`` / ``offset`` parsing.

The repository is mocked; the SQL paging itself is covered in
tests/storage/db/repositories/test_device_audit_log.py.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from flask import Flask

from docsgpt.api.devices import routes as routes_module


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def audit_calls(monkeypatch):
    calls: list = []

    class _Devices:
        def __init__(self, _conn):
            pass

        def get(self, device_id, user_id=None):
            return {"id": device_id} if device_id == "dev_abc" else None

    class _Audit:
        def __init__(self, _conn):
            pass

        def list_for_device(self, device_id, user_id, *, limit=100, offset=0):
            calls.append({"device_id": device_id, "user_id": user_id, "limit": limit, "offset": offset})
            return [{"id": 1, "created_at": None, "command": "ls"}]

    @contextmanager
    def _ro():
        yield None

    monkeypatch.setattr(routes_module, "DevicesRepository", _Devices)
    monkeypatch.setattr(routes_module, "DeviceAuditLogRepository", _Audit)
    monkeypatch.setattr(routes_module, "db_readonly", _ro)
    return calls


def _call(app: Flask, query: str = "", device_id: str = "dev_abc"):
    with app.test_request_context(f"/api/devices/{device_id}/audit{query}", method="GET"):
        from flask import request as flask_request

        flask_request.decoded_token = {"sub": "user_abc"}
        return routes_module.list_audit(device_id)


def test_defaults_unchanged(app, audit_calls):
    resp = _call(app)
    assert resp.status_code == 200
    assert resp.get_json() == {"entries": [{"id": 1, "created_at": None, "command": "ls"}]}
    assert audit_calls == [{"device_id": "dev_abc", "user_id": "user_abc", "limit": 100, "offset": 0}]


@pytest.mark.parametrize(
    "query,limit,offset",
    [
        ("?limit=50&offset=20", 50, 20),
        ("?limit=0", 1, 0),
        ("?limit=-3", 1, 0),
        ("?limit=1000", 200, 0),
        ("?limit=abc", 100, 0),
        ("?offset=-5", 100, 0),
        ("?offset=xyz", 100, 0),
    ],
)
def test_limit_and_offset_are_clamped(app, audit_calls, query, limit, offset):
    resp = _call(app, query)
    assert resp.status_code == 200
    assert audit_calls[-1]["limit"] == limit
    assert audit_calls[-1]["offset"] == offset


def test_unknown_device_404s_before_listing(app, audit_calls):
    resp = _call(app, "?limit=5", device_id="dev_missing")
    assert resp.status_code == 404
    assert audit_calls == []
