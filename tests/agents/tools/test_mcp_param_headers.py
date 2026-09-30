"""MCP tool calls send the ``Mcp-Param-*`` headers their schema asks for (SEP-2243).

GitHub's MCP server marks ``owner`` and ``repo`` with ``x-mcp-header`` and
refuses a call without ``Mcp-Param-owner`` / ``Mcp-Param-repo``. The tool
never sent them, so every such call failed with a header mismatch.

The stub server here enforces the headers the way GitHub's does.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Annotated

import pytest
from pydantic import Field

OWNER_REPO_SCHEMA = {
    "type": "object",
    "properties": {
        "method": {"type": "string"},
        "owner": {"type": "string", "x-mcp-header": "owner"},
        "repo": {"type": "string", "x-mcp-header": "repo"},
        "issue_number": {"type": "integer"},
    },
    "required": ["method", "owner", "repo", "issue_number"],
}


def _stored_parameters(schema: dict) -> dict:
    """``schema`` the way a saved tool row keeps it (``transform_actions`` adds these keys)."""
    stored = json.loads(json.dumps(schema))
    for prop in stored["properties"].values():
        prop["filled_by_llm"] = True
        prop["value"] = ""
    return stored


@pytest.fixture(autouse=True)
def _isolate_mcp_module(monkeypatch):
    # Imported through its package: mcp_tool alone hits an import cycle.
    import docsgpt.api.user  # noqa: F401
    import docsgpt.agents.tools.mcp_tool as mcp_mod

    monkeypatch.setattr(mcp_mod, "_mcp_clients_cache", {})
    # The stub listens on 127.0.0.1, which the SSRF guard refuses.
    monkeypatch.setattr(mcp_mod, "validate_url", lambda u, **kw: u)


class _Recorder:
    def __init__(self) -> None:
        self.calls: list = []


def _stub_app(recorder: _Recorder):
    """A FastMCP server with GitHub's ``issue_read`` shape, behind a header check."""
    from fastmcp import FastMCP
    from mcp.shared.inbound import decode_header_value

    server = FastMCP("stub")

    @server.tool
    def issue_read(
        method: str,
        owner: Annotated[str, Field(json_schema_extra={"x-mcp-header": "owner"})],
        repo: Annotated[str, Field(json_schema_extra={"x-mcp-header": "repo"})],
        issue_number: int,
    ) -> str:
        return f"{owner}/{repo}#{issue_number} via {method}"

    inner = server.http_app(path="/mcp", stateless_http=True, json_response=True)

    async def app(scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            await inner(scope, receive, send)
            return
        chunks = []
        more = True
        while more:
            message = await receive()
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        body = b"".join(chunks)
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        payload = json.loads(body or b"null")
        if isinstance(payload, dict) and payload.get("method") == "tools/call":
            arguments = payload["params"].get("arguments") or {}
            recorder.calls.append(headers)
            for param in ("owner", "repo"):
                sent = decode_header_value(headers.get(f"mcp-param-{param}"))
                if param in arguments and sent != str(arguments[param]):
                    error = {
                        "jsonrpc": "2.0",
                        "id": payload.get("id"),
                        "error": {
                            "code": -32020,
                            "message": f'header mismatch: missing Mcp-Param-{param} header for parameter "{param}"',
                        },
                    }
                    raw = json.dumps(error).encode()
                    await send({
                        "type": "http.response.start",
                        "status": 400,
                        "headers": [(b"content-type", b"application/json")],
                    })
                    await send({"type": "http.response.body", "body": raw})
                    return
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await inner(scope, replay, send)

    return app, inner


@pytest.fixture(scope="module")
def stub_server():
    import uvicorn

    recorder = _Recorder()
    app, inner = _stub_app(recorder)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)

    async def lifespan_app(scope, receive, send):
        if scope["type"] == "lifespan":
            await inner(scope, receive, send)
        else:
            await app(scope, receive, send)

    config.app = lifespan_app
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "stub MCP server did not start"
    yield f"http://127.0.0.1:{port}/mcp", recorder
    server.should_exit = True
    thread.join(timeout=5)


def _tool(url: str, **config):
    from docsgpt.agents.tools.mcp_tool import MCPTool

    return MCPTool({
        "server_url": url,
        "transport_type": "http",
        "auth_type": "bearer",
        "auth_credentials": {"bearer_token": "tok"},
        "timeout": 20,
        "query_mode": True,
        **config,
    })


def _text(result: dict) -> str:
    return result["content"][0]["text"]


@pytest.mark.unit
class TestParamHeaderMaps:
    def test_reads_the_stored_schema(self):
        from docsgpt.agents.tools.mcp_tool import param_header_maps

        maps = param_header_maps({"issue_read": _stored_parameters(OWNER_REPO_SCHEMA), "plain": {}})
        assert maps == {"issue_read": {("owner",): "owner", ("repo",): "repo"}}

    def test_invalid_annotations_are_ignored(self):
        from docsgpt.agents.tools.mcp_tool import param_header_maps

        schema = {"type": "object", "properties": {"n": {"type": "number", "x-mcp-header": "n"}}}
        assert param_header_maps({"bad": schema}) == {}


@pytest.mark.integration
class TestParamHeadersAgainstAServer:
    def test_call_sends_the_headers_from_the_stored_schema(self, stub_server):
        url, recorder = stub_server
        tool = _tool(
            url,
            headers={"X-Custom": "kept"},
            action_schemas={"issue_read": _stored_parameters(OWNER_REPO_SCHEMA)},
        )
        result = tool.execute_action("issue_read", method="get", owner="arc53", repo="DocsGPT", issue_number=2836)

        assert _text(result) == "arc53/DocsGPT#2836 via get"
        sent = recorder.calls[-1]
        assert sent["mcp-param-owner"] == "arc53"
        assert sent["mcp-param-repo"] == "DocsGPT"
        assert sent["x-custom"] == "kept"
        assert sent["authorization"] == "Bearer tok"

    def test_a_static_header_that_agrees_is_sent_once(self, stub_server):
        url, recorder = stub_server
        tool = _tool(
            url,
            headers={"mcp-param-repo": "DocsGPT"},
            action_schemas={"issue_read": _stored_parameters(OWNER_REPO_SCHEMA)},
        )
        result = tool.execute_action("issue_read", method="get", owner="arc53", repo="DocsGPT", issue_number=3)

        assert _text(result) == "arc53/DocsGPT#3 via get"
        assert recorder.calls[-1]["mcp-param-repo"] == "DocsGPT"

    @pytest.mark.parametrize("stored", [True, False])
    def test_a_static_header_pins_the_value(self, stub_server, stored):
        """A tool limited to one repository by its headers refuses a call for another, stored schema or not."""
        url, recorder = stub_server
        schema = _stored_parameters(OWNER_REPO_SCHEMA)
        if not stored:
            for prop in schema["properties"].values():
                prop.pop("x-mcp-header", None)
        tool = _tool(url, headers={"Mcp-Param-repo": "DocsGPT"}, action_schemas={"issue_read": schema})
        before = len(recorder.calls)

        result = tool.execute_action("issue_read", method="get", owner="arc53", repo="Other", issue_number=1)

        assert result["status"] == "error"
        assert "Mcp-Param-repo" in result["error"] and "'Other'" in result["error"]
        # Nothing with the other value reached the server.
        assert all(call.get("mcp-param-repo") != "Other" for call in recorder.calls[before:])

    def test_non_ascii_value_is_base64_wrapped(self, stub_server):
        url, recorder = stub_server
        tool = _tool(url, action_schemas={"issue_read": _stored_parameters(OWNER_REPO_SCHEMA)})
        result = tool.execute_action("issue_read", method="get", owner="arc53", repo="Café", issue_number=1)

        assert _text(result) == "arc53/Café#1 via get"
        assert recorder.calls[-1]["mcp-param-repo"].startswith("=?base64?")

    def test_a_schema_stored_without_annotations_is_refreshed(self, stub_server):
        """A row saved before the server added the annotations lists the tools and retries once."""
        url, recorder = stub_server
        stale = json.loads(json.dumps(OWNER_REPO_SCHEMA))
        for prop in stale["properties"].values():
            prop.pop("x-mcp-header", None)
        tool = _tool(url, action_schemas={"issue_read": stale})
        before = len(recorder.calls)

        result = tool.execute_action("issue_read", method="get", owner="arc53", repo="DocsGPT", issue_number=7)

        assert _text(result) == "arc53/DocsGPT#7 via get"
        refused, accepted = recorder.calls[before:]
        assert "mcp-param-repo" not in refused
        assert accepted["mcp-param-repo"] == "DocsGPT"
