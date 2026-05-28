"""Concurrency test: two redeems of one user_code yield exactly one device.

Exercises the real Lua claim against the local dev Redis (127.0.0.1:6379).
Skips cleanly if Redis isn't reachable so CI without Redis still passes.
The DB layer is stubbed; we only count how many device rows get created.
"""

from __future__ import annotations

import json
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from application.api.devices import pairing as pairing_module


def _redis_or_skip():
    redis = pytest.importorskip("redis")
    try:
        client = redis.Redis(host="127.0.0.1", port=6379, socket_connect_timeout=1)
        client.ping()
    except Exception:  # noqa: BLE001 - any connection failure -> skip
        pytest.skip("local Redis (127.0.0.1:6379) not available")
    return client


class _CountingDevicesRepo:
    creates = 0

    def __init__(self, conn):
        pass

    def create(self, **kwargs):
        type(self).creates += 1
        return {"id": kwargs.get("device_id"), **kwargs}


class _StubConn:
    def execute(self, *args, **kwargs):
        return MagicMock(fetchone=lambda: None, rowcount=0)


class _Sess:
    def __enter__(self):
        return _StubConn()

    def __exit__(self, *args):
        return False


@pytest.fixture
def app():
    return Flask(__name__)


def _seed_pairing(redis_client, user_id: str) -> str:
    """Write a pending pairing + user-code index; return the raw user_code."""
    device_code = f"dc_{uuid.uuid4().hex}"
    user_code = "".join(
        pairing_module.secrets.choice(pairing_module._USER_CODE_ALPHABET)
        for _ in range(pairing_module._USER_CODE_LEN)
    )
    state = {
        "device_code": device_code,
        "user_code": pairing_module._format_user_code(user_code),
        "user_code_raw": user_code,
        "user_id": user_id,
        "status": "pending",
        "created_at": int(time.time()),
        "requested_name": None,
        "requested_description": None,
        "requested_approval_mode": None,
    }
    redis_client.setex(
        pairing_module._PAIRING_REDIS_PREFIX + device_code, 300, json.dumps(state)
    )
    redis_client.setex(
        pairing_module._user_code_index_key(user_code), 300, device_code
    )
    return user_code


def _redeem_once(app: Flask, redis_client, user_code: str):
    with app.test_request_context(
        "/api/devices/pairings/redeem",
        method="POST",
        json={
            "user_code": user_code,
            "hostname": "concurrent-host",
            "os": "linux",
            "arch": "amd64",
            "machine_pubkey": "Zm9v",
        },
    ):
        with patch.object(pairing_module, "_redis", return_value=redis_client):
            return pairing_module.redeem_pairing()


def test_two_redeems_of_one_code_create_exactly_one_device(app, monkeypatch):
    redis_client = _redis_or_skip()
    _CountingDevicesRepo.creates = 0
    monkeypatch.setattr(pairing_module, "DevicesRepository", _CountingDevicesRepo)
    monkeypatch.setattr(
        pairing_module, "_upsert_remote_device_user_tool", lambda conn, **k: None
    )
    monkeypatch.setattr(pairing_module, "db_session", _Sess)
    monkeypatch.setattr(pairing_module, "fingerprint_pubkey", lambda _p: "fpfpfp")
    monkeypatch.setattr(pairing_module, "hash_session_token", lambda _t: "tokhash")

    user_code = _seed_pairing(redis_client, f"user_{uuid.uuid4().hex}")
    try:
        first = _redeem_once(app, redis_client, user_code)
        second = _redeem_once(app, redis_client, user_code)
    finally:
        # Best-effort cleanup of the seeded keys.
        device_code = redis_client.get(
            pairing_module._user_code_index_key(user_code)
        )
        if device_code:
            if isinstance(device_code, (bytes, bytearray)):
                device_code = device_code.decode()
            redis_client.delete(pairing_module._PAIRING_REDIS_PREFIX + device_code)
        redis_client.delete(pairing_module._user_code_index_key(user_code))

    statuses = [first.status_code, second.status_code]
    # Exactly one redeem wins (200); the other is rejected. Sequentially the
    # winner deletes the user-code index so the loser sees 404; in a true
    # race the loser loses the atomic claim and sees 409. Either way, no
    # second device.
    assert first.status_code == 200, first.get_json()
    assert second.status_code in (404, 409), second.get_json()
    assert statuses.count(200) == 1
    assert _CountingDevicesRepo.creates == 1


def test_claim_pairing_wins_exactly_once():
    # Direct test of the atomic claim against real Redis: two claims on the
    # same pending pairing key -> first True, second False. This is the 409
    # race path (no index deletion involved).
    redis_client = _redis_or_skip()
    device_code = f"dc_{uuid.uuid4().hex}"
    key = pairing_module._PAIRING_REDIS_PREFIX + device_code
    redis_client.setex(key, 60, json.dumps({"status": "pending", "user_id": "u"}))
    try:
        first = pairing_module._claim_pairing(redis_client, device_code)
        second = pairing_module._claim_pairing(redis_client, device_code)
        assert first is True
        assert second is False
        # TTL preserved (claim must not drop expiry).
        assert redis_client.ttl(key) > 0
        # State flipped to redeemed, other fields intact.
        stored = json.loads(redis_client.get(key))
        assert stored["status"] == "redeemed"
        assert stored["user_id"] == "u"
    finally:
        redis_client.delete(key)
