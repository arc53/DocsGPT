"""The MCP Apps routes: the sandbox page, a view's HTML and the tool calls a view makes."""

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from docsgpt.api.user.mcp_apps import routes

ROW_ID = "00000000-0000-0000-0000-0000000000aa"
VIEW = "ui://excalidraw/mcp-app.html"


def _row(user="alice", **action_overrides):
    actions = [
        {"name": "create_view", "active": True, "access": "read", "ui": {"resourceUri": VIEW}},
        {"name": "read_checkpoint", "active": True, "access": "read", "ui": {"visibility": ["app"]}},
        {"name": "save_checkpoint", "active": True, "access": "write", "require_approval": True,
         "ui": {"visibility": ["app"]}},
        {"name": "read_me", "active": True, "access": "read", "ui": {"visibility": ["model"]}},
        {"name": "export_to_excalidraw", "active": False, "access": "write", "ui": {"visibility": ["app"]}},
    ]
    for action in actions:
        action.update(action_overrides.get(action["name"], {}))
    return {"id": ROW_ID, "name": "mcp_tool", "user_id": user, "config": {}, "actions": actions}


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture(autouse=True)
def apps_on(monkeypatch):
    monkeypatch.setattr(routes.mcp_apps, "enabled", lambda: True)
    monkeypatch.setattr(routes.mcp_apps, "host_origins", lambda: ["http://localhost:5173"])
    monkeypatch.setattr(routes.mcp_apps, "sandbox_url", lambda: "http://127.0.0.1:7091/api/mcp_apps/sandbox")


@pytest.fixture
def tool():
    """The loaded MCP tool, with the row the user may use."""
    loaded = MagicMock()
    loaded.read_ui_resource.return_value = {"html": "<html>", "csp": {"connectDomains": ["https://esm.sh"]}}
    loaded.call_app_tool.return_value = {"content": [], "isError": False}
    with patch.object(routes, "_load", return_value=loaded):
        yield loaded


def _post(app, resource, body, user="alice"):
    with app.test_request_context("/", method="POST", json=body):
        from flask import request

        request.decoded_token = {"sub": user} if user else None
        return resource().post()


def _found(row):
    return patch.object(routes, "_app_tool", return_value=(MagicMock(), row))


@pytest.mark.unit
class TestSandboxPage:
    def test_serves_the_page_with_the_views_csp(self, app):
        with app.test_request_context(
            "/api/mcp_apps/sandbox", base_url="http://127.0.0.1:7091",
            query_string={"csp": '{"connectDomains": ["https://esm.sh"]}'},
        ):
            response = routes.McpAppSandbox().get()
        assert response.status_code == 200
        assert "connect-src https://esm.sh" in response.headers["Content-Security-Policy"]
        assert "frame-ancestors http://localhost:5173" in response.headers["Content-Security-Policy"]
        assert b"sandbox-proxy-ready" in response.get_data()

    def test_never_on_an_app_origin(self, app):
        with app.test_request_context("/api/mcp_apps/sandbox", base_url="http://localhost:5173"):
            assert routes.McpAppSandbox().get().status_code == 404

    def test_off(self, app, monkeypatch):
        monkeypatch.setattr(routes.mcp_apps, "enabled", lambda: False)
        with app.test_request_context("/api/mcp_apps/sandbox", base_url="http://127.0.0.1:7091"):
            assert routes.McpAppSandbox().get().status_code == 404

    def test_bad_csp_json_gets_the_restrictive_default(self, app):
        with app.test_request_context(
            "/api/mcp_apps/sandbox", base_url="http://127.0.0.1:7091", query_string={"csp": "{nope"}
        ):
            response = routes.McpAppSandbox().get()
        assert "connect-src 'none'" in response.headers["Content-Security-Policy"]


@pytest.mark.unit
class TestResource:
    def test_reads_the_view(self, app, tool):
        with _found(_row()):
            response = _post(app, routes.McpAppResource, {"tool_id": ROW_ID, "uri": VIEW})
        assert response.status_code == 200
        body = response.get_json()
        assert body["html"] == "<html>"
        assert body["sandbox_url"] == "http://127.0.0.1:7091/api/mcp_apps/sandbox"
        tool.read_ui_resource.assert_called_once_with(VIEW)

    def test_a_uri_no_action_declares_is_refused(self, app, tool):
        with _found(_row()):
            response = _post(app, routes.McpAppResource, {"tool_id": ROW_ID, "uri": "ui://other/x.html"})
        assert response.status_code == 404
        tool.read_ui_resource.assert_not_called()

    def test_a_tool_the_user_cannot_use(self, app, tool):
        with patch.object(routes, "_app_tool", return_value=None):
            response = _post(app, routes.McpAppResource, {"tool_id": ROW_ID, "uri": VIEW})
        assert response.status_code == 404

    def test_needs_a_session(self, app):
        assert _post(app, routes.McpAppResource, {"tool_id": ROW_ID, "uri": VIEW}, user=None).status_code == 401


@pytest.mark.unit
class TestCall:
    def test_runs_an_app_visible_read(self, app, tool):
        with _found(_row()):
            response = _post(
                app, routes.McpAppCall, {"tool_id": ROW_ID, "name": "read_checkpoint", "arguments": {"id": "c"}}
            )
        assert response.status_code == 200
        tool.call_app_tool.assert_called_once_with("read_checkpoint", {"id": "c"})

    def test_a_model_only_tool_is_refused(self, app, tool):
        with _found(_row()):
            response = _post(app, routes.McpAppCall, {"tool_id": ROW_ID, "name": "read_me"})
        assert response.status_code == 403
        tool.call_app_tool.assert_not_called()

    def test_a_write_needing_approval_asks_first(self, app, tool):
        with _found(_row()):
            response = _post(app, routes.McpAppCall, {"tool_id": ROW_ID, "name": "save_checkpoint"})
        assert response.status_code == 409
        assert response.get_json()["needs_approval"] is True
        tool.call_app_tool.assert_not_called()

    def test_an_approved_write_runs(self, app, tool):
        with _found(_row()):
            response = _post(app, routes.McpAppCall, {"tool_id": ROW_ID, "name": "save_checkpoint", "approved": True})
        assert response.status_code == 200

    def test_an_always_allowed_write_runs_without_asking(self, app, tool):
        with _found(_row(save_checkpoint={"require_approval": False})):
            response = _post(app, routes.McpAppCall, {"tool_id": ROW_ID, "name": "save_checkpoint"})
        assert response.status_code == 200

    def test_the_rows_approval_switch_gates_reads_too(self, app, tool):
        row = _row()
        row["config"] = {"require_approval": True}
        with _found(row):
            response = _post(app, routes.McpAppCall, {"tool_id": ROW_ID, "name": "read_checkpoint"})
        assert response.status_code == 409

    def test_a_tool_turned_off(self, app, tool):
        with _found(_row()):
            response = _post(
                app, routes.McpAppCall, {"tool_id": ROW_ID, "name": "export_to_excalidraw", "approved": True}
            )
        assert response.status_code == 403
        tool.call_app_tool.assert_not_called()

    def test_no_writes_on_a_shared_tools_account(self, app, tool):
        with _found(_row(user="owner", save_checkpoint={"require_approval": False})):
            response = _post(app, routes.McpAppCall, {"tool_id": ROW_ID, "name": "save_checkpoint"})
        assert response.status_code == 403

    def test_arguments_must_be_an_object(self, app, tool):
        with _found(_row()):
            response = _post(app, routes.McpAppCall, {"tool_id": ROW_ID, "name": "read_checkpoint", "arguments": [1]})
        assert response.status_code == 400


@pytest.mark.unit
class TestAppTool:
    def test_only_mcp_tool_rows(self, monkeypatch):
        monkeypatch.setattr(routes, "db_readonly", MagicMock())
        monkeypatch.setattr(routes, "resolve_tool_by_id", lambda *a, **k: {"id": ROW_ID, "name": "api_tool"})
        assert routes._app_tool("alice", ROW_ID) is None

    def test_resolves_as_the_user(self, monkeypatch):
        seen = {}

        def resolve(tool_id, user, **kwargs):
            seen.update(tool_id=tool_id, user=user)
            return _row()

        monkeypatch.setattr(routes, "db_readonly", MagicMock())
        monkeypatch.setattr(routes, "resolve_tool_by_id", resolve)
        executor, row = routes._app_tool("alice", ROW_ID)
        assert seen == {"tool_id": ROW_ID, "user": "alice"}
        assert executor.user == "alice"
        assert row["id"] == ROW_ID
