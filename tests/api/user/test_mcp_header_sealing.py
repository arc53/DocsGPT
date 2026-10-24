"""Regression tests for the PR #3159 review: MCP custom headers are always sealed."""

from unittest.mock import patch

import pytest

URL = "https://mcp.example.com/mcp"
MCP = "docsgpt.api.user.tools.mcp"


@pytest.fixture(autouse=True)
def _sealing(monkeypatch):
    """Encrypt to a readable fake blob so the tests can see what was sealed."""
    import docsgpt.api.user.tools.mcp as mcp_routes

    monkeypatch.setattr(mcp_routes, "encrypt_credentials", lambda data, uid: f"sealed:{sorted(data.items())}")
    monkeypatch.setattr(mcp_routes, "decrypt_credentials", lambda blob, uid: {"X-Saved": "saved-value"})


def _merge(config, existing=None, moved=False):
    from docsgpt.api.user.tools.mcp import _merge_mcp_headers

    return _merge_mcp_headers(config, {"config": existing} if existing is not None else None, "owner", moved)


def _prepare(new_config, existing_config):
    from docsgpt.api.user.tools.routes import _prepare_tool_config

    tool_doc = {"user_id": "owner", "name": "mcp_tool", "config": existing_config}
    return _prepare_tool_config(tool_doc, new_config, {})


# ------------------------------------------------------------- _merge_mcp_headers


@pytest.mark.unit
@pytest.mark.parametrize("value", [None, False, [], "", 0, "X-A: 1"])
def test_present_non_object_headers_are_refused(value):
    with pytest.raises(ValueError):
        _merge({"headers": value}, {"encrypted_headers": "blob"})


@pytest.mark.unit
def test_absent_headers_keep_the_saved_ones():
    assert _merge({}, {"encrypted_headers": "blob"}) == {"X-Saved": "saved-value"}


@pytest.mark.unit
def test_legacy_plaintext_headers_are_kept_on_test_and_save():
    legacy = {"headers": {"X-Legacy": "old"}}
    assert _merge({}, legacy) == {"X-Legacy": "old"}
    assert _merge({"headers": {"x-legacy": ""}}, legacy) == {"x-legacy": "old"}


@pytest.mark.unit
def test_legacy_plaintext_headers_never_follow_a_new_origin():
    assert _merge({}, {"headers": {"X-Legacy": "old"}}, moved=True) == {}
    assert _merge({"headers": {"X-Legacy": ""}}, {"headers": {"X-Legacy": "old"}}, moved=True) == {}


# ------------------------------------------------------------- _seal_mcp_headers


@pytest.mark.unit
def test_seal_returns_blob_and_names():
    from docsgpt.api.user.tools.mcp import _seal_mcp_headers

    sealed = _seal_mcp_headers({"X-A": "1"}, "owner")
    assert sealed["header_names"] == ["X-A"]
    assert sealed["encrypted_headers"].startswith("sealed:")
    assert _seal_mcp_headers({}, "owner") == {}


@pytest.mark.unit
def test_seal_fails_when_encryption_returns_nothing():
    from docsgpt.api.user.tools.mcp import _seal_mcp_headers

    with patch(f"{MCP}.encrypt_credentials", return_value=""):
        with pytest.raises(RuntimeError):
            _seal_mcp_headers({"X-A": "1"}, "owner")


# ------------------------------------------------------------- generic update path


@pytest.mark.unit
def test_update_seals_plaintext_headers():
    final = _prepare({"server_url": URL, "headers": {"X-A": "1"}}, {"server_url": URL})
    assert "headers" not in final
    assert final["header_names"] == ["X-A"]
    assert "'1'" in final["encrypted_headers"]


@pytest.mark.unit
def test_update_ignores_forged_sealed_keys():
    existing = {"server_url": URL, "encrypted_headers": "real", "header_names": ["X-Real"]}
    final = _prepare({"server_url": URL, "encrypted_headers": "forged", "header_names": ["X-Forged"]}, existing)
    assert final["encrypted_headers"] == "real"
    assert final["header_names"] == ["X-Real"]


@pytest.mark.unit
def test_update_migrates_legacy_plaintext_headers():
    final = _prepare({"server_url": URL}, {"server_url": URL, "headers": {"X-Legacy": "old"}})
    assert "headers" not in final
    assert final["header_names"] == ["X-Legacy"]
    assert "'old'" in final["encrypted_headers"]


@pytest.mark.unit
def test_update_to_a_new_origin_drops_saved_headers():
    existing = {"server_url": URL, "encrypted_headers": "real", "header_names": ["X"], "headers": {"X": "old"}}
    final = _prepare({"server_url": "https://other.example.com/mcp"}, existing)
    assert not set(final) & {"headers", "encrypted_headers", "header_names"}


@pytest.mark.unit
@pytest.mark.parametrize("value", [None, False, []])
def test_update_refuses_non_object_headers(value):
    from docsgpt.api.user.tools.routes import ConfigRefused

    with pytest.raises(ConfigRefused):
        _prepare({"server_url": URL, "headers": value}, {"server_url": URL, "encrypted_headers": "real"})


@pytest.mark.unit
def test_update_refuses_when_encryption_fails():
    from docsgpt.api.user.tools.routes import ConfigRefused

    with patch(f"{MCP}.encrypt_credentials", return_value=""):
        with pytest.raises(ConfigRefused):
            _prepare({"server_url": URL, "headers": {"X-A": "1"}}, {"server_url": URL})


# ------------------------------------------------------------- generic create path


@pytest.mark.unit
def test_create_seals_headers_and_drops_forged_keys():
    from docsgpt.api.user.tools.routes import _seal_mcp_header_config

    plain, sealed = _seal_mcp_header_config(
        {"server_url": URL, "headers": {"X-A": "1"}, "encrypted_headers": "forged"}, {}, "owner", False
    )
    assert plain == {"server_url": URL}
    assert sealed["header_names"] == ["X-A"]


# ------------------------------------------------------------- listings (own and shared)


@pytest.mark.unit
def test_listing_hides_sealed_and_legacy_plaintext_values():
    from docsgpt.api.user.tools.routes import _mask_mcp_tool_config

    masked = _mask_mcp_tool_config({"server_url": URL, "headers": {"X-Legacy": "old"}})
    assert masked == {"server_url": URL, "header_names": ["X-Legacy"]}
    masked = _mask_mcp_tool_config({"encrypted_headers": "blob", "header_names": ["X-A"]})
    assert masked == {"header_names": ["X-A"]}


@pytest.mark.unit
def test_connection_detail_lists_legacy_header_names():
    from docsgpt.connectors.service import _mcp_header_names

    assert _mcp_header_names({"header_names": ["X-A"]}) == ["X-A"]
    assert _mcp_header_names({"headers": {"X-Legacy": "old"}}) == ["X-Legacy"]
    assert _mcp_header_names({}) == []


# ------------------------------------------------------------- unreadable saved headers (review round 2)

UNREADABLE = {"server_url": URL, "encrypted_headers": "old-blob", "header_names": ["X-Tenant", "X-Other"]}


@pytest.fixture
def unreadable(monkeypatch):
    """A rotated or lost key: the stored blob decrypts to nothing."""
    import docsgpt.api.user.tools.mcp as mcp_routes

    monkeypatch.setattr(mcp_routes, "decrypt_credentials", lambda blob, uid: {})


@pytest.mark.unit
@pytest.mark.parametrize("config", [
    {"headers": {"X-Tenant": "", "X-Other": ""}},
    {"headers": {"X-Tenant": "new", "X-Other": ""}},
    {"headers": {"X-Tenant": "new"}},
    {},
])
def test_unreadable_saved_headers_refuse_the_merge(unreadable, config):
    from docsgpt.api.user.tools.mcp import HeadersUnreadable

    with pytest.raises(HeadersUnreadable):
        _merge(config, dict(UNREADABLE))


@pytest.mark.unit
def test_unreadable_saved_headers_can_be_replaced_in_full(unreadable):
    merged = _merge({"headers": {"x-tenant": "a", "X-Other": "b"}}, dict(UNREADABLE))
    assert merged == {"x-tenant": "a", "X-Other": "b"}


@pytest.mark.unit
def test_decryption_error_counts_as_unreadable(monkeypatch):
    import docsgpt.api.user.tools.mcp as mcp_routes

    def fail(blob, uid):
        raise mcp_routes.CredentialDecryptionError("no key opens this blob")

    monkeypatch.setattr(mcp_routes, "decrypt_credentials", fail)
    with pytest.raises(mcp_routes.HeadersUnreadable):
        _merge({"headers": {"X-Tenant": ""}}, dict(UNREADABLE))


@pytest.mark.unit
def test_generic_update_refuses_and_keeps_the_blob(unreadable):
    from docsgpt.api.user.tools.routes import ConfigRefused

    existing = dict(UNREADABLE)
    with pytest.raises(ConfigRefused):
        _prepare({"server_url": URL, "headers": {"X-Tenant": "new", "X-Other": ""}}, existing)
    assert existing == UNREADABLE


@pytest.mark.unit
def test_generic_update_without_headers_keeps_the_blob(unreadable):
    final = _prepare({"server_url": URL, "timeout": 60}, dict(UNREADABLE))
    assert final["encrypted_headers"] == "old-blob"
    assert final["header_names"] == ["X-Tenant", "X-Other"]


@pytest.mark.unit
def test_mcp_save_refuses_before_writing(unreadable):
    from unittest.mock import Mock

    from flask import Flask, request

    import docsgpt.api.user.tools.mcp as mcp_routes

    existing_doc = {"id": "t1", "user_id": "owner", "config": dict(UNREADABLE)}
    writes = Mock(side_effect=AssertionError("nothing may be written"))
    app = Flask(__name__)
    with patch.object(mcp_routes, "_mcp_policy_error", return_value=None), \
            patch.object(mcp_routes, "_validate_mcp_server_url", return_value=None), \
            patch.object(mcp_routes, "_existing_mcp_context", return_value=(existing_doc, "owner", True, False, {})), \
            patch.object(mcp_routes, "db_session", writes), \
            patch.object(mcp_routes, "MCPTool") as tool:
        with app.test_request_context("/api/mcp_server/save", method="POST", json={
            "id": "t1",
            "displayName": "DeepWiki",
            "config": {"server_url": URL, "auth_type": "none", "headers": {"X-Tenant": "", "X-Other": ""}},
        }):
            request.decoded_token = {"sub": "owner"}
            response = mcp_routes.MCPServerSave().post()
    assert response.status_code == 400
    assert "decrypted" in response.get_json()["error"]
    tool.assert_not_called()
    writes.assert_not_called()
    assert existing_doc["config"] == UNREADABLE


# ------------------------------------------------------------- header name and value hardening


@pytest.mark.unit
@pytest.mark.parametrize("name", ["Host", "content-length", "Transfer-Encoding", "Connection", "Upgrade", "TE"])
def test_framing_headers_are_refused(name):
    with pytest.raises(ValueError):
        _merge({"headers": {name: "x"}})


@pytest.mark.unit
@pytest.mark.parametrize("value", ["a\x00b", "a\x1bb", "a\x7fb", "a\rb", "a\nb"])
def test_control_characters_in_values_are_refused(value):
    with pytest.raises(ValueError):
        _merge({"headers": {"X-A": value}})


@pytest.mark.unit
def test_tabs_in_values_are_allowed():
    assert _merge({"headers": {"X-A": "a\tb"}}) == {"X-A": "a\tb"}
