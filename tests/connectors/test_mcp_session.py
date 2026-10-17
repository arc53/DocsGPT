"""Calling an MCP server's tools from the server side, signed in with a connection."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import docsgpt.api.user  # noqa: F401  (loads mcp_tool without the circular import)
from docsgpt.agents.tools.mcp_tool import MCPReauthorizationRequired
from docsgpt.connectors import mcp, service

LINEAR = "https://mcp.linear.app/mcp"


def _connection(status="connected", server_url="https://mcp.linear.app") -> dict:
    return {
        "id": "c1", "user_id": "alice", "provider": "mcp:https://mcp.linear.app", "connector_key": "mcp:linear",
        "auth_kind": "mcp_oauth", "status": status, "server_url": server_url, "encrypted_credentials": "v2:x",
    }


def _text(payload) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=payload if isinstance(payload, str) else json.dumps(payload))


def _result(*content, structured=None, error=False) -> SimpleNamespace:
    return SimpleNamespace(content=list(content), structured_content=structured, is_error=error)


class FakeClient:
    """An MCP client that answers from a table of tool results."""

    def __init__(self, results=None, tools=(), enter_error=None):
        self.results = results or {}
        self.tools = [SimpleNamespace(name=name, inputSchema=schema) for name, schema in tools]
        self.enter_error = enter_error
        self.calls: list[tuple[str, dict]] = []
        self.listed = 0
        self.open = False

    async def __aenter__(self):
        if self.enter_error:
            raise self.enter_error
        self.open = True
        return self

    async def __aexit__(self, *exc):
        self.open = False

    async def list_tools(self):
        self.listed += 1
        return self.tools

    async def call_tool(self, name, arguments=None, raise_on_error=True):
        assert self.open
        self.calls.append((name, dict(arguments or {})))
        result = self.results[name]
        if isinstance(result, BaseException):
            raise result
        return result


def _run(client, work, connection=None):
    with patch.object(mcp, "_client_for", return_value=client) as make:
        value = mcp.run_connection_session(connection or _connection(), LINEAR, work)
    return value, make


class TestRunConnectionSession:
    def test_calls_share_one_session_signed_in_with_the_connection(self):
        client = FakeClient({"list_teams": _result(_text({"teams": [{"id": "t1"}]}))})

        async def work(session):
            first = await session.call("list_teams", {"limit": 5})
            second = await session.call("list_teams", {})
            return first, second

        (first, second), make = _run(client, work)
        assert first == {"teams": [{"id": "t1"}]} == second
        assert client.calls == [("list_teams", {"limit": 5}), ("list_teams", {})]
        assert make.call_args.args[0]["id"] == "c1"
        assert make.call_args.args[1] == LINEAR

    def test_structured_content_is_preferred_to_text(self):
        client = FakeClient({"get_issue": _result(_text("prose"), structured={"id": "ENG-1"})})

        async def work(session):
            return await session.call("get_issue", {"id": "ENG-1"})

        assert _run(client, work)[0] == {"id": "ENG-1"}

    def test_text_that_is_not_json_comes_back_as_text(self):
        client = FakeClient({"search": _result(_text("No results"))})

        async def work(session):
            return await session.call("search", {})

        assert _run(client, work)[0] == "No results"

    def test_a_tool_error_names_the_tool(self):
        client = FakeClient({"get_issue": _result(_text("Entity not found"), error=True)})

        async def work(session):
            return await session.call("get_issue", {"id": "X"})

        with pytest.raises(mcp.MCPToolError, match="get_issue: Entity not found"):
            _run(client, work)

    def test_a_rate_limit_is_worth_retrying(self):
        client = FakeClient({"list_issues": _result(_text("Rate limit exceeded, retry later"), error=True)})

        async def work(session):
            return await session.call("list_issues", {})

        with pytest.raises(service.TransientConnectionError):
            _run(client, work)

    def test_input_schemas_are_listed_once(self):
        client = FakeClient(tools=[("list_issues", {"properties": {"team": {}}}), ("get_issue", None)])

        async def work(session):
            return (
                await session.input_schema("list_issues"),
                await session.input_schema("get_issue"),
                await session.input_schema("missing"),
            )

        assert _run(client, work)[0] == ({"properties": {"team": {}}}, {}, None)
        assert client.listed == 1

    @pytest.mark.parametrize("error", [
        MCPReauthorizationRequired("OAuth session expired"),
        RuntimeError("Client failed to connect: OAuth session expired — please re-authorize"),
        ExceptionGroup("task group", [MCPReauthorizationRequired("OAuth session expired")]),
    ])
    def test_a_lost_sign_in_flags_the_connection(self, error):
        client = FakeClient(enter_error=error)

        async def work(session):  # pragma: no cover - never reached
            return None

        with patch.object(service, "mark_reconnect_needed") as flag, pytest.raises(service.ConnectionUnavailable):
            _run(client, work)
        flag.assert_called_once()
        assert flag.call_args.args[0] == "c1"

    def test_a_lost_sign_in_during_a_call_flags_the_connection(self):
        client = FakeClient({"list_issues": MCPReauthorizationRequired("OAuth session expired")})

        async def work(session):
            return await session.call("list_issues", {})

        with patch.object(service, "mark_reconnect_needed") as flag, pytest.raises(service.ConnectionUnavailable):
            _run(client, work)
        flag.assert_called_once()

    def test_a_connection_that_needs_reconnecting_is_not_used(self):
        client = FakeClient()

        async def work(session):  # pragma: no cover - never reached
            return None

        with pytest.raises(service.ConnectionUnavailable):
            _run(client, work, _connection(status="reconnect_needed"))
        assert client.calls == []

    def test_tokens_never_go_to_another_server(self):
        async def work(session):  # pragma: no cover - never reached
            return None

        with pytest.raises(ValueError):
            _run(FakeClient(), work, _connection(server_url="https://mcp.notion.com"))

    def test_network_trouble_is_worth_retrying(self):
        client = FakeClient({"list_issues": ConnectionError("reset")})

        async def work(session):
            return await session.call("list_issues", {})

        with patch.object(service, "mark_reconnect_needed") as flag, pytest.raises(service.TransientConnectionError):
            _run(client, work)
        flag.assert_not_called()

    def test_the_client_signs_in_with_the_connections_stored_tokens(self, monkeypatch):
        from fastmcp import Client

        import docsgpt.agents.tools.mcp_tool as mcp_tool

        monkeypatch.setattr(mcp_tool, "validate_user_base_url", lambda url: None)
        client = mcp._client_for(_connection(), LINEAR, 30)
        assert isinstance(client, Client)
        auth = client.transport.auth
        assert isinstance(auth, mcp_tool.NonInteractiveOAuth)
        assert auth.context.storage.connection_id == "c1"
        assert auth.context.storage.user_id == "alice"

    def test_runs_from_inside_a_running_event_loop(self):
        import asyncio

        client = FakeClient({"list_teams": _result(_text([]))})

        async def work(session):
            return await session.call("list_teams", {})

        async def caller():
            return _run(client, work)[0]

        assert asyncio.run(caller()) == []
