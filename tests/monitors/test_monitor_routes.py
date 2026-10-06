"""Tests for the Monitors page routes: owner-scoped listing and pause / resume / cancel."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from docsgpt.core.settings import settings
from docsgpt.monitors import service
from docsgpt.monitors.checks import Content
from docsgpt.storage.db.repositories.conversations import ConversationsRepository


@pytest.fixture()
def client():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@contextmanager
def _as(sub):
    with (
        patch("docsgpt.app.handle_auth", return_value={"sub": sub}),
        patch("docsgpt.app.resolve_roles", return_value=["user"]),
    ):
        yield


@pytest.fixture()
def made(mon_db, conversation_id, monkeypatch, events):
    """A polled monitor and a webhook monitor of u1."""
    monkeypatch.setattr(settings, "PUBLIC_API_BASE_URL", "https://docs.example.com")
    monkeypatch.setattr(service, "fetch_webpage", lambda url, css_selector=None: Content(text="Price: $95"))
    caller = service.Caller(user_id="u1", conversation_id=conversation_id)
    polled = service.create(
        caller,
        {
            "description": "ACMEB below $90",
            "source": {"type": "webpage", "url": "https://shop.example.com/acmeb"},
            "check": {"type": "threshold", "op": "<", "value": 90},
            "on_match": "tell me",
        },
    )
    hook = service.create(
        caller,
        {"description": "CI done", "source": {"type": "webhook", "signature": "github"}, "on_match": "tell me"},
    )
    return polled["monitor_id"], hook["monitor_id"], hook


class TestList:
    def test_needs_a_user(self, client, mon_db):
        with patch("docsgpt.app.handle_auth", return_value=None):
            assert client.get("/api/monitors").status_code == 401

    def test_lists_only_the_callers_monitors_without_secrets(self, client, made, conversation_id, mon_db):
        polled_id, hook_id, hook = made
        with _as("u1"):
            body = client.get("/api/monitors").get_json()
        assert {m["monitor_id"] for m in body["monitors"]} == {polled_id, hook_id}
        text = str(body)
        token = hook["url"].rsplit("/", 1)[1]
        secret = TestRevealSecret._secret(None, mon_db, hook_id)
        assert token not in text and secret not in text and "token_hash" not in text
        assert "monitor_state" not in text and "secret_encrypted" not in text
        webhook = next(m for m in body["monitors"] if m["monitor_id"] == hook_id)
        assert webhook["links"][0]["kind"] == "webhook" and webhook["links"][0]["signature"] == "github"
        # The reference is not a secret: the model has it too.
        assert webhook["links"][0]["secret_ref"] == hook["secret"]
        polled = next(m for m in body["monitors"] if m["monitor_id"] == polled_id)
        assert polled["interval"] == "15m" and polled["wakes_left"] == 1 and polled["check_count"] == 1
        with _as("u2"):
            assert client.get("/api/monitors").get_json() == {"monitors": []}

    def test_filters(self, client, made, conversation_id, mon_db):
        polled_id, hook_id, _hook = made
        with mon_db.begin() as conn:
            other = str(ConversationsRepository(conn).create("u1", "other")["id"])
        with _as("u1"):
            assert len(client.get(f"/api/monitors?conversation_id={conversation_id}").get_json()["monitors"]) == 2
            assert client.get(f"/api/monitors?conversation_id={other}").get_json()["monitors"] == []
            assert client.get("/api/monitors?conversation_id=nope").status_code == 400
            client.post(f"/api/monitors/{hook_id}/cancel")
            live = client.get("/api/monitors?status=live").get_json()["monitors"]
        assert [m["monitor_id"] for m in live] == [polled_id]


class TestActions:
    def test_pause_resume_cancel(self, client, made, mon_db, events):
        polled_id, _hook_id, _hook = made
        with _as("u1"):
            paused = client.post(f"/api/monitors/{polled_id}/pause")
            assert paused.status_code == 200 and paused.get_json()["monitor"]["status"] == "paused"
            assert paused.get_json()["monitor"]["paused_reason"] == "paused by the user"
            assert client.post(f"/api/monitors/{polled_id}/pause").status_code == 409
            resumed = client.post(f"/api/monitors/{polled_id}/resume").get_json()["monitor"]
            assert resumed["status"] == "active" and resumed["next_check_at"] is not None
            cancelled = client.post(f"/api/monitors/{polled_id}/cancel").get_json()["monitor"]
            assert cancelled["status"] == "cancelled"
            assert client.post(f"/api/monitors/{polled_id}/resume").status_code == 409
        assert any(e["payload"]["status"] == "cancelled" for e in events)

    def test_someone_elses_monitor_is_404(self, client, made):
        polled_id, _hook_id, _hook = made
        with _as("u2"):
            assert client.get(f"/api/monitors/{polled_id}").status_code == 404
            assert client.post(f"/api/monitors/{polled_id}/cancel").status_code == 404
        with _as("u1"):
            assert client.get(f"/api/monitors/{polled_id}").get_json()["monitor"]["status"] == "active"

    def test_unknown_action(self, client, made):
        polled_id, _hook_id, _hook = made
        with _as("u1"):
            assert client.post(f"/api/monitors/{polled_id}/delete").status_code == 404


class TestRevealSecret:
    def _secret(self, mon_db, monitor_id):
        from sqlalchemy import text

        from docsgpt.monitors import links

        with mon_db.connect() as conn:
            sealed = conn.execute(
                text("SELECT secret_encrypted FROM trigger_links WHERE monitor_id = CAST(:m AS uuid)"),
                {"m": monitor_id},
            ).scalar()
        return links.open_secret(sealed, "u1")

    def test_the_owner_gets_the_secret_uncached_and_audited(self, client, made, mon_db, caplog):
        _polled_id, hook_id, hook = made
        with _as("u1"):
            response = client.get(f"/api/monitors/{hook_id}/secret")
        assert response.status_code == 200
        body = response.get_json()
        secret = self._secret(mon_db, hook_id)
        assert body == {"secret": secret, "signature": "github"}
        assert response.headers["Cache-Control"] == "no-store"
        assert hook["secret"] != secret and secret not in str(hook)
        assert secret not in caplog.text
        from sqlalchemy import text

        with mon_db.connect() as conn:
            audit = conn.execute(
                text("SELECT user_id, metadata::text FROM auth_events WHERE event = 'monitor.secret_revealed'")
            ).fetchall()
        assert len(audit) == 1 and audit[0][0] == "u1"
        assert hook_id in audit[0][1] and secret not in audit[0][1]

    def test_nobody_else_and_no_unsigned_or_ended_link(self, client, made):
        polled_id, hook_id, _hook = made
        with _as("u2"):
            assert client.get(f"/api/monitors/{hook_id}/secret").status_code == 404
        with patch("docsgpt.app.handle_auth", return_value=None):
            assert client.get(f"/api/monitors/{hook_id}/secret").status_code == 401
        with _as("u1"):
            assert client.get(f"/api/monitors/{polled_id}/secret").status_code == 404
            assert client.get("/api/monitors/not-a-uuid/secret").status_code == 404
            client.post(f"/api/monitors/{hook_id}/cancel")
            assert client.get(f"/api/monitors/{hook_id}/secret").status_code == 404

    def test_rate_limited(self, client, made, monkeypatch, fake_redis):
        from docsgpt.api.user.monitors import routes

        monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: fake_redis)
        _polled_id, hook_id, _hook = made
        with _as("u1"):
            statuses = [
                client.get(f"/api/monitors/{hook_id}/secret").status_code
                for _ in range(routes.SECRET_REVEALS_PER_MINUTE + 1)
            ]
        assert statuses[0] == 200 and statuses[-1] == 429

    def test_an_access_token_can_never_read_it(self):
        from docsgpt.api.pat.rules import DENIED

        assert DENIED["/api/monitors/<string:monitor_id>/secret"] == ("*",)



class TestSetSecret:
    def test_the_owner_sets_it_and_nobody_else_can(self, client, made, mon_db, caplog):
        _polled_id, hook_id, _hook = made
        value = "a-replacement-secret-0123456789"
        with _as("u2"):
            assert client.put(f"/api/monitors/{hook_id}/secret", json={"secret": value}).status_code == 404
        with _as("u1"):
            response = client.put(f"/api/monitors/{hook_id}/secret", json={"secret": value})
            assert response.status_code == 200 and response.get_json() == {"saved": True, "signature": "github"}
            assert response.headers["Cache-Control"] == "no-store"
            assert client.get(f"/api/monitors/{hook_id}/secret").get_json()["secret"] == value
        assert value not in caplog.text

    def test_bad_requests(self, client, made):
        polled_id, hook_id, _hook = made
        with _as("u1"):
            assert client.put(f"/api/monitors/{hook_id}/secret", json={}).status_code == 400
            bad = client.put(f"/api/monitors/{hook_id}/secret", json={"secret": "short"})
            assert bad.status_code == 400 and "16 to 512" in bad.get_json()["message"]
            assert "short" not in bad.get_json()["message"]
            assert client.put(f"/api/monitors/{polled_id}/secret",
                              json={"secret": "a-long-enough-secret-value"}).status_code == 404
        with patch("docsgpt.app.handle_auth", return_value=None):
            assert client.put(f"/api/monitors/{hook_id}/secret", json={"secret": "x" * 20}).status_code == 401

    def test_rate_limited(self, client, made, monkeypatch, fake_redis):
        from docsgpt.api.user.monitors import routes

        monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: fake_redis)
        _polled_id, hook_id, _hook = made
        with _as("u1"):
            statuses = [
                client.put(f"/api/monitors/{hook_id}/secret", json={"secret": "a-long-enough-secret-value"}
                           ).status_code
                for _ in range(routes.SECRET_REVEALS_PER_MINUTE + 1)
            ]
        assert statuses[0] == 200 and statuses[-1] == 429


class TestSecretExposure:
    def test_only_the_owner_turns_it_on_and_off(self, client, made):
        _polled_id, hook_id, _hook = made
        path = f"/api/monitors/{hook_id}/secret/exposure"
        with _as("u2"):
            assert client.put(path, json={"exposed": True}).status_code == 404
        with patch("docsgpt.app.handle_auth", return_value=None):
            assert client.put(path, json={"exposed": True}).status_code == 401
        with _as("u1"):
            assert client.put(path, json={"exposed": "yes"}).status_code == 400
            on = client.put(path, json={"exposed": True})
            assert on.status_code == 200 and on.get_json() == {"exposed": True}
            listed = client.get("/api/monitors").get_json()
            hook = next(m for m in listed["monitors"] if m["monitor_id"] == hook_id)
            assert hook["links"][0]["secret_exposed"] is True and "secret" not in hook["links"][0]
            assert client.put(path, json={"exposed": False}).get_json() == {"exposed": False}

    def test_an_access_token_can_never_change_it(self):
        from docsgpt.api.pat.rules import DENIED

        assert DENIED["/api/monitors/<string:monitor_id>/secret/exposure"] == ("*",)
