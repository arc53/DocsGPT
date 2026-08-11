"""Tests for ``GET /api/devices/me``.

Exercises the route handler directly through a Flask test-request context
so we can mock ``DevicesRepository.find_by_token_hash`` without spinning
up Postgres.
"""

from __future__ import annotations

from datetime import datetime, timezone
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
        "id": "dev_abc",
        "user_id": "user_xyz",
        "name": "laptop",
        "hostname": "laptop.local",
        "os": "linux",
        "arch": "amd64",
        "status": "active",
        "approval_mode": "full",
        "description": "primary desktop",
        "paired_at": datetime(2026, 5, 26, 14, 23, tzinfo=timezone.utc),
        "last_seen_at": datetime(2026, 5, 26, 14, 30, tzinfo=timezone.utc),
        "machine_pubkey_fingerprint": "fpfpfp",
        "token_hash": "tokhash",
    }


def _call_me(app: Flask, token: str | None):
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    with app.test_request_context(
        "/api/devices/me", method="GET", headers=headers,
    ):
        return session_module.me()


def test_me_returns_device_record_on_valid_token(app):
    """Valid token returns the device's own public fields, datetimes ISO."""
    row = _device_row()

    class _Repo:
        def __init__(self, _conn):
            self._row = row

        def find_by_token_hash(self, _token_hash):
            return self._row

        def touch_last_seen(self, _device_id):
            pass

    class _Ctx:
        def __enter__(self):
            return None

        def __exit__(self, *a):
            return False

    with patch.object(auth_module, "DevicesRepository", _Repo), \
         patch.object(auth_module, "db_readonly", _Ctx), \
         patch.object(auth_module, "db_session", _Ctx):
        response = _call_me(app, "tok_good")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["id"] == "dev_abc"
    assert payload["name"] == "laptop"
    assert payload["hostname"] == "laptop.local"
    assert payload["os"] == "linux"
    assert payload["status"] == "active"
    assert payload["approval_mode"] == "full"
    assert payload["description"] == "primary desktop"
    assert payload["paired_at"] == "2026-05-26T14:23:00+00:00"
    assert payload["last_seen_at"] == "2026-05-26T14:30:00+00:00"
    # Internal fields never leak.
    assert "token_hash" not in payload
    assert "machine_pubkey_fingerprint" not in payload
    assert "user_id" not in payload


def test_me_rejects_missing_authorization(app):
    """No Authorization header -> 401 missing_token, route handler not entered."""
    response = _call_me(app, token=None)
    assert response.status_code == 401
    assert response.get_json()["error"] == "missing_token"


def test_me_rejects_invalid_token(app):
    """Unknown token -> 401 invalid_token."""

    class _Repo:
        def __init__(self, _conn):
            pass

        def find_by_token_hash(self, _token_hash):
            return None

    class _Ctx:
        def __enter__(self):
            return None

        def __exit__(self, *a):
            return False

    with patch.object(auth_module, "DevicesRepository", _Repo), \
         patch.object(auth_module, "db_readonly", _Ctx):
        response = _call_me(app, "tok_bogus")
    assert response.status_code == 401
    assert response.get_json()["error"] == "invalid_token"
