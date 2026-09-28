"""Tests for the connection write endpoints."""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.connectors import service
from docsgpt.security.encryption import encrypt_json


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch.multiple("docsgpt.api.connector.connections", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.service", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.api.connector.routes", db_session=_yield, db_readonly=_yield):
        yield


def _call(app, resource, method, path, user="alice", body=None, headers=None, args=()):
    with app.test_request_context(path, method=method.upper(), json=body, headers=headers or {}):
        from flask import request

        request.decoded_token = {"sub": user} if user else None
        return getattr(resource(), method)(*args)


def _connection(conn, user="alice", provider="telegram", auth_kind="api_key", secrets=None, status="connected",
                **cols) -> str:
    values = {
        "user_id": user, "provider": provider, "connector_key": provider, "auth_kind": auth_kind,
        "status": status, "account_label": cols.pop("account_label", "…abcd"),
        "encrypted_credentials": encrypt_json(secrets, user) if secrets is not None else None, **cols,
    }
    names = ", ".join(values)
    params = ", ".join(f":{k}" for k in values)
    return str(conn.execute(
        text(f"INSERT INTO connector_sessions ({names}) VALUES ({params}) RETURNING id"), values,
    ).scalar())


class TestCreate:
    def test_telegram_zero_question_setup(self, app, pg_conn):
        """Appendix C of the connectors spec: create, then set up, tools appear."""
        from docsgpt.api.connector.connections import ConnectionSetup, ConnectionsList

        with _db(pg_conn):
            created = _call(app, ConnectionsList, "post", "/api/connections",
                            body={"connector_key": "telegram", "credentials": {"token": "123:abcdefgh"}})
            assert created.status_code == 201
            payload = created.get_json()
            assert payload["setup"] == {"tools": "auto", "sync": "off"}
            assert "token" not in json.dumps(payload)
            cid = payload["connection"]["id"]
            setup = _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup",
                          body={"create_tools": True}, args=[cid])
        assert setup.status_code == 200
        tools = setup.get_json()["tools"]
        assert [t["name"] for t in tools] == ["telegram"]
        actions = {a["name"]: a for a in tools[0]["actions"]}
        assert actions["telegram_send_message"]["access"] == "write"
        assert actions["telegram_send_message"]["permission"] == "ask"

    def test_setup_is_idempotent_for_tools(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionSetup

        cid = _connection(pg_conn, secrets={"credentials": {"token": "t"}})
        with _db(pg_conn):
            for _ in range(2):
                _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup",
                      body={"create_tools": True}, args=[cid])
        count = pg_conn.execute(
            text("SELECT count(*) FROM user_tools WHERE connection_id = CAST(:c AS uuid)"), {"c": cid},
        ).scalar()
        assert count == 1

    def test_rejects_oauth_connector(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionsList

        with _db(pg_conn):
            resp = _call(app, ConnectionsList, "post", "/api/connections",
                         body={"connector_key": "google_drive", "credentials": {}})
        assert resp.status_code == 400

    def test_default_key_refused(self, app, pg_conn, monkeypatch):
        from docsgpt.api.connector.connections import ConnectionsList
        from docsgpt.core.settings import settings
        from docsgpt.security.encryption import DEFAULT_ENCRYPTION_KEY

        monkeypatch.setattr(settings, "ENCRYPTION_SECRET_KEY", DEFAULT_ENCRYPTION_KEY)
        monkeypatch.setattr(settings, "AUTH_TYPE", "oidc")
        with _db(pg_conn):
            resp = _call(app, ConnectionsList, "post", "/api/connections",
                         body={"connector_key": "brave", "credentials": {"token": "some-long-key"}})
        assert resp.status_code == 400
        assert resp.get_json()["code"] == "encryption_key_default"


class TestSetupSync:
    def test_oauth_source_is_queued_with_connection(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionSetup

        cid = _connection(pg_conn, provider="google_drive", auth_kind="oauth", secrets={"token_info": {}})
        task = MagicMock(id="task-1")
        with _db(pg_conn), patch("docsgpt.api.user.tasks.ingest_connector_task.apply_async",
                                 return_value=task) as apply:
            resp = _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup", body={
                "create_tools": True,
                "sync": {"items": {"folder_ids": ["f1"]}, "frequency": "weekly", "name": "Handbook"},
            }, args=[cid])
        assert resp.status_code == 200
        source = resp.get_json()["sources"][0]
        assert source["name"] == "Handbook" and source["sync_frequency"] == "weekly"
        kwargs = apply.call_args.kwargs["kwargs"]
        assert kwargs["connection_id"] == cid
        assert kwargs["folder_ids"] == ["f1"]
        assert "session_token" not in kwargs
        # Drive has no tools; nothing was created.
        assert resp.get_json()["tools"] == []

    def test_nothing_picked_is_a_bad_request(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionSetup

        cid = _connection(pg_conn, provider="google_drive", auth_kind="oauth", secrets={"token_info": {}})
        with _db(pg_conn):
            resp = _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup",
                         body={"sync": {"items": {}}}, args=[cid])
        assert resp.status_code == 400

    def test_rejected_request_does_not_claim_its_idempotency_key(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionSetup

        @contextmanager
        def _yield():
            yield pg_conn

        cid = _connection(pg_conn, provider="google_drive", auth_kind="oauth", secrets={"token_info": {}})
        headers = {"Idempotency-Key": "setup-retry-1"}
        with _db(pg_conn), patch("docsgpt.api.user.sources.upload.db_session", _yield), patch(
            "docsgpt.api.user.tasks.ingest_connector_task.apply_async", return_value=MagicMock(id="t"),
        ) as apply:
            bad = _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup",
                        body={"sync": {"items": {}}}, headers=headers, args=[cid])
            fixed = _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup",
                          body={"sync": {"items": {"folder_ids": ["f1"]}}}, headers=headers, args=[cid])
        assert bad.status_code == 400
        assert fixed.status_code == 200
        apply.assert_called_once()

    def test_s3_keys_stay_on_the_connection(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionSetup

        cid = _connection(pg_conn, provider="s3", secrets={"credentials": {
            "aws_access_key_id": "AKIA", "aws_secret_access_key": "shh-secret"}})
        with _db(pg_conn), patch("docsgpt.api.user.tasks.ingest_remote.apply_async",
                                 return_value=MagicMock(id="t")) as apply:
            resp = _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup", body={
                "sync": {"items": {"bucket": "docs", "aws_secret_access_key": "smuggled"}},
            }, args=[cid])
        assert resp.status_code == 200
        kwargs = apply.call_args.kwargs["kwargs"]
        assert kwargs["source_data"] == {"bucket": "docs"}
        assert kwargs["connection_id"] == cid

    def test_flagged_connection_must_reconnect_first(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionSetup

        cid = _connection(pg_conn, status="reconnect_needed", secrets={})
        with _db(pg_conn):
            resp = _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup",
                         body={}, args=[cid])
        assert resp.status_code == 409


class TestReconnect:
    def test_api_key_reconnect_replaces_and_resumes(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionReconnect

        cid = _connection(pg_conn, status="reconnect_needed", secrets={"credentials": {"token": "old"}})
        pg_conn.execute(text(
            "INSERT INTO sources (user_id, name, connection_id, metadata) "
            "VALUES ('alice', 's', CAST(:c AS uuid), '{\"sync_state\": \"paused_reconnect\"}')"
        ), {"c": cid})
        with _db(pg_conn):
            resp = _call(app, ConnectionReconnect, "post", f"/api/connections/{cid}/reconnect",
                         body={"credentials": {"token": "new"}}, args=[cid])
        assert resp.status_code == 200
        assert resp.get_json()["connection"]["status"] == "connected"
        row = pg_conn.execute(text("SELECT * FROM connector_sessions WHERE id = CAST(:c AS uuid)"),
                              {"c": cid}).one()._mapping
        assert service.read_secrets(dict(row))["credentials"]["token"] == "new"
        meta = pg_conn.execute(text("SELECT metadata FROM sources WHERE user_id = 'alice'")).scalar()
        assert "sync_state" not in meta

    def test_reconnect_recovers_undecryptable_credentials_without_a_second_write(self, app, pg_conn):
        """After a lost key the reconnect replaces the blob; it must not flag the row it holds locked."""
        from docsgpt.api.connector.connections import ConnectionReconnect

        cid = _connection(pg_conn, status="reconnect_needed")
        pg_conn.execute(text(
            "UPDATE connector_sessions SET encrypted_credentials = :blob WHERE id = CAST(:c AS uuid)"
        ), {"c": cid, "blob": encrypt_json({"credentials": {"token": "old"}}, "someone-else")})
        with _db(pg_conn), patch.object(service, "mark_reconnect_needed") as flag:
            resp = _call(app, ConnectionReconnect, "post", f"/api/connections/{cid}/reconnect",
                         body={"credentials": {"token": "new"}}, args=[cid])
        assert resp.status_code == 200
        flag.assert_not_called()
        row = pg_conn.execute(text("SELECT * FROM connector_sessions WHERE id = CAST(:c AS uuid)"),
                              {"c": cid}).one()._mapping
        assert service.read_secrets(dict(row))["credentials"] == {"token": "new"}

    def test_oauth_reconnect_returns_authorization_url(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionReconnect

        cid = _connection(pg_conn, provider="google_drive", auth_kind="oauth", secrets={})
        fake_auth = MagicMock()
        fake_auth.get_authorization_url.return_value = "https://accounts.example/auth"
        with _db(pg_conn), patch("docsgpt.api.connector.routes.ConnectorCreator.create_auth",
                                 return_value=fake_auth):
            resp = _call(app, ConnectionReconnect, "post", f"/api/connections/{cid}/reconnect",
                         body={}, args=[cid])
        assert resp.get_json()["authorization_url"] == "https://accounts.example/auth"
        state = fake_auth.get_authorization_url.call_args.kwargs["state"]
        import base64

        assert json.loads(base64.urlsafe_b64decode(state))["object_id"] == cid

    def test_cannot_reconnect_someone_elses(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionReconnect

        cid = _connection(pg_conn, user="bob", secrets={})
        with _db(pg_conn):
            resp = _call(app, ConnectionReconnect, "post", f"/api/connections/{cid}/reconnect",
                         body={"credentials": {"token": "x"}}, args=[cid])
        assert resp.status_code == 404


class TestPickerToken:
    def test_returns_access_token_only(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionPickerToken

        cid = _connection(pg_conn, provider="google_drive", auth_kind="oauth",
                          secrets={"token_info": {"access_token": "at", "refresh_token": "rt"}})
        fake_auth = MagicMock()
        fake_auth.is_token_expired.return_value = False
        with _db(pg_conn), patch("docsgpt.parser.connectors.connector_creator.ConnectorCreator.create_auth",
                                 return_value=fake_auth):
            resp = _call(app, ConnectionPickerToken, "post", f"/api/connections/{cid}/picker-token",
                         args=[cid])
        payload = resp.get_json()
        assert payload["access_token"] == "at"
        assert "rt" not in json.dumps(payload)

    def test_owner_only(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionPickerToken

        cid = _connection(pg_conn, user="bob", provider="google_drive", auth_kind="oauth", secrets={})
        with _db(pg_conn):
            resp = _call(app, ConnectionPickerToken, "post", f"/api/connections/{cid}/picker-token",
                         args=[cid])
        assert resp.status_code == 404


class TestClaim:
    def test_claims_own_token(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionClaim

        cid = _connection(pg_conn, provider="google_drive", auth_kind="oauth", secrets={}, session_token="legacy")
        with _db(pg_conn):
            resp = _call(app, ConnectionClaim, "post", "/api/connections/claim",
                         body={"provider": "google_drive", "session_token": "legacy"})
        assert resp.get_json()["connection_id"] == cid

    def test_other_users_token_is_not_found(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionClaim

        _connection(pg_conn, user="bob", provider="google_drive", auth_kind="oauth", secrets={}, session_token="b")
        with _db(pg_conn):
            resp = _call(app, ConnectionClaim, "post", "/api/connections/claim",
                         body={"provider": "google_drive", "session_token": "b"})
        assert resp.status_code == 404


class TestPermissions:
    def test_set_permissions(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionToolPermissions

        cid = _connection(pg_conn, secrets={"credentials": {"token": "t"}})
        with _db(pg_conn):
            tool = service.ensure_connection_tools(pg_conn, "alice", service.ConnectorSessionsRepository(
                pg_conn).get(cid))[0]
            resp = _call(app, ConnectionToolPermissions, "put",
                         f"/api/connections/{cid}/tools/{tool['id']}/permissions",
                         body={"permissions": {"telegram_send_image": "off", "telegram_send_message": "always"}},
                         args=[cid, str(tool["id"])])
        actions = {a["name"]: a["permission"] for a in resp.get_json()["tool"]["actions"]}
        assert actions == {"telegram_send_message": "always", "telegram_send_image": "off"}

    def test_rejects_unknown_permission(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionToolPermissions

        cid = _connection(pg_conn, secrets={})
        with _db(pg_conn):
            resp = _call(app, ConnectionToolPermissions, "put", "/x", body={"permissions": {"a": "maybe"}},
                         args=[cid, "t"])
        assert resp.status_code == 400


class TestDelete:
    def test_delete_with_source_removal(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionDetail

        cid = _connection(pg_conn, provider="google_drive", auth_kind="oauth", secrets={})
        pg_conn.execute(text("INSERT INTO sources (user_id, name, connection_id) VALUES ('alice', 's', CAST(:c AS uuid))"),
                        {"c": cid})
        with _db(pg_conn), patch("docsgpt.connectors.service.revoke_at_provider"), patch(
            "docsgpt.api.user.sources.routes.delete_source", return_value=True
        ) as delete_source:
            resp = _call(app, ConnectionDetail, "delete", f"/api/connections/{cid}",
                         body={"sources": "delete"}, args=[cid])
        assert resp.status_code == 200
        assert delete_source.call_count == 1

    def test_bad_mode(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionDetail

        cid = _connection(pg_conn, secrets={})
        with _db(pg_conn):
            resp = _call(app, ConnectionDetail, "delete", "/x", body={"sources": "burn"}, args=[cid])
        assert resp.status_code == 400


class TestNoSecretsInResponses:
    def test_list_and_detail(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionDetail, ConnectionsList

        cid = _connection(pg_conn, secrets={"credentials": {"token": "super-secret-value"}},
                          session_token="sess-tok")
        with _db(pg_conn):
            listed = _call(app, ConnectionsList, "get", "/api/connections")
            detail = _call(app, ConnectionDetail, "get", f"/api/connections/{cid}", args=[cid])
        for resp in (listed, detail):
            body = json.dumps(resp.get_json())
            assert "super-secret-value" not in body
            assert "sess-tok" not in body
            assert "v2:" not in body
