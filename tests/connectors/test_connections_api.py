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

    def test_same_bot_with_another_default_chat_is_another_connection(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionsList

        with _db(pg_conn):
            first = _call(app, ConnectionsList, "post", "/api/connections",
                          body={"connector_key": "telegram", "credentials": {"token": "123:abcdefgh"}})
            second = _call(app, ConnectionsList, "post", "/api/connections",
                           body={"connector_key": "telegram",
                                 "credentials": {"token": "123:abcdefgh", "chat_id": "-1001"}})
        assert first.status_code == 201 and second.status_code == 201
        assert first.get_json()["connection"]["id"] != second.get_json()["connection"]["id"]

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


class TestParameters:
    @staticmethod
    def _tool(pg_conn, user="alice"):
        cid = _connection(pg_conn, user=user, secrets={"credentials": {"token": "t"}})
        tool = service.ensure_connection_tools(pg_conn, user, service.ConnectorSessionsRepository(pg_conn).get(cid))[0]
        return cid, str(tool["id"])

    @staticmethod
    def _put(app, cid, tool_id, body, user="alice"):
        from docsgpt.api.connector.connections import ConnectionToolParameters

        return _call(app, ConnectionToolParameters, "put", f"/api/connections/{cid}/tools/{tool_id}/parameters",
                     user=user, body=body, args=[cid, tool_id])

    @staticmethod
    def _parameters(payload, action="telegram_send_message"):
        actions = {a["name"]: a for a in payload["tool"]["actions"]}
        return {p["name"]: p for p in actions[action]["parameters"]}

    def test_serialized_actions_list_their_parameters(self, pg_conn):
        cid, _ = self._tool(pg_conn)
        detail = service.connection_detail(pg_conn, service.ConnectorSessionsRepository(pg_conn).get(cid))
        action = next(a for a in detail["tools"][0]["actions"] if a["name"] == "telegram_send_message")
        names = [p["name"] for p in action["parameters"]]
        assert names == ["text", "chat_id"]
        chat_id = action["parameters"][1]
        assert chat_id["fixed"] is False and chat_id["value"] is None
        assert chat_id["type"] == "string"
        assert chat_id["description"]

    def test_owner_fixes_and_releases_a_parameter(self, app, pg_conn):
        cid, tool_id = self._tool(pg_conn)
        with _db(pg_conn):
            fixed = self._put(app, cid, tool_id, {"action": "telegram_send_message",
                                                  "parameters": {"chat_id": "-1001"}})
            assert fixed.status_code == 200
            chat_id = self._parameters(fixed.get_json())["chat_id"]
            assert chat_id["fixed"] is True and chat_id["value"] == "-1001"
            released = self._put(app, cid, tool_id, {"action": "telegram_send_message",
                                                     "parameters": {"chat_id": None}})
        chat_id = self._parameters(released.get_json())["chat_id"]
        assert chat_id["fixed"] is False and chat_id["value"] is None

    @pytest.mark.parametrize(
        "body",
        [
            {"action": "telegram_send_message", "parameters": {"token": "x"}},
            {"action": "not_an_action", "parameters": {"chat_id": "1"}},
            {"action": "telegram_send_message", "parameters": {"chat_id": ""}},
            {"action": "telegram_send_message", "parameters": "chat_id"},
            {"parameters": {"chat_id": "1"}},
        ],
    )
    def test_rejects_what_the_action_does_not_have(self, app, pg_conn, body):
        cid, tool_id = self._tool(pg_conn)
        with _db(pg_conn):
            resp = self._put(app, cid, tool_id, body)
        assert resp.status_code == 400

    def test_a_chat_set_on_the_account_shows_as_set_there(self, app, pg_conn):
        cid = _connection(pg_conn, secrets={"credentials": {"token": "t", "chat_id": "-1001"}})
        row = service.ConnectorSessionsRepository(pg_conn).get(cid)
        tool_id = str(service.ensure_connection_tools(pg_conn, "alice", row)[0]["id"])
        detail = service.connection_detail(pg_conn, row)
        action = next(a for a in detail["tools"][0]["actions"] if a["name"] == "telegram_send_message")
        chat_id = next(p for p in action["parameters"] if p["name"] == "chat_id")
        assert chat_id == {**chat_id, "fixed": True, "value": "-1001", "set_by": "account"}
        with _db(pg_conn):
            resp = self._put(app, cid, tool_id, {"action": "telegram_send_message", "parameters": {"text": "hi"}})
        chat_id = self._parameters(resp.get_json())["chat_id"]
        assert chat_id["set_by"] == "account"

    def test_another_user_cannot_fix_values(self, app, pg_conn):
        cid, tool_id = self._tool(pg_conn)
        with _db(pg_conn):
            resp = self._put(app, cid, tool_id, {"action": "telegram_send_message",
                                                 "parameters": {"chat_id": "666"}}, user="mallory")
        assert resp.status_code == 404
        stored = pg_conn.execute(
            text("SELECT actions FROM user_tools WHERE id = CAST(:i AS uuid)"), {"i": tool_id}
        ).scalar()
        chat_id = stored[0]["parameters"]["properties"]["chat_id"]
        assert chat_id["filled_by_llm"] is True


class TestRename:
    @staticmethod
    def _patch(app, cid, body, user="alice"):
        from docsgpt.api.connector.connections import ConnectionDetail

        return _call(app, ConnectionDetail, "patch", f"/api/connections/{cid}", user=user, body=body, args=[cid])

    def test_owner_names_and_unnames_an_account(self, app, pg_conn):
        cid = _connection(pg_conn, secrets={"credentials": {"token": "t"}})
        with _db(pg_conn):
            named = self._patch(app, cid, {"name": "  Alerts bot "})
            assert named.status_code == 200
            connection = named.get_json()["connection"]
            assert connection["account_name"] == "Alerts bot"
            # The label stays the account's identity.
            assert connection["account_label"] == "…abcd"
            cleared = self._patch(app, cid, {"name": ""})
        assert cleared.get_json()["connection"]["account_name"] is None

    @pytest.mark.parametrize("body", [{"name": "x" * 81}, {"name": 5}, {}])
    def test_rejects_bad_names(self, app, pg_conn, body):
        cid = _connection(pg_conn, secrets={})
        with _db(pg_conn):
            assert self._patch(app, cid, body).status_code == 400

    def test_another_user_cannot_rename(self, app, pg_conn):
        cid = _connection(pg_conn, secrets={})
        with _db(pg_conn):
            assert self._patch(app, cid, {"name": "Mine now"}, user="mallory").status_code == 404
        name = pg_conn.execute(
            text("SELECT account_name FROM connector_sessions WHERE id = CAST(:i AS uuid)"), {"i": cid}
        ).scalar()
        assert name is None


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
