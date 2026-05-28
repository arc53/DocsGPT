"""Tests for ``PATCH /api/devices/<id>`` body validation.

The validation rejects bad ``name``/``description`` values before any DB
access, so the 400 cases exercise the handler directly without Postgres.
A valid PATCH is covered with the repository + session mocked.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from flask import Flask

from application.api.devices import routes as routes_module


@pytest.fixture
def app():
    return Flask(__name__)


def _call_update(app: Flask, body, device_id: str = "dev_abc"):
    with app.test_request_context(
        f"/api/devices/{device_id}", method="PATCH", json=body,
    ):
        from flask import request as flask_request

        flask_request.decoded_token = {"sub": "user_abc"}
        return routes_module.update_device(device_id)


def test_patch_rejects_null_name(app):
    response = _call_update(app, {"name": None})
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_name"


def test_patch_rejects_blank_name(app):
    response = _call_update(app, {"name": "  "})
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_name"


def test_patch_rejects_non_string_name(app):
    response = _call_update(app, {"name": 123})
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_name"


def test_patch_rejects_null_description(app):
    response = _call_update(app, {"description": None})
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_description"


def test_patch_rejects_non_string_description(app):
    response = _call_update(app, {"description": ["x"]})
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_description"


def test_patch_still_validates_approval_mode(app):
    response = _call_update(app, {"approval_mode": "bogus"})
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_approval_mode"


def test_patch_empty_body_is_no_fields(app):
    response = _call_update(app, {})
    assert response.status_code == 400
    assert response.get_json()["error"] == "no_fields"


def test_patch_valid_name_trimmed_and_persisted(app, monkeypatch):
    """A valid PATCH trims the name and writes the stripped value."""
    captured: dict = {}

    class _Repo:
        def __init__(self, _conn):
            pass

        def update(self, _device_id, _user_id, fields):
            captured.update(fields)
            return True

        def get(self, device_id, user_id=None):
            return {"id": device_id, "name": fields_name(), "description": ""}

    def fields_name():
        return captured.get("name")

    class _Sess:
        def __enter__(self):
            return None

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(routes_module, "DevicesRepository", _Repo)
    monkeypatch.setattr(routes_module, "db_session", _Sess)
    monkeypatch.setattr(
        "application.api.devices.pairing._upsert_remote_device_user_tool",
        lambda conn, **kwargs: None,
    )

    response = _call_update(app, {"name": "  laptop  ", "description": "  box "})
    assert response.status_code == 200
    assert captured["name"] == "laptop"
    assert captured["description"] == "box"
