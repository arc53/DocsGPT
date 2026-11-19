"""A preset that needs URL parameters, such as Supabase's project ref."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from sqlalchemy import text

import docsgpt.api.user  # noqa: F401  (loads mcp_tool without the circular import)
from docsgpt.api.user.tools.mcp import MCPServerSave
from docsgpt.connectors import catalog, service
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

_REF = "abcdefghijklmnopqrst"
_URL = "https://mcp.example.com/mcp"

_SCOPED_PRESET = (
    "key: mcp:example\n"
    "name: Example\n"
    "description: Example records.\n"
    "mcp_url: https://mcp.example.com/mcp\n"
    "url_parameters:\n"
    "  - key: project_ref\n"
    "    label: Project ref\n"
    "    pattern: '[a-z]{20}'\n"
    "    hint: Found in the project's settings.\n"
)


@pytest.fixture(autouse=True)
def _fresh_registry():
    catalog.reset_registry_for_tests()
    yield
    catalog.reset_registry_for_tests()


@pytest.fixture
def scoped(tmp_path, monkeypatch):
    """The catalog with one preset, ``mcp:example``, that needs a project ref."""
    (tmp_path / "example.yaml").write_text(_SCOPED_PRESET)
    monkeypatch.setattr(catalog, "_PRESETS_DIR", tmp_path)
    return catalog.get_definition("mcp:example")


class TestCatalog:
    def test_a_preset_declares_the_url_parameters_it_needs(self, scoped):
        (field,) = scoped.url_parameters
        assert (field.key, field.label, field.pattern) == ("project_ref", "Project ref", "[a-z]{20}")
        # Asked for in the open, and never optional.
        assert field.secret is False
        assert field.required is True
        assert field.hint == "Found in the project's settings."

    def test_the_frontend_gets_the_fields_and_their_patterns(self, scoped):
        (field,) = scoped.to_dict()["url_parameters"]
        assert field["key"] == "project_ref"
        assert field["pattern"] == "[a-z]{20}"

    def test_presets_need_none_unless_they_say_so(self):
        assert catalog.get_definition("mcp:notion").url_parameters == ()
        assert catalog.get_definition("mcp:notion").to_dict()["url_parameters"] == []

    @pytest.mark.parametrize(
        "parameter",
        [
            "{key: project_ref, label: Project ref}",
            "{key: project_ref, label: Project ref, pattern: '[a-z'}",
            "{label: Project ref, pattern: '[a-z]+'}",
        ],
        ids=["no-pattern", "bad-pattern", "no-key"],
    )
    def test_a_parameter_the_server_cannot_check_is_refused(self, tmp_path, monkeypatch, parameter):
        (tmp_path / "example.yaml").write_text(
            "key: mcp:example\nname: Example\ndescription: Example records.\n"
            f"mcp_url: https://mcp.example.com/mcp\nurl_parameters: [{parameter}]\n"
        )
        monkeypatch.setattr(catalog, "_PRESETS_DIR", tmp_path)

        with pytest.raises(ValueError, match="example.yaml"):
            catalog.get_definition("mcp:example")


class TestCheckUrlParameters:
    @pytest.mark.parametrize(
        "url",
        [
            f"https://mcp.example.com/mcp?project_ref={_REF}",
            # Other parameters are the user's business (Supabase's read_only).
            f"https://mcp.example.com/mcp?project_ref={_REF}&read_only=true",
            # Not this preset's server.
            "https://mcp.other.com/mcp",
        ],
    )
    def test_a_url_with_what_its_preset_needs_passes(self, scoped, url):
        catalog.check_url_parameters(url)

    def test_a_preset_without_parameters_takes_its_plain_url(self):
        catalog.check_url_parameters("https://mcp.notion.com/mcp")

    @pytest.mark.parametrize(
        "url",
        [
            "https://mcp.example.com/mcp",
            "https://mcp.example.com/mcp?project_ref=",
            # A custom server at the preset's address is that preset.
            "https://mcp.example.com/other?read_only=true",
        ],
    )
    def test_a_missing_parameter_is_refused(self, scoped, url):
        with pytest.raises(catalog.UrlParametersRequired, match="Example needs a Project ref"):
            catalog.check_url_parameters(url)

    @pytest.mark.parametrize(
        "value",
        ["ABCDEFGHIJKLMNOPQRST", "abc", _REF + "u", f"{_REF}&project_ref=zyxwvutsrqponmlkjihg", "x/../" + _REF],
        ids=["uppercase", "short", "long", "twice", "path"],
    )
    def test_a_value_that_does_not_match_is_refused(self, scoped, value):
        from urllib.parse import quote

        query = f"project_ref={value}" if "&" in value else f"project_ref={quote(value)}"
        with pytest.raises(catalog.UrlParametersRequired, match="Project ref is not valid"):
            catalog.check_url_parameters(f"https://mcp.example.com/mcp?{query}")


class TestUrlParameterValues:
    def test_the_values_are_read_from_a_checked_url(self, scoped):
        url = f"https://mcp.example.com/mcp?read_only=true&project_ref={_REF}"
        assert catalog.url_parameter_values(url) == {"project_ref": _REF}

    def test_a_url_at_another_server_has_none(self, scoped):
        assert catalog.url_parameter_values(f"https://mcp.other.com/mcp?project_ref={_REF}") == {}

    def test_the_preset_url_is_rebuilt_from_stored_values(self, scoped):
        assert catalog.preset_url(scoped, {"project_ref": _REF}) == f"https://mcp.example.com/mcp?project_ref={_REF}"

    @pytest.mark.parametrize("values", [{}, {"project_ref": "nope"}, None], ids=["missing", "invalid", "none"])
    def test_no_url_is_built_without_valid_values(self, scoped, values):
        assert catalog.preset_url(scoped, values) is None

    def test_a_preset_without_parameters_keeps_its_url(self):
        notion = catalog.get_definition("mcp:notion")
        assert catalog.preset_url(notion, None) == notion.mcp_url


# ---------------------------------------------------------------------------
# The connection keeps the values, so a rebuilt tool gets them back
# ---------------------------------------------------------------------------

_ACTIONS = [
    {"name": "list_tables", "description": "List tables", "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "properties": {}}},
]


def _connection(pg_conn, session_data: Optional[dict] = None) -> dict:
    """A sign-in to ``mcp:example``'s server, as the MCP OAuth flow stores it."""
    return dict(pg_conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, server_url, "
            "session_data) VALUES ('alice', 'mcp:https://mcp.example.com', 'mcp:example', 'mcp_oauth', "
            "'connected', 'https://mcp.example.com', CAST(:s AS jsonb)) RETURNING *"
        ),
        {"s": json.dumps(session_data or {})},
    ).one()._mapping)


def _row(pg_conn, connection: dict) -> dict:
    return service.ConnectorSessionsRepository(pg_conn).get(str(connection["id"]))


class TestConnection:
    def test_a_saved_url_leaves_its_values_on_the_connection(self, scoped, pg_conn):
        connection = _connection(pg_conn, {"driver_state": 1})

        service.remember_url_parameters(pg_conn, str(connection["id"]), f"{_URL}?project_ref={_REF}")

        row = _row(pg_conn, connection)
        assert row["session_data"] == {"driver_state": 1, "url_parameters": {"project_ref": _REF}}
        assert service.serialize_connection(row)["url_parameters"] == {"project_ref": _REF}

    def test_a_url_without_them_changes_nothing(self, pg_conn):
        connection = _connection(pg_conn, {"url_parameters": {"project_ref": _REF}})

        service.remember_url_parameters(pg_conn, str(connection["id"]), "https://mcp.notion.com/mcp")

        assert _row(pg_conn, connection)["session_data"] == {"url_parameters": {"project_ref": _REF}}

    def test_signing_in_again_keeps_them(self, scoped, pg_conn):
        """A reconnect rewrites the secrets; the project stays."""
        connection = _connection(pg_conn, {"url_parameters": {"project_ref": _REF}})

        service.write_secrets(pg_conn, connection, {"tokens": {"access_token": "new"}})

        assert _row(pg_conn, connection)["session_data"]["url_parameters"] == {"project_ref": _REF}

    def test_a_connection_without_them_shows_none(self, pg_conn):
        assert service.serialize_connection(_row(pg_conn, _connection(pg_conn)))["url_parameters"] == {}


class TestRebuild:
    def test_a_deleted_tool_comes_back_scoped_to_the_stored_project(self, scoped, pg_conn):
        connection = _connection(pg_conn, {"url_parameters": {"project_ref": _REF}})

        assert service.needs_mcp_discovery(pg_conn, connection) is True
        config = service.connection_mcp_config(scoped, connection=connection)
        [tool] = service.ensure_connection_tools(pg_conn, "alice", connection, mcp_actions=_ACTIONS)

        assert config["server_url"] == f"{_URL}?project_ref={_REF}"
        assert tool["config"]["server_url"] == f"{_URL}?project_ref={_REF}"

    def test_no_tool_is_built_on_the_plain_url(self, scoped, pg_conn):
        connection = _connection(pg_conn)

        assert service.connection_mcp_config(scoped, connection=connection) is None
        assert service.needs_mcp_discovery(pg_conn, connection) is False
        assert service.ensure_connection_tools(pg_conn, "alice", connection, mcp_actions=_ACTIONS) == []

    def test_presets_without_parameters_rebuild_as_before(self):
        notion = catalog.get_definition("mcp:notion")
        assert service.connection_mcp_config(notion)["server_url"] == notion.mcp_url


# ---------------------------------------------------------------------------
# Every route that stores an MCP server URL checks it
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture(autouse=True)
def _mcp_servers_allowed():
    """The admin switch is covered elsewhere; these tests are about the URL."""
    with patch("docsgpt.api.user.tools.mcp._mcp_policy_error", return_value=None):
        yield


@pytest.fixture
def public_host():
    """``mcp.example.com`` resolves to a public address, so the SSRF check lets it through."""
    with patch("docsgpt.core.url_validation.resolve_hostname", return_value="104.18.0.1"):
        yield


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch.multiple("docsgpt.api.user.tools.mcp", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.service", db_session=_yield, db_readonly=_yield):
        yield


def _post(app, resource, path: str, body: dict, user: str = "alice"):
    with app.test_request_context(path, method="POST", json=body):
        from flask import request

        request.decoded_token = {"sub": user}
        return resource().post()


@pytest.mark.usefixtures("public_host")
class TestMcpRoutes:
    @pytest.mark.parametrize("route", ["test", "save"])
    def test_a_url_without_the_project_is_refused(self, scoped, app, route):
        from docsgpt.api.user.tools.mcp import MCPServerSave, TestMCPServerConfig

        resource = TestMCPServerConfig if route == "test" else MCPServerSave
        with patch("docsgpt.api.user.tools.mcp.MCPTool") as tool:
            response = _post(app, resource, f"/api/mcp_server/{route}", {
                "displayName": "Example",
                "config": {"server_url": _URL, "auth_type": "oauth", "transport_type": "auto"},
            })

        assert response.status_code == 400
        assert response.json == {
            "success": False,
            "error": "Example needs a Project ref",
            "message": "Example needs a Project ref",
            "code": "url_parameters",
        }
        tool.assert_not_called()

    def test_a_signed_in_save_leaves_the_project_on_the_connection(self, scoped, app, pg_conn):
        connection = _connection(pg_conn)
        discovered = MagicMock()
        discovered.get_actions_metadata.return_value = _ACTIONS
        url = f"{_URL}?project_ref={_REF}"

        with _db(pg_conn), patch("docsgpt.api.user.tools.mcp.MCPTool", return_value=discovered):
            response = _post(app, MCPServerSave, "/api/mcp_server/save", {
                "displayName": "Example",
                "config": {"server_url": url, "auth_type": "oauth", "transport_type": "auto"},
            })

        assert response.status_code == 200, response.json
        assert _row(pg_conn, connection)["session_data"]["url_parameters"] == {"project_ref": _REF}
        tool = UserToolsRepository(pg_conn).get_any(response.json["id"], "alice")
        assert tool["config"]["server_url"] == url
        assert str(tool["connection_id"]) == str(connection["id"])


@pytest.mark.usefixtures("public_host")
class TestToolRoutes:
    def test_creating_a_tool_on_the_plain_url_is_refused(self, scoped, app, pg_conn):
        from docsgpt.api.user.tools.routes import CreateTool

        # The route reads the workspace and the folder the tool lands in first.
        with _tools_db(pg_conn):
            response = _post(app, CreateTool, "/api/create_tool", {
                "name": "mcp_tool", "displayName": "Example", "description": "", "status": True,
                "config": {"server_url": _URL, "auth_type": "none"},
            })

        assert response.status_code == 400
        assert response.json["message"] == "Example needs a Project ref"

    @pytest.mark.parametrize("route", ["update_tool", "update_tool_config"])
    def test_moving_a_saved_tool_to_the_plain_url_is_refused(self, scoped, app, pg_conn, route):
        from docsgpt.api.user.tools.routes import UpdateTool, UpdateToolConfig

        repo = UserToolsRepository(pg_conn)
        saved = repo.create(
            "alice", "mcp_tool", config={"server_url": f"{_URL}?project_ref={_REF}", "auth_type": "none"},
            display_name="Example",
        )

        with _tools_db(pg_conn):
            response = _post(app, UpdateTool if route == "update_tool" else UpdateToolConfig, f"/api/{route}", {
                "id": str(saved["id"]), "config": {"server_url": _URL, "auth_type": "none"},
            })

        assert response.status_code == 400
        assert response.json["message"] == "Example needs a Project ref"
        assert repo.get_any(str(saved["id"]), "alice")["config"]["server_url"] == f"{_URL}?project_ref={_REF}"


@contextmanager
def _tools_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch.multiple("docsgpt.api.user.tools.routes", db_session=_yield, db_readonly=_yield):
        yield


def test_supabase_connects_to_one_project():
    """Its plain URL reaches every project the account can see."""
    supabase = catalog.get_definition("mcp:supabase")

    with pytest.raises(catalog.UrlParametersRequired, match="Supabase needs a Project ID"):
        catalog.check_url_parameters(supabase.mcp_url)
    catalog.check_url_parameters(f"{supabase.mcp_url}?project_ref={_REF}")
    catalog.check_url_parameters(f"{supabase.mcp_url}?project_ref={_REF}&read_only=true")
