"""Routes: presence, the push public key, subscriptions, the unread mark, and the sidebar's unread flag."""

from __future__ import annotations

import base64
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from flask import Flask, request

from docsgpt.api.user.notifications import routes
from docsgpt.core.settings import settings
from docsgpt.notifications import presence, push
from docsgpt.storage.db.repositories.conversation_unread import ConversationUnreadRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.push_subscriptions import PushSubscriptionsRepository

CID = "11111111-1111-1111-1111-111111111111"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _subscription(endpoint="https://fcm.googleapis.com/fcm/send/abc"):
    key = ec.generate_private_key(ec.SECP256R1())
    p256dh = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"endpoint": endpoint, "expirationTime": None, "keys": {"p256dh": _b64(p256dh), "auth": _b64(os.urandom(16))}}


@pytest.fixture()
def app():
    return Flask(__name__)


@pytest.fixture()
def db(pg_engine, monkeypatch):
    monkeypatch.setattr("docsgpt.storage.db.engine._engine", pg_engine)
    return pg_engine


@pytest.fixture()
def vapid(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(settings, "WEBPUSH_VAPID_PRIVATE_KEY", _b64(key.private_numbers().private_value.to_bytes(32, "big")))
    monkeypatch.setattr(settings, "WEBPUSH_VAPID_PUBLIC_KEY", None)
    push._load_vapid.cache_clear()
    yield
    push._load_vapid.cache_clear()


def _call(app, resource, method, path="/x", *, user="u1", json=None, **kwargs):
    with app.test_request_context(path, method=method.upper(), json=json):
        request.decoded_token = {"sub": user} if user else None
        return getattr(resource(), method)(**kwargs)


class TestPresenceRoute:
    def test_reports_and_closes(self, app, fake_redis):
        body = {"tab_id": "tab-1", "conversation_id": CID, "visible": True}
        response = _call(app, routes.Presence, "post", json=body)
        assert response.status_code == 200
        assert response.get_json() == {"success": True, "stored": True}
        assert presence.is_watching("u1", CID)
        _call(app, routes.Presence, "post", json={**body, "closing": True})
        assert not presence.is_watching("u1", CID)

    def test_null_conversation_and_default_visibility(self, app, fake_redis):
        assert _call(app, routes.Presence, "post", json={"tab_id": "t", "conversation_id": None}).status_code == 200
        assert presence.tabs("u1")[0]["visible"] is False

    @pytest.mark.parametrize(
        "body",
        [
            None,
            {"conversation_id": CID, "visible": True},
            {"tab_id": "", "visible": True},
            {"tab_id": "x" * 65, "visible": True},
            {"tab_id": "bad tab", "visible": True},
            {"tab_id": "t", "conversation_id": "not-a-uuid", "visible": True},
            {"tab_id": "t", "visible": "yes"},
            {"tab_id": "t", "visible": True, "closing": 1},
        ],
    )
    def test_rejects_bad_reports(self, app, fake_redis, body):
        assert _call(app, routes.Presence, "post", json=body).status_code == 400

    def test_needs_a_user(self, app):
        assert _call(app, routes.Presence, "post", user=None, json={"tab_id": "t"}).status_code == 401

    def test_redis_down_still_answers(self, app, fake_redis):
        fake_redis.fail = True
        response = _call(app, routes.Presence, "post", json={"tab_id": "t", "visible": True})
        assert response.status_code == 200 and response.get_json()["stored"] is False


class TestPublicKey:
    def test_off(self, app, monkeypatch):
        monkeypatch.setattr(settings, "WEBPUSH_VAPID_PRIVATE_KEY", None)
        assert _call(app, routes.PushPublicKey, "get").get_json() == {"enabled": False, "public_key": None}

    def test_on(self, app, vapid):
        body = _call(app, routes.PushPublicKey, "get").get_json()
        assert body["enabled"] is True
        assert len(base64.urlsafe_b64decode(body["public_key"] + "==")) == 65

    def test_needs_a_user(self, app):
        assert _call(app, routes.PushPublicKey, "get", user=None).status_code == 401


class TestSubscriptions:
    def _rows(self, db, user_id="u1"):
        with db.connect() as conn:
            return PushSubscriptionsRepository(conn).list_for_user(user_id)

    def test_save_and_delete(self, app, db, vapid):
        sub = _subscription()
        with app.test_request_context("/x", method="POST", json=sub, headers={"User-Agent": "Firefox/140"}):
            request.decoded_token = {"sub": "u1"}
            assert routes.PushSubscriptions().post().status_code == 201
        [row] = self._rows(db)
        assert row["endpoint"] == sub["endpoint"] and row["user_agent"] == "Firefox/140"
        assert _call(app, routes.PushSubscriptions, "delete", json={"endpoint": sub["endpoint"]}).get_json() == {
            "success": True,
            "deleted": True,
        }
        assert self._rows(db) == []
        deleted = _call(app, routes.PushSubscriptions, "delete", path=f"/x?endpoint={sub['endpoint']}")
        assert deleted.get_json()["deleted"] is False

    def test_rejects_endpoints_outside_the_allowlist(self, app, db, vapid):
        for endpoint in ("https://evil.example.com/x", "http://fcm.googleapis.com/x", "https://10.0.0.1/x"):
            response = _call(app, routes.PushSubscriptions, "post", json=_subscription(endpoint))
            assert response.status_code == 400
        assert self._rows(db) == []

    def test_extra_hosts_are_accepted(self, app, db, vapid, monkeypatch):
        monkeypatch.setattr(settings, "WEBPUSH_EXTRA_ALLOWED_HOSTS", ["*.trycloudflare.com"])
        response = _call(app, routes.PushSubscriptions, "post", json=_subscription("https://a-b.trycloudflare.com/sink/push-s05"))
        assert response.status_code == 201

    def test_503_when_push_is_off(self, app, db, monkeypatch):
        monkeypatch.setattr(settings, "WEBPUSH_VAPID_PRIVATE_KEY", None)
        assert _call(app, routes.PushSubscriptions, "post", json=_subscription()).status_code == 503

    def test_keeps_a_bounded_number_per_user(self, app, db, vapid, monkeypatch):
        monkeypatch.setattr(routes, "MAX_SUBSCRIPTIONS_PER_USER", 2)
        for i in range(3):
            _call(app, routes.PushSubscriptions, "post", json=_subscription(f"https://fcm.googleapis.com/{i}"))
        assert sorted(r["endpoint"] for r in self._rows(db)) == ["https://fcm.googleapis.com/1", "https://fcm.googleapis.com/2"]

    def test_delete_needs_an_endpoint_and_a_user(self, app):
        assert _call(app, routes.PushSubscriptions, "delete", json={}).status_code == 400
        assert _call(app, routes.PushSubscriptions, "delete", user=None).status_code == 401
        assert _call(app, routes.PushSubscriptions, "post", user=None).status_code == 401

    def test_database_errors_answer_500(self, app, vapid, monkeypatch):
        monkeypatch.setattr(routes, "db_session", lambda: (_ for _ in ()).throw(RuntimeError("db")))
        assert _call(app, routes.PushSubscriptions, "post", json=_subscription()).status_code == 500
        assert _call(app, routes.PushSubscriptions, "delete", json={"endpoint": "x"}).status_code == 500
        assert _call(app, routes.ConversationRead, "post", conversation_id=CID).status_code == 500


class TestConversationRead:
    def test_clears_the_mark_and_the_listing_shows_it(self, app, db):
        from docsgpt.api.user.conversations.routes import GetConversations

        with db.begin() as conn:
            cid = str(ConversationsRepository(conn).create("u1", "chat")["id"])
            ConversationUnreadRepository(conn).mark_unread(cid, "u1")
        listed = _call(app, GetConversations, "get", path="/api/get_conversations").get_json()
        assert [c["unread"] for c in listed if c["id"] == cid] == [True]

        assert _call(app, routes.ConversationRead, "post", conversation_id=cid).get_json() == {
            "success": True,
            "cleared": True,
        }
        assert _call(app, routes.ConversationRead, "post", conversation_id=cid).get_json()["cleared"] is False
        listed = _call(app, GetConversations, "get", path="/api/get_conversations").get_json()
        assert [c["unread"] for c in listed if c["id"] == cid] == [False]

    def test_another_users_conversation_is_untouched(self, app, db):
        with db.begin() as conn:
            cid = str(ConversationsRepository(conn).create("u1", "chat")["id"])
            ConversationUnreadRepository(conn).mark_unread(cid, "u1")
        assert _call(app, routes.ConversationRead, "post", user="u2", conversation_id=cid).get_json()["cleared"] is False

    def test_bad_input(self, app):
        assert _call(app, routes.ConversationRead, "post", conversation_id="nope").status_code == 400
        assert _call(app, routes.ConversationRead, "post", user=None, conversation_id=CID).status_code == 401


class TestRegistration:
    def test_routes_are_on_the_api(self):
        from docsgpt.app import app as flask_app

        rules = {rule.rule for rule in flask_app.url_map.iter_rules()}
        assert {
            "/api/presence",
            "/api/push/public_key",
            "/api/push/subscriptions",
            "/api/conversations/<string:conversation_id>/read",
        } <= rules
