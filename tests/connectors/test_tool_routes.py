"""Tests for creating and editing tools whose secret lives on a connection."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

import docsgpt.api.user  # noqa: F401  (import order: avoids the tools/tasks cycle)
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

    with patch.multiple("docsgpt.api.user.tools.routes", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.service", db_session=_yield, db_readonly=_yield):
        yield


def _call(app, resource, body, user="alice"):
    with app.test_request_context("/api/tools", method="POST", json=body):
        from flask import request

        request.decoded_token = {"sub": user}
        return resource().post()


def _telegram(token="123456:SECRETTOKEN", **extra):
    return {
        "name": "telegram",
        "displayName": "Telegram",
        "description": "Send messages",
        "config": {"token": token},
        "status": True,
        **extra,
    }


def _connection_row(conn, connection_id):
    return dict(conn.execute(
        text("SELECT * FROM connector_sessions WHERE id = CAST(:i AS uuid)"), {"i": connection_id}
    ).one()._mapping)


class TestCreateConnectedTool:
    def test_pasted_key_goes_on_a_connection_not_the_tool(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import CreateTool

        with _db(pg_conn):
            resp = _call(app, CreateTool, _telegram())
        assert resp.status_code == 200
        body = resp.get_json()
        tool = dict(pg_conn.execute(
            text("SELECT * FROM user_tools WHERE id = CAST(:i AS uuid)"), {"i": body["id"]}
        ).one()._mapping)
        assert str(tool["connection_id"]) == body["connection_id"]
        assert "SECRETTOKEN" not in str(tool["config"])
        assert "encrypted_credentials" not in (tool["config"] or {})
        row = _connection_row(pg_conn, body["connection_id"])
        assert service.read_secrets(row)["credentials"] == {"token": "123456:SECRETTOKEN"}

    def test_same_key_twice_shares_one_connection(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import CreateTool

        with _db(pg_conn):
            first = _call(app, CreateTool, _telegram()).get_json()
            second = _call(app, CreateTool, _telegram()).get_json()
        assert first["id"] != second["id"]
        assert first["connection_id"] == second["connection_id"]

    def test_existing_connection_is_used_by_id(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import CreateTool

        with _db(pg_conn):
            first = _call(app, CreateTool, _telegram()).get_json()
            resp = _call(app, CreateTool, _telegram(token="", connection_id=first["connection_id"]))
        assert resp.status_code == 200
        assert resp.get_json()["connection_id"] == first["connection_id"]

    def test_existing_connection_path_still_validates_the_config(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import CreateTool

        with _db(pg_conn):
            first = _call(app, CreateTool, _telegram()).get_json()
            with patch("docsgpt.api.user.tools.routes._validate_config",
                       return_value={"timeout": "Timeout must be between 1 and 300"}) as validate:
                resp = _call(app, CreateTool, _telegram(token="", connection_id=first["connection_id"]))
        assert resp.status_code == 400
        # The connection supplies the secret, so a missing key is not an error.
        assert validate.call_args.kwargs["has_existing_secrets"] is True

    def test_someone_elses_connection_is_not_found(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import CreateTool

        with _db(pg_conn):
            victims = _call(app, CreateTool, _telegram(), user="victim").get_json()
            resp = _call(app, CreateTool, _telegram(token="", connection_id=victims["connection_id"]))
        assert resp.status_code == 404

    def test_connection_of_another_service_is_not_found(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import CreateTool

        with _db(pg_conn):
            telegram = _call(app, CreateTool, _telegram()).get_json()
            resp = _call(app, CreateTool, {
                **_telegram(token=""), "name": "ntfy", "config": {}, "connection_id": telegram["connection_id"],
            })
        assert resp.status_code == 404

    def test_missing_key_is_a_validation_error(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import CreateTool

        with _db(pg_conn):
            resp = _call(app, CreateTool, _telegram(token=""))
        assert resp.status_code == 400

    def test_disabled_connector_is_refused(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import CreateTool
        from docsgpt.storage.db.repositories.connector_policies import ConnectorPoliciesRepository

        ConnectorPoliciesRepository(pg_conn).upsert("telegram", enabled=False)
        with _db(pg_conn):
            resp = _call(app, CreateTool, _telegram())
        assert resp.status_code == 403

    def test_default_key_on_multi_user_falls_back_to_the_tool(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import CreateTool

        with _db(pg_conn), patch.object(service, "ensure_can_store_credentials",
                                        side_effect=service.EncryptionKeyNotConfigured("set a key")):
            resp = _call(app, CreateTool, _telegram())
        assert resp.status_code == 200
        tool = dict(pg_conn.execute(
            text("SELECT * FROM user_tools WHERE id = CAST(:i AS uuid)"), {"i": resp.get_json()["id"]}
        ).one()._mapping)
        assert tool["connection_id"] is None
        assert "encrypted_credentials" in tool["config"]


class TestUpdateConnectedTool:
    def _create(self, app, pg_conn, user="alice"):
        from docsgpt.api.user.tools.routes import CreateTool

        with _db(pg_conn):
            return _call(app, CreateTool, _telegram(), user=user).get_json()

    def test_new_key_is_written_to_the_connection(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateTool

        created = self._create(app, pg_conn)
        with _db(pg_conn):
            resp = _call(app, UpdateTool, {"id": created["id"], "config": {"token": "999999:ROTATED"}})
        assert resp.status_code == 200
        row = _connection_row(pg_conn, created["connection_id"])
        assert service.read_secrets(row)["credentials"]["token"] == "999999:ROTATED"
        config = pg_conn.execute(
            text("SELECT config FROM user_tools WHERE id = CAST(:i AS uuid)"), {"i": created["id"]}
        ).scalar()
        assert "ROTATED" not in str(config)

    def test_new_key_replaces_unreadable_credentials(self, app, pg_conn):
        """After a lost encryption key, editing the tool is a way back in."""
        from docsgpt.api.user.tools.routes import UpdateTool

        created = self._create(app, pg_conn)
        pg_conn.execute(
            text("UPDATE connector_sessions SET encrypted_credentials = :b WHERE id = CAST(:i AS uuid)"),
            {"b": encrypt_json({"credentials": {"token": "x"}}, "someone-else"), "i": created["connection_id"]},
        )
        with _db(pg_conn):
            resp = _call(app, UpdateTool, {"id": created["id"], "config": {"token": "999999:ROTATED"}})
        assert resp.status_code == 200
        row = _connection_row(pg_conn, created["connection_id"])
        assert service.read_secrets(row)["credentials"] == {"token": "999999:ROTATED"}

    def test_editing_without_a_new_key_keeps_the_connection(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateTool

        created = self._create(app, pg_conn)
        with _db(pg_conn):
            resp = _call(app, UpdateTool, {"id": created["id"], "config": {}})
        assert resp.status_code == 200
        row = _connection_row(pg_conn, created["connection_id"])
        assert service.read_secrets(row)["credentials"]["token"] == "123456:SECRETTOKEN"

    def test_rejected_edit_leaves_the_connection_untouched(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import UpdateTool

        created = self._create(app, pg_conn)
        with _db(pg_conn), patch("docsgpt.api.user.tools.routes._validate_config",
                                 return_value={"timeout": "Timeout must be between 1 and 300"}):
            resp = _call(app, UpdateTool, {"id": created["id"], "config": {"token": "999999:ROTATED"}})
        assert resp.status_code == 400
        row = _connection_row(pg_conn, created["connection_id"])
        assert service.read_secrets(row)["credentials"]["token"] == "123456:SECRETTOKEN"
