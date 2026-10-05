"""Tests for the public trigger route: POST only, 202, 404 for any dead token, 401, 413, 429, dedupe."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from docsgpt.core.settings import settings
from docsgpt.monitors import links, signatures
from docsgpt.storage.db.repositories.monitors import MonitorsRepository
from docsgpt.storage.db.repositories.trigger_links import TriggerLinksRepository


@pytest.fixture()
def client():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture()
def enqueued(monkeypatch):
    calls = []
    monkeypatch.setattr("docsgpt.monitors.tick.enqueue_hit", lambda hit_id, **kw: calls.append(hit_id) or True)
    return calls


def make_link(engine, conversation_id, *, scheme="none", max_hits=1000, expires_in=timedelta(days=1)):
    """A webhook monitor with its link; returns ``(token, secret, link, monitor)``."""
    now = datetime.now(timezone.utc)
    token = links.new_token("webhook")
    secret = links.new_secret(scheme)
    with engine.begin() as conn:
        monitor = MonitorsRepository(conn).create(
            user_id="u1",
            conversation_id=conversation_id,
            agent_id=None,
            description="CI done",
            source_type="webhook",
            spec={"source": {"type": "webhook", "signature": scheme}},
            on_match="tell me",
            end_at=now + timedelta(days=7),
            next_run_at=now + timedelta(days=7),
            max_wakes=1,
        )
        link = TriggerLinksRepository(conn).create(
            monitor_id=monitor["id"],
            user_id="u1",
            conversation_id=conversation_id,
            token_hash=links.token_hash(token),
            kind="webhook",
            expires_at=now + expires_in,
            max_hits=max_hits,
            signature_scheme=scheme,
            secret_encrypted=links.seal_secret(secret, "u1"),
        )
    return token, secret, link, monitor


def _hits(engine):
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text("SELECT * FROM trigger_hits ORDER BY received_at"))]


class TestBasics:
    def test_get_is_405_with_a_short_explanation(self, client):
        response = client.get("/api/triggers/trg_anything_at_all_here")
        assert response.status_code == 405
        assert "POST" in response.get_data(as_text=True) and response.headers["Allow"] == "POST"

    def test_post_stores_once_and_queues(self, client, mon_db, conversation_id, enqueued):
        token, _secret, link, _monitor = make_link(mon_db, conversation_id)
        response = client.post(f"/api/triggers/{token}", json={"status": "success"})
        assert response.status_code == 202 and response.get_json() == {"accepted": True}
        hits = _hits(mon_db)
        assert len(hits) == 1 and hits[0]["payload"]["body"] == {"status": "success"}
        assert enqueued == [str(hits[0]["id"])]
        with mon_db.connect() as conn:
            assert TriggerLinksRepository(conn).get(str(link["id"]))["hit_count"] == 1

    def test_a_senders_authorization_header_is_ignored(self, client, mon_db, conversation_id, enqueued):
        token, *_ = make_link(mon_db, conversation_id)
        response = client.post(f"/api/triggers/{token}", data="x", headers={"Authorization": "Bearer junk"})
        assert response.status_code == 202

    def test_form_and_text_bodies(self, client, mon_db, conversation_id, enqueued):
        token, *_ = make_link(mon_db, conversation_id)
        client.post(f"/api/triggers/{token}", data={"status": "done", "n": "2"})
        client.post(f"/api/triggers/{token}", data="plain words", content_type="text/plain")
        bodies = [h["payload"]["body"] for h in _hits(mon_db)]
        assert {"status": "done", "n": "2"} in bodies and "plain words" in bodies

    def test_event_header_is_kept(self, client, mon_db, conversation_id, enqueued):
        token, *_ = make_link(mon_db, conversation_id)
        client.post(f"/api/triggers/{token}", json={}, headers={"X-GitHub-Event": "workflow_run"})
        assert _hits(mon_db)[0]["payload"]["event"] == "workflow_run"


class TestDeadLinks:
    def _body(self, response):
        return response.status_code, response.get_json()

    def test_unknown_expired_revoked_and_used_up_look_the_same(self, client, mon_db, conversation_id, enqueued):
        unknown = self._body(client.post("/api/triggers/trg_not_a_real_token_123", json={}))
        expired_token, *_ = make_link(mon_db, conversation_id, expires_in=timedelta(seconds=-1))
        expired = self._body(client.post(f"/api/triggers/{expired_token}", json={}))
        revoked_token, _s, _l, monitor = make_link(mon_db, conversation_id)
        with mon_db.begin() as conn:
            TriggerLinksRepository(conn).revoke_for_monitor(monitor["id"])
        revoked = self._body(client.post(f"/api/triggers/{revoked_token}", json={}))
        used_token, *_ = make_link(mon_db, conversation_id, max_hits=1)
        assert client.post(f"/api/triggers/{used_token}", json={"a": 1}).status_code == 202
        used = self._body(client.post(f"/api/triggers/{used_token}", json={"a": 2}))
        malformed = self._body(client.post("/api/triggers/../etc", json={}))
        assert unknown == expired == revoked == used == (404, {"error": "not found"})
        assert malformed[0] == 404

    def test_monitors_off_is_404(self, client, mon_db, conversation_id, monkeypatch, enqueued):
        token, *_ = make_link(mon_db, conversation_id)
        monkeypatch.setattr(settings, "MONITORS_ENABLED", False)
        assert client.post(f"/api/triggers/{token}", json={}).status_code == 404


class TestLimits:
    def test_large_body_is_413(self, client, mon_db, conversation_id, monkeypatch, enqueued):
        monkeypatch.setattr(settings, "TRIGGER_MAX_PAYLOAD_BYTES", 1024)
        token, *_ = make_link(mon_db, conversation_id)
        response = client.post(f"/api/triggers/{token}", data="x" * 2000, content_type="text/plain")
        assert response.status_code == 413 and _hits(mon_db) == []

    def test_rate_limit_is_429(self, client, mon_db, conversation_id, monkeypatch, fake_redis, enqueued):
        monkeypatch.setattr(settings, "TRIGGER_RATE_PER_MINUTE", 3)
        monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: fake_redis)
        token, *_ = make_link(mon_db, conversation_id)
        statuses = [client.post(f"/api/triggers/{token}", json={"i": i}).status_code for i in range(5)]
        assert statuses == [202, 202, 202, 429, 429]
        limited = client.post(f"/api/triggers/{token}", json={"i": 9})
        assert limited.headers["Retry-After"] == "60" and len(_hits(mon_db)) == 3

    def test_rate_limits_are_per_link(self, client, mon_db, conversation_id, monkeypatch, fake_redis, enqueued):
        monkeypatch.setattr(settings, "TRIGGER_RATE_PER_MINUTE", 1)
        monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: fake_redis)
        first, *_ = make_link(mon_db, conversation_id)
        second, *_ = make_link(mon_db, conversation_id)
        assert client.post(f"/api/triggers/{first}", json={}).status_code == 202
        assert client.post(f"/api/triggers/{second}", json={}).status_code == 202


class TestDedupe:
    def test_idempotency_key(self, client, mon_db, conversation_id, enqueued):
        token, *_ = make_link(mon_db, conversation_id)
        first = client.post(f"/api/triggers/{token}", json={"a": 1}, headers={"Idempotency-Key": "k1"})
        again = client.post(f"/api/triggers/{token}", json={"a": 2}, headers={"Idempotency-Key": "k1"})
        assert first.status_code == again.status_code == 202
        assert again.get_json() == {"accepted": True, "duplicate": True}
        assert len(_hits(mon_db)) == 1 and _hits(mon_db)[0]["dedupe_key"] == "idem:k1"

    def test_github_delivery_and_payload_hash(self, client, mon_db, conversation_id, enqueued):
        token, *_ = make_link(mon_db, conversation_id)
        client.post(f"/api/triggers/{token}", json={"a": 1}, headers={"X-GitHub-Delivery": "d-1"})
        client.post(f"/api/triggers/{token}", json={"a": 1}, headers={"X-GitHub-Delivery": "d-1"})
        client.post(f"/api/triggers/{token}", data='{"b": 2}', content_type="application/json")
        client.post(f"/api/triggers/{token}", data='{"b": 2}', content_type="application/json")
        keys = sorted(h["dedupe_key"] for h in _hits(mon_db))
        assert keys == ["gh:d-1", "sha:" + hashlib.sha256(b'{"b": 2}').hexdigest()]

    def test_a_duplicate_does_not_use_up_a_hit(self, client, mon_db, conversation_id, enqueued):
        token, _s, link, _m = make_link(mon_db, conversation_id, max_hits=2)
        for _ in range(3):
            client.post(f"/api/triggers/{token}", json={"same": True})
        with mon_db.connect() as conn:
            assert TriggerLinksRepository(conn).get(str(link["id"]))["hit_count"] == 1


class TestSignedLinks:
    def test_github(self, client, mon_db, conversation_id, enqueued):
        token, secret, *_ = make_link(mon_db, conversation_id, scheme="github")
        body = json.dumps({"action": "completed"}).encode()
        good = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers = {"Content-Type": "application/json", "X-GitHub-Delivery": "g-1"}
        bad = client.post(f"/api/triggers/{token}", data=body, headers={**headers, "X-Hub-Signature-256": "sha256=00"})
        missing = client.post(f"/api/triggers/{token}", data=body, headers=headers)
        assert bad.status_code == missing.status_code == 401
        ok = client.post(f"/api/triggers/{token}", data=body, headers={**headers, "X-Hub-Signature-256": good})
        assert ok.status_code == 202 and len(_hits(mon_db)) == 1

    def test_plain_hmac(self, client, mon_db, conversation_id, enqueued):
        token, secret, *_ = make_link(mon_db, conversation_id, scheme="hmac_sha256")
        body = b'{"x": 1}'
        sig = "sha256=" + signatures.hex_hmac(secret, body)
        assert client.post(f"/api/triggers/{token}", data=body, headers={"X-Signature": sig}).status_code == 202
        assert client.post(f"/api/triggers/{token}", data=body + b" ", headers={"X-Signature": sig}).status_code == 401

    def test_standard_webhooks_and_its_id_dedupes(self, client, mon_db, conversation_id, enqueued):
        token, secret, *_ = make_link(mon_db, conversation_id, scheme="standard_webhooks")
        body = b'{"type": "invoice.paid"}'
        now = int(time.time())
        headers = {
            "webhook-id": "msg_9",
            "webhook-timestamp": str(now),
            "webhook-signature": signatures.sign_standard(secret, "msg_9", now, body),
            "Content-Type": "application/json",
        }
        assert client.post(f"/api/triggers/{token}", data=body, headers=headers).status_code == 202
        assert client.post(f"/api/triggers/{token}", data=body, headers=headers).get_json()["duplicate"] is True
        stale = {
            **headers,
            "webhook-timestamp": str(now - 600),
            "webhook-signature": signatures.sign_standard(secret, "msg_9", now - 600, body),
        }
        assert client.post(f"/api/triggers/{token}", data=body, headers=stale).status_code == 401
        assert _hits(mon_db)[0]["dedupe_key"] == "wh:msg_9"

    def test_a_bad_signature_does_not_count_a_hit(self, client, mon_db, conversation_id, enqueued):
        token, _secret, link, _m = make_link(mon_db, conversation_id, scheme="github")
        client.post(f"/api/triggers/{token}", json={}, headers={"X-Hub-Signature-256": "sha256=00"})
        with mon_db.connect() as conn:
            assert TriggerLinksRepository(conn).get(str(link["id"]))["hit_count"] == 0

    def test_secrets_never_reach_the_logs(self, client, mon_db, conversation_id, enqueued, caplog):
        token, secret, *_ = make_link(mon_db, conversation_id, scheme="github")
        with caplog.at_level("DEBUG"):
            client.post(f"/api/triggers/{token}", json={}, headers={"X-Hub-Signature-256": "sha256=00"})
        assert secret not in caplog.text
