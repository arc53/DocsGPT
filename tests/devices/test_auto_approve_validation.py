"""Input validation for the add-auto-approve-pattern route.

These exercise ``add_auto_approve_pattern`` directly. The non-string and
missing-command cases short-circuit with a 400 before any DB access, so no
Postgres fixture is needed.
"""

from __future__ import annotations

import pytest
from flask import Flask

from application.api.devices import routes as routes_module


@pytest.fixture
def app():
    return Flask(__name__)


def _call(app: Flask, body):
    with app.test_request_context(
        "/api/devices/dev_x/auto-approve",
        method="POST",
        json=body,
    ):
        from flask import request as flask_request

        flask_request.decoded_token = {"sub": "user_abc"}
        return routes_module.add_auto_approve_pattern("dev_x")


@pytest.mark.parametrize("bad_command", [123, 12.5, True, ["ls"], {"c": 1}])
def test_add_auto_approve_rejects_non_string_command(app, bad_command):
    # A truthy-but-non-string command must 400 rather than crash in shlex.
    response = _call(app, {"command": bad_command})
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_command"


def test_add_auto_approve_missing_command(app):
    response = _call(app, {})
    assert response.status_code == 400
    assert response.get_json()["error"] == "missing_command"
