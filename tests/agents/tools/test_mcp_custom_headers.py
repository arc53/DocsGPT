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


def _tool(**config):
    import docsgpt.agents.tools.mcp_tool as mcp_mod

    return mcp_mod.MCPTool({
        "server_url": "https://mcp.example.com/mcp",
        "transport_type": "http",
        "query_mode": True,
        "auth_type": "none",
        **config,
    }, user_id="owner")


@pytest.mark.unit
def test_saved_header_values_are_decrypted(monkeypatch):
    import docsgpt.agents.tools.mcp_tool as mcp_mod

    monkeypatch.setattr(mcp_mod, "decrypt_credentials", lambda blob, uid: {"X-Tenant": "saved"})
    headers = dict(_tool(encrypted_headers="sealed")._create_transport().headers)
    assert _values(headers, "X-Tenant") == ["saved"]


@pytest.mark.unit
def test_different_headers_do_not_share_a_cached_client():
    a = _tool(headers={"X-Tenant": "a"})
    b = _tool(headers={"X-Tenant": "b"})
    assert a._cache_key != b._cache_key
    assert _tool()._cache_key == "https://mcp.example.com/mcp#http#none"


STORED = {"X-Tenant": "saved-tenant", "X-Region": "saved-region"}


def _merge(monkeypatch, headers, moved=False):
    import docsgpt.api.user.tools.mcp as mcp_routes

    monkeypatch.setattr(mcp_routes, "decrypt_credentials", lambda blob, uid: dict(STORED))
    existing = {"config": {"encrypted_headers": "sealed"}}
    return mcp_routes._merge_mcp_headers({"headers": headers}, existing, "owner", moved)


@pytest.mark.unit
def test_empty_value_keeps_the_saved_one_in_any_case(monkeypatch):
    assert _merge(monkeypatch, {"x-tenant": ""}) == {"x-tenant": "saved-tenant"}


@pytest.mark.unit
def test_new_value_replaces_the_saved_one(monkeypatch):
    assert _merge(monkeypatch, {"X-Tenant": "new"}) == {"X-Tenant": "new"}


@pytest.mark.unit
def test_header_not_sent_again_is_removed(monkeypatch):
    assert "X-Region" not in _merge(monkeypatch, {"X-Tenant": ""})


@pytest.mark.unit
def test_new_server_never_inherits_saved_values(monkeypatch):
    assert _merge(monkeypatch, {"X-Tenant": ""}, moved=True) == {}


@pytest.mark.unit
def test_new_tool_sends_what_was_typed():
    import docsgpt.api.user.tools.mcp as mcp_routes

    assert mcp_routes._merge_mcp_headers({"headers": {"X-A": "1"}}, None, "owner", False) == {"X-A": "1"}


@pytest.mark.unit
@pytest.mark.parametrize("headers", [
    {"Bad Name": "x"},
    {"X-A": "a\r\nInjected: 1"},
    {"X-A": "1", "x-a": "2"},
    {"X-A": 5},
    ["not", "an", "object"],
])
def test_invalid_headers_are_refused(monkeypatch, headers):
    with pytest.raises(ValueError):
        _merge(monkeypatch, headers)
