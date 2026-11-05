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
        {"name": "read_checkpoint", "active": True, "access": "read", "ui": {"visibility": ["app"]},
         "parameters": {"type": "object", "properties": {
             "id": {"type": "string", "filled_by_llm": True, "value": ""},
             "board": {"type": "string", "filled_by_llm": False, "value": "pinned-board"},
         }}},
        {"name": "save_checkpoint", "active": True, "access": "write", "require_approval": True,
         "ui": {"visibility": ["app"]}},
        {"name": "read_me", "active": True, "access": "read", "ui": {"visibility": ["model"]}},
        {"name": "export_to_excalidraw", "active": False, "access": "write", "ui": {"visibility": ["app"]}},
    ]
    for action in actions:
        action.update(action_overrides.get(action["name"], {}))
    return {"id": ROW_ID, "name": "mcp_tool", "user_id": user, "status": True, "config": {}, "actions": actions}


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


def _post_raw(app, resource, body, user="alice"):
    """``_post`` with the body sent as given: no body, or text that is not a JSON object."""
    with app.test_request_context("/", method="POST", data=body, content_type="application/json"):
        from flask import request

        request.decoded_token = {"sub": user} if user else None
        return resource().post()


def _executor(resolved=None, connection_pins=None):
    """The executor the routes load a row with: no connection and no connection pins unless given."""
    executor = MagicMock()
    executor._resolve_connection.return_value = resolved
    executor._connection_parameters.return_value = connection_pins or {}
    executor.redact_app_result.side_effect = lambda result: result
    return executor


def _found(row, executor=None):
    return patch.object(routes, "_app_tool", return_value=(executor or _executor(), row))


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

    def test_a_body_that_is_not_an_object(self, app, tool):
        with _found(_row()):
            response = _post(app, routes.McpAppResource, [ROW_ID, VIEW])
        assert response.status_code == 400
        tool.read_ui_resource.assert_not_called()

    @pytest.mark.parametrize("body", [None, "null", "{nope"], ids=["missing", "null", "malformed"])
    def test_a_missing_or_malformed_body(self, app, tool, body):
        with _found(_row()):
            response = _post_raw(app, routes.McpAppResource, body)
        assert response.status_code == 400
        tool.read_ui_resource.assert_not_called()


@pytest.mark.unit
class TestCall:
    def test_runs_an_app_visible_read(self, app, tool):
        with _found(_row()):
            response = _post(
                app, routes.McpAppCall, {"tool_id": ROW_ID, "name": "read_checkpoint", "arguments": {"id": "c"}}
            )
        assert response.status_code == 200
        tool.call_app_tool.assert_called_once_with("read_checkpoint", {"id": "c", "board": "pinned-board"})

    def test_a_fixed_value_wins_over_the_views(self, app, tool):
        with _found(_row()):
            _post(
                app, routes.McpAppCall,
                {"tool_id": ROW_ID, "name": "read_checkpoint", "arguments": {"id": "c", "board": "other"}},
            )
        tool.call_app_tool.assert_called_once_with("read_checkpoint", {"id": "c", "board": "pinned-board"})

    def test_a_value_the_connection_fixes_wins_too(self, app, tool):
        with _found(_row(), _executor(connection_pins={"id": "from-connection"})):
            _post(app, routes.McpAppCall, {"tool_id": ROW_ID, "name": "read_checkpoint", "arguments": {"id": "c"}})
        tool.call_app_tool.assert_called_once_with(
            "read_checkpoint", {"id": "from-connection", "board": "pinned-board"}
        )

    def test_a_hidden_parameter_without_a_value_stays_out(self, app, tool):
        # As for the model: the owner hid it, so the view does not get to set it either.
        hidden = {"read_checkpoint": {"parameters": {"type": "object", "properties": {
            "id": {"type": "string", "filled_by_llm": True, "value": ""},
            "board": {"type": "string", "filled_by_llm": False, "value": ""},
        }}}}
        with _found(_row(**hidden)):
            _post(
                app, routes.McpAppCall,
                {"tool_id": ROW_ID, "name": "read_checkpoint", "arguments": {"id": "c", "board": "mine"}},
            )
        tool.call_app_tool.assert_called_once_with("read_checkpoint", {"id": "c"})

    def test_a_server_that_ships_no_view_takes_no_view_calls(self, app, tool):
        # Its app-visible tools exist, but no view of its can be the one calling.
        no_view = _row(create_view={"ui": {}})
        with _found(no_view):
            response = _post(app, routes.McpAppCall, {"tool_id": ROW_ID, "name": "read_checkpoint"})
        assert response.status_code == 403
        tool.call_app_tool.assert_not_called()

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

    def test_no_writes_through_the_owners_connection(self, app, tool):
        row = _row(user="owner", save_checkpoint={"require_approval": False})
        with _found(row, _executor(resolved=MagicMock(delegated=True))):
            response = _post(app, routes.McpAppCall, {"tool_id": ROW_ID, "name": "save_checkpoint"})
        assert response.status_code == 403
        tool.call_app_tool.assert_not_called()

    def test_a_shared_tool_writes_on_the_members_own_connection(self, app, tool):
        # Member mode: the shared row runs on the caller's own account.
        row = _row(user="owner", save_checkpoint={"require_approval": False})
        with _found(row, _executor(resolved=MagicMock(delegated=False))):
            response = _post(app, routes.McpAppCall, {"tool_id": ROW_ID, "name": "save_checkpoint"})
        assert response.status_code == 200

    def test_arguments_must_be_an_object(self, app, tool):
        with _found(_row()):
            response = _post(app, routes.McpAppCall, {"tool_id": ROW_ID, "name": "read_checkpoint", "arguments": [1]})
        assert response.status_code == 400

    def test_the_result_is_cleaned_as_an_agents_calls_is(self, app, tool, monkeypatch):
        # Control characters out, and an exposed secret the server echoes back as its reference.
        from docsgpt.agents.tool_executor import ToolExecutor

        executor = ToolExecutor(user="alice")
        monkeypatch.setattr(executor, "exposed_secrets", lambda: {"raw-secret": "{{link_secret:ABCDEF}}"})
        tool.call_app_tool.return_value = {
            "content": [{"type": "text", "text": "key=raw-secret\x07"}],
            "structuredContent": {"key": "raw-secret"},
            "isError": False,
        }
        with _found(_row(), executor):
            response = _post(app, routes.McpAppCall, {"tool_id": ROW_ID, "name": "read_checkpoint"})
        assert response.status_code == 200
        assert response.get_json()["result"] == {
            "content": [{"type": "text", "text": "key={{link_secret:ABCDEF}}"}],
            "structuredContent": {"key": "{{link_secret:ABCDEF}}"},
            "isError": False,
        }

    def test_an_unusable_connection_answers_a_fixed_message(self, app, tool):
        # The exception's own text may quote the provider; the caller gets the connector routes' answer.
        from docsgpt.connectors.service import ConnectionUnavailable

        tool.call_app_tool.side_effect = ConnectionUnavailable("upstream said: token xyz revoked")
        with _found(_row()):
            response = _post(app, routes.McpAppCall, {"tool_id": ROW_ID, "name": "read_checkpoint"})
        assert response.status_code == 409
        assert response.get_json() == {"success": False, "error": "Reconnect to continue", "code": "reconnect"}

    def test_a_body_that_is_not_an_object(self, app, tool):
        with _found(_row()):
            response = _post(app, routes.McpAppCall, [ROW_ID, "read_checkpoint"])
        assert response.status_code == 400
        tool.call_app_tool.assert_not_called()

    @pytest.mark.parametrize("body", [None, "null", "{nope"], ids=["missing", "null", "malformed"])
    def test_a_missing_or_malformed_body(self, app, tool, body):
        with _found(_row()):
            response = _post_raw(app, routes.McpAppCall, body)
        assert response.status_code == 400
        tool.call_app_tool.assert_not_called()


@pytest.mark.unit
class TestAppTool:
    def test_only_mcp_tool_rows(self, monkeypatch):
        monkeypatch.setattr(routes, "db_readonly", MagicMock())
        monkeypatch.setattr(routes, "resolve_tool_by_id", lambda *a, **k: {"id": ROW_ID, "name": "api_tool"})
        assert routes._app_tool("alice", ROW_ID) is None

    @pytest.mark.parametrize("status", [False, None])
    def test_a_row_switched_off_is_not_usable(self, monkeypatch, status):
        # An old view must not keep driving a tool the user turned off.
        monkeypatch.setattr(routes, "db_readonly", MagicMock())
        monkeypatch.setattr(routes, "resolve_tool_by_id", lambda *a, **k: {**_row(), "status": status})
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


RESULT = {"content": [], "structuredContent": {"elements": []}, "isError": False}


@pytest.fixture
def saved(pg_conn, monkeypatch):
    """A message of alice's whose call ``c1`` drew a view, with its result journaled."""
    from contextlib import contextmanager

    from docsgpt.storage.db.repositories.conversations import ConversationsRepository
    from docsgpt.storage.db.repositories.tool_call_attempts import ToolCallAttemptsRepository

    @contextmanager
    def _conn():
        yield pg_conn

    monkeypatch.setattr(routes, "db_readonly", _conn)
    conversations = ConversationsRepository(pg_conn)
    conversation_id = str(conversations.create("alice", "c")["id"])
    message_id = str(conversations.append_message(conversation_id, {"prompt": "p", "response": "r"})["id"])
    journal = ToolCallAttemptsRepository(pg_conn)
    for call_id, app_result in (("c1", RESULT), ("c2", None)):
        key = f"{message_id}:{call_id}"
        journal.record_proposed(key, "mcp_tool", "create_view", {}, message_id=message_id, user_id="alice")
        journal.mark_executed(key, "ok", message_id=message_id, user_id="alice", app_result=app_result)
    return {"conversation_id": conversation_id, "message_id": message_id, "conn": pg_conn}


@pytest.mark.unit
class TestResult:
    def test_the_owner_reads_it_back(self, app, saved):
        response = _post(app, routes.McpAppResult, {"message_id": saved["message_id"], "call_id": "c1"})
        assert response.status_code == 200
        assert response.json == {"success": True, "result": RESULT}

    def test_a_user_the_conversation_is_shared_with_reads_it_too(self, app, saved):
        from docsgpt.storage.db.repositories.conversations import ConversationsRepository

        ConversationsRepository(saved["conn"]).add_shared_user(saved["conversation_id"], "bob")
        response = _post(app, routes.McpAppResult, {"message_id": saved["message_id"], "call_id": "c1"}, user="bob")
        assert response.status_code == 200

    def test_another_user_gets_nothing(self, app, saved):
        response = _post(app, routes.McpAppResult, {"message_id": saved["message_id"], "call_id": "c1"}, user="eve")
        assert response.status_code == 404

    def test_a_deleted_message(self, app, saved):
        from sqlalchemy import text

        saved["conn"].execute(
            text("DELETE FROM conversation_messages WHERE id = CAST(:id AS uuid)"), {"id": saved["message_id"]}
        )
        response = _post(app, routes.McpAppResult, {"message_id": saved["message_id"], "call_id": "c1"})
        assert response.status_code == 404

    @pytest.mark.parametrize("call_id", ["c2", "c9"])
    def test_a_call_with_no_saved_result(self, app, saved, call_id):
        response = _post(app, routes.McpAppResult, {"message_id": saved["message_id"], "call_id": call_id})
        assert response.status_code == 404

    def test_a_malformed_message_id(self, app, saved):
        assert _post(app, routes.McpAppResult, {"message_id": "nope", "call_id": "c1"}).status_code == 404

    def test_needs_a_session(self, app):
        assert _post(app, routes.McpAppResult, {"message_id": "m", "call_id": "c1"}, user=None).status_code == 401

    def test_off(self, app, monkeypatch):
        monkeypatch.setattr(routes.mcp_apps, "enabled", lambda: False)
        assert _post(app, routes.McpAppResult, {"message_id": "m", "call_id": "c1"}).status_code == 404
