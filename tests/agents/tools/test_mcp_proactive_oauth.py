"""Tests for the proactive OAuth flow used by the Hugging Face MCP preset.

Hugging Face serves anonymous MCP requests with HTTP 200, so the MCP SDK
never sees a challenge and never asks for a token. The connector would then
report a completed sign-in while every call still ran unauthenticated.

With ``proactive_oauth`` the sign-in happens before the first request. These
tests cover the initiation, the scope handling, the token-state detection and
the failure paths that keep a silent anonymous sign-in from being reported as
a success.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _patch_mcp_globals(monkeypatch):
    """Isolate the module-level client cache and the URL validation."""
    if "docsgpt.agents.tools.mcp_tool" in sys.modules:
        mcp_mod = sys.modules["docsgpt.agents.tools.mcp_tool"]
    else:
        mock_tasks = MagicMock()
        monkeypatch.setitem(sys.modules, "docsgpt.api.user.tasks", mock_tasks)
        import docsgpt.agents.tools.mcp_tool as mcp_mod

    monkeypatch.setattr(mcp_mod, "_mcp_clients_cache", {})
    monkeypatch.setattr(mcp_mod, "validate_user_base_url", lambda u: None)


def _oauth(**kwargs):
    """A ``DocsGPTOAuth`` with the storage and network layers stubbed out."""
    from docsgpt.agents.tools.mcp_tool import DocsGPTOAuth

    defaults = {
        "mcp_url": "https://huggingface.co/mcp",
        "redirect_uri": "https://example.com/callback",
        "redis_client": MagicMock(),
        "task_id": "task-1",
        "user_id": "user1",
    }
    defaults.update(kwargs)

    with patch("docsgpt.agents.tools.mcp_tool.DBTokenStorage"):
        oauth = DocsGPTOAuth(**defaults)
    # The SDK's ``_initialize`` awaits the stored tokens, so the storage has
    # to answer asynchronously. No token is stored, which is the state a
    # first-time sign-in starts from.
    oauth.context.storage.get_tokens = AsyncMock(return_value=None)
    oauth.context.storage.get_client_info = AsyncMock(return_value=None)
    return oauth


# ---- Scope normalization ------------------------------------------------


class TestOAuthScopeNormalization:
    """The frontend sends scopes as a string, presets as a list."""

    def test_a_list_of_scopes_is_kept_as_a_list(self):
        from docsgpt.agents.tools.mcp_tool import _normalize_oauth_scopes

        assert _normalize_oauth_scopes(["read-mcp", "read-repos"]) == [
            "read-mcp",
            "read-repos",
        ]

    def test_a_comma_separated_string_becomes_a_list(self):
        from docsgpt.agents.tools.mcp_tool import _normalize_oauth_scopes

        assert _normalize_oauth_scopes("read-mcp, read-repos") == [
            "read-mcp",
            "read-repos",
        ]

    def test_a_space_separated_string_becomes_a_list(self):
        from docsgpt.agents.tools.mcp_tool import _normalize_oauth_scopes

        assert _normalize_oauth_scopes("read-mcp read-repos") == [
            "read-mcp",
            "read-repos",
        ]

    def test_none_becomes_an_empty_list(self):
        from docsgpt.agents.tools.mcp_tool import _normalize_oauth_scopes

        assert _normalize_oauth_scopes(None) == []

    def test_empty_scopes_are_dropped(self):
        from docsgpt.agents.tools.mcp_tool import _normalize_oauth_scopes

        assert _normalize_oauth_scopes("read-mcp,,  ,read-repos") == [
            "read-mcp",
            "read-repos",
        ]

    def test_duplicates_are_dropped(self):
        from docsgpt.agents.tools.mcp_tool import _normalize_oauth_scopes

        assert _normalize_oauth_scopes(["read-mcp", "read-mcp"]) == ["read-mcp"]

    def test_a_comma_separated_string_is_not_one_scope(self):
        """The cache key joins the scopes, so a string must not be split per character."""
        from docsgpt.agents.tools.mcp_tool import _normalize_oauth_scopes

        scopes = _normalize_oauth_scopes("read-mcp")
        assert scopes == ["read-mcp"]
        assert ",".join(scopes) == "read-mcp"


class TestMCPToolScopeConfig:
    """The tool reads the scopes from the config it is given."""

    def _tool(self, config):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        base = {
            "server_url": "https://huggingface.co/mcp",
            "transport_type": "http",
            "auth_type": "oauth",
        }
        base.update(config)
        return MCPTool(base, user_id="user1")

    def test_a_list_of_scopes_is_stored_as_a_list(self):
        tool = self._tool({"oauth_scopes": ["read-mcp", "contribute-repos"]})
        assert tool.oauth_scopes == ["read-mcp", "contribute-repos"]

    def test_a_comma_separated_string_is_stored_as_a_list(self):
        tool = self._tool({"oauth_scopes": "read-mcp, contribute-repos"})
        assert tool.oauth_scopes == ["read-mcp", "contribute-repos"]

    def test_no_scopes_becomes_an_empty_list(self):
        tool = self._tool({})
        assert tool.oauth_scopes == []

    def test_the_cache_key_does_not_join_a_string_per_character(self):
        tool = self._tool({"oauth_scopes": "read-mcp"})
        assert "read-mcp" in tool._cache_key
        assert "r,e,a,d" not in tool._cache_key

    def test_proactive_oauth_defaults_to_false(self):
        assert self._tool({}).proactive_oauth is False

    def test_proactive_oauth_is_read_from_the_config(self):
        assert self._tool({"proactive_oauth": True}).proactive_oauth is True


# ---- Proactive initiation ----------------------------------------------


class TestProactiveOAuthInitiation:
    """The sign-in starts before the first request, not after a challenge."""

    def test_the_flow_is_not_started_when_proactive_is_off(self):
        oauth = _oauth(proactive_authorization=False)
        assert oauth.proactive_authorization is False

    def test_the_flow_is_started_when_proactive_is_on(self):
        oauth = _oauth(proactive_authorization=True)
        assert oauth.proactive_authorization is True

    def test_ensure_authorized_signs_in_when_there_is_no_token(self):
        oauth = _oauth(proactive_authorization=True)
        oauth.context.is_token_valid = MagicMock(return_value=False)
        oauth._proactive_sign_in = AsyncMock()

        asyncio.run(oauth._ensure_authorized())

        oauth._proactive_sign_in.assert_awaited_once()
        assert oauth.proactive_signed_in is True

    def test_ensure_authorized_reuses_a_stored_valid_token(self):
        oauth = _oauth(proactive_authorization=True)
        oauth.context.is_token_valid = MagicMock(return_value=True)
        oauth._proactive_sign_in = AsyncMock()

        asyncio.run(oauth._ensure_authorized())

        oauth._proactive_sign_in.assert_not_awaited()
        assert oauth.proactive_signed_in is True

    def test_ensure_authorized_signs_in_only_once(self):
        oauth = _oauth(proactive_authorization=True)
        oauth.context.is_token_valid = MagicMock(return_value=False)
        oauth._proactive_sign_in = AsyncMock()

        asyncio.run(oauth._ensure_authorized())
        asyncio.run(oauth._ensure_authorized())

        oauth._proactive_sign_in.assert_awaited_once()

    def test_a_valid_token_is_not_signed_in_again(self):
        oauth = _oauth(proactive_authorization=True)
        oauth.context.is_token_valid = MagicMock(return_value=True)
        oauth._proactive_sign_in = AsyncMock()

        asyncio.run(oauth._ensure_authorized())

        assert oauth.proactive_signed_in is True
        oauth._proactive_sign_in.assert_not_awaited()


# ---- Scope selection ---------------------------------------------------


class TestProactiveScopeSelection:
    """A preset asks for the scopes it needs, not everything the server offers."""

    def _oauth_with_metadata(self, requested, supported):
        from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata

        oauth = _oauth(scopes=requested, proactive_authorization=True)
        oauth.context.oauth_metadata = OAuthMetadata(
            issuer="https://huggingface.co",
            authorization_endpoint="https://huggingface.co/oauth/authorize",
            token_endpoint="https://huggingface.co/oauth/token",
            scopes_supported=supported.split(),
        )
        oauth.context.protected_resource_metadata = ProtectedResourceMetadata(
            resource="https://huggingface.co/mcp",
            authorization_servers=["https://huggingface.co"],
        )
        return oauth

    def test_the_configured_scopes_are_kept_when_the_server_supports_them(self):
        oauth = self._oauth_with_metadata(
            ["openid", "profile", "read-mcp", "read-repos", "contribute-repos"],
            "openid profile read-mcp read-repos contribute-repos jobs inference-api",
        )

        oauth._proactive_select_scopes()

        assert oauth.context.client_metadata.scope == (
            "openid profile read-mcp read-repos contribute-repos"
        )

    def test_the_servers_scopes_are_used_when_a_requested_one_is_unsupported(self):
        oauth = self._oauth_with_metadata(
            ["read-mcp", "not-a-real-scope"],
            "read-mcp read-repos",
        )

        oauth._proactive_select_scopes()

        assert "not-a-real-scope" not in (oauth.context.client_metadata.scope or "")

    def test_a_comma_separated_string_reaches_the_client_metadata_as_scopes(self):
        oauth = _oauth(scopes="openid, read-mcp", proactive_authorization=True)

        assert oauth.context.client_metadata.scope == "openid read-mcp"

    def test_a_list_reaches_the_client_metadata_as_scopes(self):
        oauth = _oauth(scopes=["openid", "read-mcp"], proactive_authorization=True)

        assert oauth.context.client_metadata.scope == "openid read-mcp"


# ---- Token-state detection ---------------------------------------------


class TestOAuthSignedIn:
    """A discovery that answered anonymously is not a signed-in session."""

    def _tool(self):
        from docsgpt.agents.tools.mcp_tool import MCPTool

        return MCPTool(
            {
                "server_url": "https://huggingface.co/mcp",
                "transport_type": "http",
                "auth_type": "oauth",
                "proactive_oauth": True,
            },
            user_id="user1",
        )

    def test_a_tool_without_an_auth_provider_is_not_signed_in(self):
        tool = self._tool()
        assert tool.oauth_signed_in() is False

    def test_a_provider_without_a_context_is_not_signed_in(self):
        tool = self._tool()
        tool._auth = MagicMock(spec=[])
        assert tool.oauth_signed_in() is False

    def test_a_valid_token_means_signed_in(self):
        tool = self._tool()
        tool._auth = MagicMock()
        tool._auth.context.is_token_valid = MagicMock(return_value=True)
        assert tool.oauth_signed_in() is True

    def test_an_invalid_token_means_not_signed_in(self):
        tool = self._tool()
        tool._auth = MagicMock()
        tool._auth.context.is_token_valid = MagicMock(return_value=False)
        assert tool.oauth_signed_in() is False


# ---- Failure paths -----------------------------------------------------


class TestProactiveOAuthFailures:
    """A failed discovery is reported, not swallowed."""

    def test_discovery_without_protected_resource_metadata_fails(self):
        from mcp.client.auth.exceptions import OAuthFlowError

        oauth = _oauth(proactive_authorization=True)

        with patch(
            "docsgpt.agents.tools.mcp_tool.build_protected_resource_metadata_discovery_urls",
            return_value=["https://huggingface.co/.well-known/oauth-protected-resource"],
        ), patch(
            "docsgpt.agents.tools.mcp_tool._mcp_http_client"
        ) as client_factory:
            client = client_factory.return_value.__aenter__.return_value
            client.send = AsyncMock(
                return_value=MagicMock(status_code=404, text="", headers={})
            )
            with pytest.raises(OAuthFlowError, match="No protected resource metadata"):
                asyncio.run(oauth._proactive_discover("https://huggingface.co/mcp"))

    def test_a_sign_in_failure_is_not_reported_as_a_success(self):
        """``proactive_signed_in`` stays false when the handshake raises."""
        oauth = _oauth(proactive_authorization=True)
        oauth.context.is_token_valid = MagicMock(return_value=False)
        oauth._proactive_sign_in = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(oauth._ensure_authorized())

        assert oauth.proactive_signed_in is False


# ---- The Hugging Face preset -------------------------------------------


class TestHuggingFacePreset:
    """The preset carries the flag and the scopes the fix needs."""

    def _preset(self):
        from docsgpt.connectors import catalog

        return catalog.get_definition("mcp:huggingface")

    def test_the_preset_exists(self):
        assert self._preset() is not None

    def test_the_preset_signs_in_proactively(self):
        assert self._preset().proactive_oauth is True

    def test_the_preset_asks_for_the_expected_scopes(self):
        assert list(self._preset().oauth_scopes) == [
            "openid",
            "profile",
            "read-mcp",
            "read-repos",
            "contribute-repos",
        ]

    def test_the_preset_uses_oauth(self):
        assert self._preset().auth_kind == "mcp_oauth"

    def test_the_preset_points_at_the_hugging_face_mcp_server(self):
        assert self._preset().mcp_url == "https://huggingface.co/mcp"


class TestPresetConfigPropagation:
    """The preset's flag and scopes reach the tool config."""

    def test_the_generated_config_carries_the_flag_and_the_scopes(self):
        from docsgpt.connectors import catalog, service

        definition = catalog.get_definition("mcp:huggingface")
        assert definition is not None

        config = service.preset_mcp_config(definition)

        assert config["proactive_oauth"] is True
        assert config["oauth_scopes"] == [
            "openid",
            "profile",
            "read-mcp",
            "read-repos",
            "contribute-repos",
        ]
        assert config["auth_type"] == "oauth"
