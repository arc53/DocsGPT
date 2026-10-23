"""Custom MCP headers are sent, but never override auth headers (any capitalization)."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_mcp_module(monkeypatch):
    import docsgpt.api.user  # noqa: F401  (avoids an import cycle)
    import docsgpt.agents.tools.mcp_tool as mcp_mod

    monkeypatch.setattr(mcp_mod, "_mcp_clients_cache", {})
    monkeypatch.setattr(mcp_mod, "validate_user_base_url", lambda u: None)


def _headers(**config) -> dict:
    import docsgpt.agents.tools.mcp_tool as mcp_mod

    tool = mcp_mod.MCPTool({
        "server_url": "https://mcp.example.com/mcp",
        "transport_type": "http",
        "query_mode": True,
        **config,
    })
    return dict(tool._create_transport().headers)


def _values(headers: dict, name: str) -> list:
    return [v for k, v in headers.items() if k.lower() == name.lower()]


@pytest.mark.unit
def test_custom_headers_are_sent():
    headers = _headers(auth_type="none", headers={"X-Tenant": "acme"})
    assert _values(headers, "X-Tenant") == ["acme"]


@pytest.mark.unit
@pytest.mark.parametrize("name", ["X-API-Key", "x-api-key", "X-API-KEY", "x-Api-kEy"])
def test_custom_header_cannot_override_api_key(name):
    headers = _headers(
        auth_type="api_key",
        auth_credentials={"api_key": "real-key"},
        headers={name: "evil", "X-Tenant": "acme"},
    )
    assert _values(headers, "X-API-Key") == ["real-key"]
    assert _values(headers, "X-Tenant") == ["acme"]


@pytest.mark.unit
@pytest.mark.parametrize("name", ["X-Custom-Key", "x-custom-key", "X-CUSTOM-KEY"])
def test_custom_header_cannot_override_custom_api_key_header(name):
    headers = _headers(
        auth_type="api_key",
        auth_credentials={"api_key": "real-key", "api_key_header": "X-Custom-Key"},
        headers={name: "evil"},
    )
    assert _values(headers, "X-Custom-Key") == ["real-key"]


@pytest.mark.unit
@pytest.mark.parametrize("name", ["Authorization", "authorization", "AUTHORIZATION"])
def test_custom_header_cannot_override_basic_auth(name):
    headers = _headers(
        auth_type="basic",
        auth_credentials={"username": "u", "password": "p"},
        headers={name: "Basic evil"},
    )
    values = _values(headers, "Authorization")
    assert len(values) == 1 and values[0] != "Basic evil"


@pytest.mark.unit
@pytest.mark.parametrize("name", ["Authorization", "authorization", "AUTHORIZATION"])
def test_custom_authorization_dropped_for_bearer(name):
    headers = _headers(
        auth_type="bearer",
        auth_credentials={"bearer_token": "tok"},
        headers={name: "Bearer evil", "X-Tenant": "acme"},
    )
    assert _values(headers, "Authorization") == []
    assert _values(headers, "X-Tenant") == ["acme"]


@pytest.mark.unit
def test_custom_header_case_does_not_duplicate_defaults():
    headers = _headers(auth_type="none", headers={"content-type": "application/json"})
    assert len(_values(headers, "Content-Type")) == 1
