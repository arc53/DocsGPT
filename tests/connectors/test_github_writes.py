"""GitHub write access: opted into per connection, forbidden by an admin, enforced at run time."""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from sqlalchemy import text

import docsgpt.api.user  # noqa: F401  (loads mcp_tool without the circular import)
import docsgpt.agents.tools.mcp_tool  # noqa: F401,E402  (patched below)
from docsgpt.connectors import catalog, mcp, service
from docsgpt.security.encryption import encrypt_json

READONLY_MCP = "https://api.githubcopilot.com/mcp/readonly"
WRITE_MCP = "https://api.githubcopilot.com/mcp/"


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch.multiple("docsgpt.api.connector.connections", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.api.admin.connectors", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.service", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.mcp", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.resolve", db_readonly=_yield):
        yield


def _call(app, resource, method, path, user="alice", body=None, args=(), roles=None):
    with app.test_request_context(path, method=method.upper(), json=body):
        from flask import request

        request.decoded_token = {"sub": user, "roles": roles or ["user"]} if user else None
        return getattr(resource(), method)(*args)


def _connection(conn, user="alice") -> str:
    return str(conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, account_label, "
            "encrypted_credentials) VALUES (:u, 'github', 'github', 'api_key', 'connected', 'octocat', :e) "
            "RETURNING id"
        ),
        {"u": user, "e": encrypt_json({"credentials": {"access_token": "github_pat_alice"}}, user)},
    ).scalar())


def _tool(conn, cid, server_url, actions) -> str:
    return str(conn.execute(
        text(
            "INSERT INTO user_tools (user_id, name, config, actions, connection_id) VALUES ('alice', 'mcp_tool', "
            "CAST(:c AS jsonb), CAST(:a AS jsonb), CAST(:cid AS uuid)) RETURNING id"
        ),
        {"c": json.dumps({"server_url": server_url, "auth_type": "bearer", "transport_type": "http", "timeout": 30}),
         "a": json.dumps(actions), "cid": cid},
    ).scalar())


def _row(conn, cid) -> dict:
    return dict(conn.execute(
        text("SELECT * FROM connector_sessions WHERE id = CAST(:c AS uuid)"), {"c": cid},
    ).one()._mapping)


def _stored(conn, cid) -> tuple[dict, dict]:
    config, actions = conn.execute(
        text("SELECT config, actions FROM user_tools WHERE connection_id = CAST(:c AS uuid)"), {"c": cid},
    ).one()
    return config, {a["name"]: a for a in actions}


def _forbid(conn):
    from docsgpt.storage.db.repositories.app_metadata import AppMetadataRepository
    from docsgpt.storage.db.repositories.connector_policies import allow_writes_key

    AppMetadataRepository(conn).set(allow_writes_key("github"), "false")


def _action(name, read_only=None):
    action = {"name": name, "description": name,
              "parameters": {"type": "object", "properties": {"owner": {"type": "string"}}}}
    if read_only is not None:
        action["annotations"] = {"readOnlyHint": read_only}
    return action


# What GitHub's servers list: the read-only endpoint only reads; the full one
# adds writes, annotated ``readOnlyHint: false`` (or not annotated at all).
READ_ACTIONS = [_action("get_issue", True), _action("search_code", True)]
WRITE_ACTIONS = READ_ACTIONS + [
    _action("create_issue", False),
    _action("add_issue_comment", False),
    _action("mark_all_notifications_read"),
]


def _fake_discovery(calls):
    """Stands in for GitHub's MCP server: lists the actions of the endpoint asked for."""

    def discover(user_id, connection, tool):
        url = tool["config"]["server_url"]
        calls.append(url)
        return [dict(a) for a in (WRITE_ACTIONS if url == WRITE_MCP else READ_ACTIONS)]

    return discover


class TestCatalog:
    def test_github_offers_writes_on_its_full_endpoint(self):
        definition = catalog.get_definition("github")
        assert definition.mcp_url == READONLY_MCP
        assert definition.mcp_write_url == WRITE_MCP
        assert definition.to_dict()["writes_opt_in"] is True
        assert catalog.get_definition("telegram").to_dict()["writes_opt_in"] is False

    def test_members_see_whether_writes_are_allowed(self, pg_conn):
        entries = {e["key"]: e for e in service.catalog_for_user(pg_conn, "alice", is_admin=False)}
        assert entries["github"]["writes_allowed"] is True
        assert entries["telegram"]["writes_allowed"] is False
        _forbid(pg_conn)
        entries = {e["key"]: e for e in service.catalog_for_user(pg_conn, "alice", is_admin=False)}
        assert entries["github"]["writes_allowed"] is False

    def test_builtin_config_picks_the_endpoint(self):
        definition = catalog.get_definition("github")
        assert service.builtin_mcp_config(definition)["server_url"] == READONLY_MCP
        assert service.builtin_mcp_config(definition, writes=True)["server_url"] == WRITE_MCP


class TestClassification:
    def test_full_endpoint_actions_are_writes_unless_marked_read_only(self):
        """A GitHub action is a read only when GitHub says so: a name like
        ``mark_all_notifications_read`` must not pass for one."""
        connection = {"id": "c1", "auth_kind": "api_key", "status": "connected", "connector_key": "github"}
        fake = MagicMock()
        fake.get_actions_metadata.return_value = [dict(a) for a in WRITE_ACTIONS]
        with patch.object(service, "access_credentials", return_value={"access_token": "t"}), \
                patch("docsgpt.agents.tools.mcp_tool.MCPTool", return_value=fake):
            actions = mcp.discover_builtin_actions("alice", connection, writes=True)
        access = {a["name"]: a["access"] for a in actions}
        assert access == {
            "get_issue": "read", "search_code": "read",
            "create_issue": "write", "add_issue_comment": "write", "mark_all_notifications_read": "write",
        }


class TestSetup:
    def test_opting_in_uses_the_full_endpoint_and_writes_ask_first(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionDetail, ConnectionSetup

        cid = _connection(pg_conn)
        calls = []
        with _db(pg_conn), patch.object(mcp, "_discover", side_effect=_fake_discovery(calls)):
            resp = _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup",
                         body={"create_tools": True, "allow_writes": True}, args=[cid])
            detail = _call(app, ConnectionDetail, "get", f"/api/connections/{cid}", args=[cid]).get_json()
        assert resp.status_code == 200
        assert calls == [WRITE_MCP]
        config, actions = _stored(pg_conn, cid)
        assert config["server_url"] == WRITE_MCP
        assert actions["create_issue"]["access"] == "write" and actions["create_issue"]["require_approval"] is True
        assert actions["mark_all_notifications_read"]["access"] == "write"
        assert actions["get_issue"]["access"] == "read" and not actions["get_issue"].get("require_approval")
        assert detail["connection"]["writes"] is True
        permissions = {a["name"]: a["permission"] for a in detail["connection"]["tools"][0]["actions"]}
        assert permissions["create_issue"] == "ask" and permissions["get_issue"] == "always"

    def test_read_only_is_the_default(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionDetail, ConnectionSetup

        cid = _connection(pg_conn)
        calls = []
        with _db(pg_conn), patch.object(mcp, "_discover", side_effect=_fake_discovery(calls)):
            _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup",
                  body={"create_tools": True}, args=[cid])
            detail = _call(app, ConnectionDetail, "get", f"/api/connections/{cid}", args=[cid]).get_json()
        assert calls == [READONLY_MCP]
        assert _stored(pg_conn, cid)[0]["server_url"] == READONLY_MCP
        assert detail["connection"]["writes"] is False

    def test_forbidden_writes_are_refused(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionSetup

        cid = _connection(pg_conn)
        _forbid(pg_conn)
        with _db(pg_conn), patch.object(mcp, "_discover") as discover:
            resp = _call(app, ConnectionSetup, "post", f"/api/connections/{cid}/setup",
                         body={"create_tools": True, "allow_writes": True}, args=[cid])
        assert resp.status_code == 403
        assert resp.get_json()["code"] == "writes_forbidden"
        discover.assert_not_called()
        assert pg_conn.execute(text("SELECT count(*) FROM user_tools")).scalar() == 0


class TestSwitchWrites:
    def _read_only_tool(self, conn, cid):
        actions = mcp.apply_default_permissions("mcp_tool", service._transform_actions(
            [dict(a) for a in READ_ACTIONS]))
        # The user turned one read off; that choice survives switching.
        actions = [{**a, "active": a["name"] != "search_code"} for a in actions]
        return _tool(conn, cid, READONLY_MCP, actions)

    def test_turning_writes_on_and_off_keeps_choices(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionWrites

        cid = _connection(pg_conn)
        self._read_only_tool(pg_conn, cid)
        calls = []
        with _db(pg_conn), patch.object(mcp, "_discover", side_effect=_fake_discovery(calls)):
            on = _call(app, ConnectionWrites, "put", f"/api/connections/{cid}/writes",
                       body={"allow": True}, args=[cid])
            config, actions = _stored(pg_conn, cid)
            assert on.status_code == 200
            assert on.get_json()["writes"] is True
            assert sorted(on.get_json()["added"]) == ["add_issue_comment", "create_issue",
                                                       "mark_all_notifications_read"]
            assert config["server_url"] == WRITE_MCP
            assert actions["search_code"]["active"] is False
            assert actions["create_issue"]["require_approval"] is True
            off = _call(app, ConnectionWrites, "put", f"/api/connections/{cid}/writes",
                        body={"allow": False}, args=[cid])
        assert calls == [WRITE_MCP, READONLY_MCP]
        config, actions = _stored(pg_conn, cid)
        assert off.get_json()["writes"] is False
        assert config["server_url"] == READONLY_MCP
        assert set(actions) == {"get_issue", "search_code"}
        assert actions["search_code"]["active"] is False

    def test_forbidden_writes_cannot_be_turned_on_but_can_be_turned_off(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionWrites

        cid = _connection(pg_conn)
        _tool(pg_conn, cid, WRITE_MCP, [_action("create_issue", False)])
        _forbid(pg_conn)
        calls = []
        with _db(pg_conn), patch.object(mcp, "_discover", side_effect=_fake_discovery(calls)):
            on = _call(app, ConnectionWrites, "put", "/x", body={"allow": True}, args=[cid])
            off = _call(app, ConnectionWrites, "put", "/x", body={"allow": False}, args=[cid])
        assert on.status_code == 403 and on.get_json()["code"] == "writes_forbidden"
        assert off.status_code == 200
        assert _stored(pg_conn, cid)[0]["server_url"] == READONLY_MCP

    def test_owner_only_github_only_and_needs_the_tool(self, app, pg_conn):
        from docsgpt.api.connector.connections import ConnectionWrites

        cid = _connection(pg_conn)
        with _db(pg_conn):
            bob = _call(app, ConnectionWrites, "put", "/x", user="bob", body={"allow": True}, args=[cid])
            no_tool = _call(app, ConnectionWrites, "put", "/x", body={"allow": True}, args=[cid])
            bad = _call(app, ConnectionWrites, "put", "/x", body={"allow": "yes"}, args=[cid])
        assert bob.status_code == 404
        assert no_tool.status_code == 409 and no_tool.get_json()["code"] == "no_tools"
        assert bad.status_code == 400
        telegram = str(pg_conn.execute(text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, account_label) "
            "VALUES ('alice', 'telegram', 'telegram', 'api_key', 'connected', 'bot') RETURNING id"
        )).scalar())
        with _db(pg_conn):
            other = _call(app, ConnectionWrites, "put", "/x", body={"allow": True}, args=[telegram])
        assert other.status_code == 400

    def test_refresh_after_an_admin_forbids_writes_goes_read_only(self, pg_conn):
        cid = _connection(pg_conn)
        _tool(pg_conn, cid, WRITE_MCP, [_action("create_issue", False)])
        _forbid(pg_conn)
        calls = []
        with _db(pg_conn), patch.object(mcp, "_discover", side_effect=_fake_discovery(calls)):
            result = mcp.refresh_mcp_tools("alice", _row(pg_conn, cid))
        assert calls == [READONLY_MCP]
        assert result["removed"] == ["create_issue"]
        assert _stored(pg_conn, cid)[0]["server_url"] == READONLY_MCP


class TestAdmin:
    def test_admin_can_forbid_github_writes(self, app, pg_conn):
        from docsgpt.api.admin.connectors import AdminConnectorsResource

        with _db(pg_conn):
            before = _call(app, AdminConnectorsResource, "get", "/x", roles=["admin"]).get_json()
            resp = _call(app, AdminConnectorsResource, "put", "/x", roles=["admin"],
                         body={"policies": {"github": {"allow_writes": False}}})
        rows = {c["key"]: c for c in before["connectors"]}
        assert rows["github"]["allow_writes"] is True
        assert rows["telegram"]["allow_writes"] is None
        assert resp.status_code == 200
        assert {c["key"]: c for c in resp.get_json()["connectors"]}["github"]["allow_writes"] is False
        assert service.writes_allowed(service.load_policies(pg_conn), "github") is False

    def test_rejects_writes_policy_where_it_means_nothing(self, app, pg_conn):
        from docsgpt.api.admin.connectors import AdminConnectorsResource

        with _db(pg_conn):
            other = _call(app, AdminConnectorsResource, "put", "/x", roles=["admin"],
                          body={"policies": {"telegram": {"allow_writes": False}}})
            not_bool = _call(app, AdminConnectorsResource, "put", "/x", roles=["admin"],
                             body={"policies": {"github": {"allow_writes": "no"}}})
        assert other.status_code == 400
        assert not_bool.status_code == 400


def _tool_data(cid, server_url=WRITE_MCP):
    return {
        "id": "tool-gh", "user_id": "alice", "name": "mcp_tool", "connection_id": cid,
        "config": {"server_url": server_url, "auth_type": "bearer"}, "credential_mode": "owner",
        "actions": [
            {"name": "create_issue", "access": "write", "active": True, "require_approval": False},
            {"name": "get_issue", "access": "read", "active": True},
        ],
    }


class TestRuntime:
    def _loaded_url(self, pg_conn, tool):
        from docsgpt.agents.tool_executor import ToolExecutor

        with _db(pg_conn), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            ToolExecutor(user="alice")._get_or_load_tool(tool, "t1", "create_issue")
        return manager.return_value.load_tool.call_args.kwargs["tool_config"]["server_url"]

    def test_write_endpoint_is_used_while_allowed(self, pg_conn):
        assert self._loaded_url(pg_conn, _tool_data(_connection(pg_conn))) == WRITE_MCP

    def test_forbidden_writes_fall_back_to_the_read_only_endpoint(self, pg_conn):
        cid = _connection(pg_conn)
        _forbid(pg_conn)
        assert self._loaded_url(pg_conn, _tool_data(cid)) == READONLY_MCP

    def test_any_other_path_on_githubs_host_is_read_only(self, pg_conn):
        cid = _connection(pg_conn)
        assert self._loaded_url(pg_conn, _tool_data(cid, "https://api.githubcopilot.com/mcp/x/all")) == READONLY_MCP

    def _pause(self, pg_conn, action_name):
        from docsgpt.agents.tool_executor import ToolExecutor

        cid = _connection(pg_conn)
        _forbid(pg_conn)
        with _db(pg_conn), patch("docsgpt.agents.tool_executor.ToolActionParser") as parser:
            parser.return_value.parse_args.return_value = ("t1", action_name, {})
            return ToolExecutor(user="alice").check_pause(
                {"t1": _tool_data(cid)}, SimpleNamespace(id="c1", name=action_name, thought_signature=None),
                "OpenAILLM",
            )

    def test_forbidden_write_is_denied_with_a_reason(self, pg_conn):
        pause = self._pause(pg_conn, "create_issue")
        assert pause["pause_type"] == "headless_denied"
        assert "admin" in pause["deny_reason"]

    def test_reads_still_run_when_writes_are_forbidden(self, pg_conn):
        assert self._pause(pg_conn, "get_issue") is None
