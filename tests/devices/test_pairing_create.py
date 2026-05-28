"""Tests for the create-pairing endpoint's optional preset fields.

Covers the friction-reducer A change: ``POST /api/devices/pairings`` now
accepts ``name``, ``description``, and ``approval_mode`` in the body and
stashes them in Redis so ``redeem_pairing`` can apply them to the new
``devices`` row. These tests exercise the function directly (no Flask
test client) because the broader pairing flow needs Redis + Postgres
fixtures that aren't wired into this module yet.
"""

from __future__ import annotations

import json
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from flask import Flask

from application.api.devices import pairing as pairing_module


class _StubRedis:
    """Minimal Redis stand-in capturing setex payloads.

    ``eval`` re-implements the redeem-claim Lua: read the pairing JSON and,
    only if ``status == 'pending'``, flip it to ``redeemed`` (returning 1),
    else return 0. This lets the redeem tests exercise the atomic path.
    """

    def __init__(self) -> None:
        self.setex_calls: list[tuple[str, int, str]] = []
        self.store: dict[str, str] = {}

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.setex_calls.append((key, ttl, value))
        self.store[key] = value

    def get(self, key: str) -> Optional[str]:
        return self.store.get(key)

    def delete(self, key: str) -> None:
        self.store.pop(key, None)

    def eval(self, _script: str, _numkeys: int, key: str, *_args) -> int:
        raw = self.store.get(key)
        if raw is None:
            return 0
        try:
            state = json.loads(raw)
        except Exception:
            return 0
        if state.get("status") != "pending":
            return 0
        state["status"] = "redeemed"
        self.store[key] = json.dumps(state)
        return 1


@pytest.fixture
def app():
    return Flask(__name__)


def _call_create(app: Flask, body: dict, redis: _StubRedis):
    with app.test_request_context(
        "/api/devices/pairings",
        method="POST",
        json=body,
    ):
        from flask import request as flask_request

        flask_request.decoded_token = {"sub": "user_abc"}
        with patch.object(pairing_module, "_redis", return_value=redis):
            return pairing_module.create_pairing()


def _stashed_state(redis: _StubRedis) -> dict:
    assert redis.setex_calls, "no redis writes recorded"
    # The first setex is the device_code -> state hash; the second is the
    # user_code -> device_code index.
    raw = redis.setex_calls[0][2]
    return json.loads(raw)


def test_create_pairing_stashes_name_description_and_mode(app):
    redis = _StubRedis()
    response = _call_create(
        app,
        {
            "name": "  laptop  ",
            "description": "  desk machine ",
            "approval_mode": "full",
        },
        redis,
    )
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["user_code"], "expected a user_code in the response"
    state = _stashed_state(redis)
    assert state["requested_name"] == "laptop"
    assert state["requested_description"] == "desk machine"
    assert state["requested_approval_mode"] == "full"


def test_create_pairing_defaults_when_body_omitted(app):
    redis = _StubRedis()
    response = _call_create(app, {}, redis)
    assert response.status_code == 200
    state = _stashed_state(redis)
    assert state["requested_name"] is None
    assert state["requested_description"] is None
    assert state["requested_approval_mode"] is None


@pytest.mark.parametrize("mode", ["bogus", "writes-only", "never"])
def test_create_pairing_rejects_invalid_approval_mode(app, mode):
    redis = _StubRedis()
    response = _call_create(app, {"approval_mode": mode}, redis)
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "invalid_approval_mode"
    assert not redis.setex_calls


@pytest.mark.parametrize("bad_name", [123, 12.5, True, ["x"], {"a": 1}])
def test_create_pairing_rejects_non_string_name(app, bad_name):
    # A non-string ``name`` must 400 instead of crashing on ``.strip()``.
    redis = _StubRedis()
    response = _call_create(app, {"name": bad_name}, redis)
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_name"
    assert not redis.setex_calls


def test_create_pairing_blank_strings_normalize_to_none(app):
    redis = _StubRedis()
    response = _call_create(
        app,
        {"name": "   ", "description": ""},
        redis,
    )
    assert response.status_code == 200
    state = _stashed_state(redis)
    assert state["requested_name"] is None
    assert state["requested_description"] is None


class _StubDevicesRepo:
    def __init__(self) -> None:
        self.create_args: dict = {}

    def create(self, **kwargs) -> dict:
        self.create_args = kwargs
        return {"id": kwargs.get("device_id"), **kwargs}


class _StubConn:
    def __init__(self) -> None:
        self.executed: list = []

    def execute(self, *args, **kwargs):
        self.executed.append((args, kwargs))
        # Return an object with .fetchone()/.rowcount where needed; for
        # the upsert helper we only need .fetchone() returning None.
        return MagicMock(fetchone=lambda: None, rowcount=0)


def test_redeem_applies_stashed_preferences(app, monkeypatch):
    """End-to-end: stash via create, then redeem applies the values."""
    redis = _StubRedis()
    # Step 1 — create with preset name/description/mode
    create_response = _call_create(
        app,
        {
            "name": "edgebox",
            "description": "raspberry pi",
            "approval_mode": "full",
        },
        redis,
    )
    create_payload = create_response.get_json()
    user_code = create_payload["user_code"].replace("-", "")
    # Step 2 — simulate the CLI hitting redeem.
    devices_repo = _StubDevicesRepo()
    monkeypatch.setattr(
        pairing_module, "DevicesRepository", lambda conn: devices_repo
    )
    monkeypatch.setattr(
        pairing_module,
        "_upsert_remote_device_user_tool",
        lambda conn, **kwargs: None,
    )

    class _Sess:
        def __enter__(self):
            return _StubConn()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(pairing_module, "db_session", _Sess)
    monkeypatch.setattr(
        pairing_module,
        "fingerprint_pubkey",
        lambda _pubkey: "fpfpfp",
    )
    monkeypatch.setattr(
        pairing_module,
        "hash_session_token",
        lambda _tok: "tokhash",
    )

    with app.test_request_context(
        "/api/devices/pairings/redeem",
        method="POST",
        json={
            "user_code": user_code,
            "hostname": "myhost",
            "os": "linux",
            "arch": "amd64",
            "cli_version": "0.5.0",
            "machine_pubkey": "Zm9v",
        },
    ):
        with patch.object(pairing_module, "_redis", return_value=redis):
            response = pairing_module.redeem_pairing()
    assert response.status_code == 200, response.get_json()
    args = devices_repo.create_args
    assert args["approval_mode"] == "full"
    assert args["description"] == "raspberry pi"
    # Name prefix is the user-supplied value (collision suffix appended).
    assert args["name"].startswith("edgebox")


def test_redeem_falls_back_to_hostname_and_ask(app, monkeypatch):
    redis = _StubRedis()
    create_response = _call_create(app, {}, redis)
    user_code = create_response.get_json()["user_code"].replace("-", "")
    devices_repo = _StubDevicesRepo()
    monkeypatch.setattr(
        pairing_module, "DevicesRepository", lambda conn: devices_repo
    )
    monkeypatch.setattr(
        pairing_module,
        "_upsert_remote_device_user_tool",
        lambda conn, **kwargs: None,
    )

    class _Sess:
        def __enter__(self):
            return _StubConn()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(pairing_module, "db_session", _Sess)
    monkeypatch.setattr(
        pairing_module, "fingerprint_pubkey", lambda _pubkey: "fpfpfp",
    )
    monkeypatch.setattr(
        pairing_module, "hash_session_token", lambda _tok: "tokhash",
    )

    with app.test_request_context(
        "/api/devices/pairings/redeem",
        method="POST",
        json={
            "user_code": user_code,
            "hostname": "fallback-host",
            "os": "linux",
            "arch": "amd64",
            "machine_pubkey": "Zm9v",
        },
    ):
        with patch.object(pairing_module, "_redis", return_value=redis):
            response = pairing_module.redeem_pairing()
    assert response.status_code == 200
    args = devices_repo.create_args
    assert args["approval_mode"] == "ask"
    assert args["description"] is None
    assert args["name"].startswith("fallback-host")
