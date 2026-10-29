"""Flow-level tests for the proactive OAuth handshake used by the Hugging Face preset.

``test_mcp_proactive_oauth.py`` covers the configuration surface: the flag, the
scopes, the preset and the token-state detection. This file covers the
handshake itself — the parts that only run once a server actually answers:
issuer validation (RFC 8414), the authorization-response issuer (RFC 9207),
scope selection, client registration (RFC 7591 and CIMD), the RFC 8707
resource match, and the token response.

Every test here is a mock. None of them talks to a real authorization server.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx2
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

    # The SDK awaits the stored state, so the storage answers asynchronously.
    oauth.context.storage.get_tokens = AsyncMock(return_value=None)
    oauth.context.storage.get_client_info = AsyncMock(return_value=None)
    oauth.context.storage.set_tokens = AsyncMock()
    oauth.context.storage.set_client_info = AsyncMock()
    return oauth


def _http_client(*responses):
    """A stand-in for ``_mcp_http_client`` whose client sends ``responses`` in order."""
    client = MagicMock()
    client.send = AsyncMock(side_effect=list(responses))
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = client
    factory.return_value.__aexit__.return_value = False
    return factory


def _json_response(status_code: int, body: dict) -> httpx2.Response:
    return httpx2.Response(status_code, json=body)


# The documents a Hugging Face-shaped server publishes.
PRM = {
    "resource": "https://huggingface.co/mcp",
    "authorization_servers": ["https://huggingface.co"],
    "scopes_supported": [
        "openid",
        "profile",
        "read-mcp",
        "read-repos",
        "contribute-repos",
    ],
}

ASM = {
    "issuer": "https://huggingface.co",
    "authorization_endpoint": "https://huggingface.co/oauth/authorize",
    "token_endpoint": "https://huggingface.co/oauth/token",
    "registration_endpoint": "https://huggingface.co/oauth/register",
    "response_types_supported": ["code"],
    "grant_types_supported": ["authorization_code", "refresh_token"],
    "code_challenge_methods_supported": ["S256"],
    "scopes_supported": [
        "openid",
        "profile",
        "read-mcp",
        "read-repos",
        "contribute-repos",
        "jobs",
        "inference-api",
    ],
}


def _metadata(**overrides):
    from mcp.shared.auth import OAuthMetadata

    body = dict(ASM)
    body.update(overrides)
    return OAuthMetadata.model_validate(body)


# ---- Discovery: the resource document and the authorization server --------


class TestProactiveDiscovery:
    """The handshake reads both documents before it registers anything."""

    def _discover(self, oauth, prm=None, asm=None):
        """Run ``_proactive_discover`` against two canned documents."""
        prm_response = _json_response(200, PRM if prm is None else prm)
        asm_response = _json_response(200, ASM if asm is None else asm)

        with patch(
            "docsgpt.agents.tools.mcp_tool._mcp_http_client",
            _http_client(prm_response, asm_response),
        ):
            asyncio.run(oauth._proactive_discover("https://huggingface.co/mcp"))

    def test_the_protected_resource_metadata_is_read(self):
        oauth = _oauth(proactive_authorization=True)
        self._discover(oauth)

        assert oauth.context.protected_resource_metadata is not None
        assert (
            str(oauth.context.protected_resource_metadata.resource)
            == "https://huggingface.co/mcp"
        )

    def test_the_authorization_server_metadata_is_read(self):
        oauth = _oauth(proactive_authorization=True)
        self._discover(oauth)

        assert oauth.context.oauth_metadata is not None
        assert (
            str(oauth.context.oauth_metadata.token_endpoint)
            == "https://huggingface.co/oauth/token"
        )

    def test_the_advertised_authorization_server_is_recorded(self):
        oauth = _oauth(proactive_authorization=True)
        self._discover(oauth)

        assert oauth.context.auth_server_url == "https://huggingface.co"

    def test_the_first_advertised_authorization_server_is_used(self):
        oauth = _oauth(proactive_authorization=True)
        self._discover(
            oauth,
            prm={
                "resource": "https://huggingface.co/mcp",
                "authorization_servers": [
                    "https://huggingface.co",
                    "https://auth.huggingface.co",
                ],
            },
        )

        assert oauth.context.auth_server_url == "https://huggingface.co"

    def test_a_mismatched_metadata_issuer_is_rejected(self):
        """RFC 8414 §3.3: the issuer must be the one discovery was built from."""
        from mcp.client.auth.exceptions import OAuthFlowError

        oauth = _oauth(proactive_authorization=True)
        with pytest.raises(OAuthFlowError, match="issuer mismatch"):
            self._discover(oauth, asm={**ASM, "issuer": "https://evil.example.com"})

    def test_a_matching_metadata_issuer_is_accepted(self):
        oauth = _oauth(proactive_authorization=True)
        self._discover(oauth, asm={**ASM, "issuer": "https://huggingface.co"})

        assert oauth.context.oauth_metadata is not None

    def test_a_metadata_issuer_that_only_differs_by_a_slash_is_rejected(self):
        """The strict comparison only relaxes a root slash on the legacy path."""
        from mcp.client.auth.exceptions import OAuthFlowError

        oauth = _oauth(proactive_authorization=True)
        with pytest.raises(OAuthFlowError, match="issuer mismatch"):
            self._discover(oauth, asm={**ASM, "issuer": "https://huggingface.co/"})


# ---- RFC 8707: the resource the token is bound to -------------------------


class TestResourceMatch:
    """The protected resource must cover the server the client called."""

    def _discover(self, oauth, prm):
        prm_response = _json_response(200, prm)
        asm_response = _json_response(200, ASM)

        with patch(
            "docsgpt.agents.tools.mcp_tool._mcp_http_client",
            _http_client(prm_response, asm_response),
        ):
            asyncio.run(oauth._proactive_discover("https://huggingface.co/mcp"))

    def test_a_resource_on_another_host_is_rejected(self):
        from mcp.client.auth.exceptions import OAuthFlowError

        oauth = _oauth(proactive_authorization=True)
        with pytest.raises(OAuthFlowError, match="does not match expected"):
            self._discover(
                oauth,
                {
                    "resource": "https://evil.example.com/mcp",
                    "authorization_servers": ["https://huggingface.co"],
                },
            )

    def test_a_sibling_path_on_the_same_host_is_rejected(self):
        from mcp.client.auth.exceptions import OAuthFlowError

        oauth = _oauth(proactive_authorization=True)
        with pytest.raises(OAuthFlowError, match="does not match expected"):
            self._discover(
                oauth,
                {
                    "resource": "https://huggingface.co/other",
                    "authorization_servers": ["https://huggingface.co"],
                },
            )

    def test_a_parent_resource_is_accepted(self):
        """A token for the host covers the path underneath it."""
        oauth = _oauth(proactive_authorization=True)
        self._discover(
            oauth,
            {
                "resource": "https://huggingface.co",
                "authorization_servers": ["https://huggingface.co"],
            },
        )

        assert oauth.context.protected_resource_metadata is not None


# ---- RFC 9207: the issuer in the authorization response ------------------


class TestAuthorizationResponseIssuer:
    """The ``iss`` parameter is compared with the issuer the request was sent to."""

    def _grant(self, oauth, iss):
        """Run the SDK's authorization-code grant with a canned callback result."""
        from mcp.shared.auth import AuthorizationCodeResult

        captured = {}

        async def fake_redirect(authorization_url):
            captured["url"] = authorization_url

        async def fake_callback():
            state = parse_qs(urlparse(captured["url"]).query)["state"][0]
            return AuthorizationCodeResult(code="the-code", state=state, iss=iss)

        oauth.context.redirect_handler = fake_redirect
        oauth.context.callback_handler = fake_callback
        return asyncio.run(oauth._perform_authorization_code_grant())

    def _oauth_with_issuer(self, **metadata_overrides):
        from mcp.shared.auth import OAuthClientInformationFull

        oauth = _oauth(proactive_authorization=True)
        oauth.context.oauth_metadata = _metadata(**metadata_overrides)
        oauth.context.client_info = OAuthClientInformationFull(
            client_id="the-client-id",
            redirect_uris=["https://example.com/callback"],
        )
        return oauth

    def test_a_matching_iss_is_accepted(self):
        oauth = self._oauth_with_issuer()

        code, verifier = self._grant(oauth, "https://huggingface.co")

        assert code == "the-code"
        assert verifier

    def test_a_mismatched_iss_is_rejected(self):
        from mcp.client.auth.exceptions import OAuthFlowError

        oauth = self._oauth_with_issuer()

        with pytest.raises(OAuthFlowError, match="iss mismatch"):
            self._grant(oauth, "https://evil.example.com")

    def test_a_missing_iss_is_accepted_when_it_is_not_advertised(self):
        oauth = self._oauth_with_issuer()

        code, _ = self._grant(oauth, None)

        assert code == "the-code"

    def test_a_missing_iss_is_rejected_when_the_server_advertises_it(self):
        from mcp.client.auth.exceptions import OAuthFlowError

        oauth = self._oauth_with_issuer(
            authorization_response_iss_parameter_supported=True
        )

        with pytest.raises(OAuthFlowError, match="missing iss"):
            self._grant(oauth, None)

    def test_the_callback_returns_the_issuer_the_worker_stored(self):
        oauth = _oauth(proactive_authorization=True)
        oauth.extracted_state = "state-123"
        oauth.redis_client.get.side_effect = lambda key: (
            b"the-code"
            if key.endswith("code:state-123")
            else (b"https://huggingface.co" if key.endswith("iss:state-123") else None)
        )

        result = asyncio.run(oauth.callback_handler())

        assert result.code == "the-code"
        assert result.iss == "https://huggingface.co"

    def test_the_callback_reports_no_issuer_when_none_was_stored(self):
        oauth = _oauth(proactive_authorization=True)
        oauth.extracted_state = "state-123"
        oauth.redis_client.get.side_effect = lambda key: (
            b"the-code" if key.endswith("code:state-123") else None
        )

        result = asyncio.run(oauth.callback_handler())

        assert result.iss is None


# ---- Scope selection -----------------------------------------------------


class TestScopeSelection:
    """The requested scopes are kept when the server supports them."""

    def _oauth_with_metadata(self, requested, prm_scopes, asm_scopes):
        from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata

        oauth = _oauth(scopes=requested, proactive_authorization=True)
        oauth.context.oauth_metadata = OAuthMetadata.model_validate(
            {**ASM, "scopes_supported": asm_scopes}
        )
        oauth.context.protected_resource_metadata = ProtectedResourceMetadata(
            resource="https://huggingface.co/mcp",
            authorization_servers=["https://huggingface.co"],
            scopes_supported=prm_scopes,
        )
        return oauth

    def test_the_protected_resource_scopes_win_over_the_server_scopes(self):
        oauth = self._oauth_with_metadata(
            ["read-mcp", "jobs"],
            ["read-mcp"],
            ["read-mcp", "jobs"],
        )

        oauth._proactive_select_scopes()

        assert oauth.context.client_metadata.scope == "read-mcp"

    def test_an_unsupported_requested_scope_replaces_the_whole_set(self):
        oauth = self._oauth_with_metadata(
            ["read-mcp", "not-a-real-scope"],
            ["read-mcp", "read-repos"],
            ["read-mcp", "read-repos"],
        )

        oauth._proactive_select_scopes()

        assert "not-a-real-scope" not in (oauth.context.client_metadata.scope or "")
        assert oauth.context.client_metadata.scope == "read-mcp read-repos"

    def test_the_configured_scopes_are_kept_when_the_server_supports_them(self):
        """The SDK's ``offline_access`` augmentation does not override the
        configured set: a preset that asks for what it needs keeps it."""
        oauth = self._oauth_with_metadata(
            ["read-mcp"],
            ["read-mcp"],
            ["read-mcp", "offline_access"],
        )

        oauth._proactive_select_scopes()

        assert oauth.context.client_metadata.scope == "read-mcp"

    def test_the_server_scopes_are_adopted_when_a_requested_one_is_unsupported(self):
        """Replacing the set brings the SDK's augmentation with it."""
        oauth = self._oauth_with_metadata(
            ["read-mcp", "not-a-real-scope"],
            ["read-mcp"],
            ["read-mcp", "offline_access"],
        )

        oauth._proactive_select_scopes()

        assert oauth.context.client_metadata.scope == "read-mcp offline_access"

    def test_the_scope_is_untouched_without_any_metadata(self):
        oauth = _oauth(scopes=["read-mcp"], proactive_authorization=True)

        oauth._proactive_select_scopes()

        assert oauth.context.client_metadata.scope == "read-mcp"


# ---- Client registration -------------------------------------------------


class TestClientRegistration:
    """The client is registered with the discovered server before it signs in."""

    def test_dynamic_registration_is_used_by_default(self):
        oauth = _oauth(proactive_authorization=True)
        oauth.context.oauth_metadata = _metadata()
        oauth.context.auth_server_url = "https://huggingface.co"

        registration = _json_response(
            201,
            {
                "client_id": "minted-client-id",
                "token_endpoint_auth_method": "none",
                "redirect_uris": ["https://example.com/callback"],
            },
        )

        with patch(
            "docsgpt.agents.tools.mcp_tool._mcp_http_client",
            _http_client(registration),
        ):
            asyncio.run(oauth._proactive_register_client())

        assert oauth.context.client_info is not None
        assert oauth.context.client_info.client_id == "minted-client-id"

    def test_the_issuer_is_stamped_on_the_registration(self):
        oauth = _oauth(proactive_authorization=True)
        oauth.context.oauth_metadata = _metadata()
        oauth.context.auth_server_url = "https://huggingface.co"

        registration = _json_response(
            201,
            {
                "client_id": "minted-client-id",
                "token_endpoint_auth_method": "none",
                "redirect_uris": ["https://example.com/callback"],
            },
        )

        with patch(
            "docsgpt.agents.tools.mcp_tool._mcp_http_client",
            _http_client(registration),
        ):
            asyncio.run(oauth._proactive_register_client())

        assert oauth.context.client_info.issuer == "https://huggingface.co"

    def test_an_issuer_the_server_invented_is_ignored(self):
        """The server cannot move these credentials to another issuer."""
        oauth = _oauth(proactive_authorization=True)
        oauth.context.oauth_metadata = _metadata()
        oauth.context.auth_server_url = "https://huggingface.co"

        registration = _json_response(
            201,
            {
                "client_id": "minted-client-id",
                "token_endpoint_auth_method": "none",
                "redirect_uris": ["https://example.com/callback"],
                "issuer": "https://evil.example.com",
            },
        )

        with patch(
            "docsgpt.agents.tools.mcp_tool._mcp_http_client",
            _http_client(registration),
        ):
            asyncio.run(oauth._proactive_register_client())

        assert oauth.context.client_info.issuer == "https://huggingface.co"

    def test_a_url_based_client_id_is_used_when_the_server_supports_it(self):
        """CIMD: the client ID is a URL the server already knows."""
        oauth = _oauth(proactive_authorization=True)
        oauth.context.oauth_metadata = _metadata(
            client_id_metadata_document_supported=True
        )
        oauth.context.auth_server_url = "https://huggingface.co"
        oauth.context.client_metadata_url = "https://huggingface.co/client-metadata.json"

        asyncio.run(oauth._proactive_register_client())

        assert oauth.context.client_info is not None
        assert (
            oauth.context.client_info.client_id
            == "https://huggingface.co/client-metadata.json"
        )
        assert oauth.context.client_info.token_endpoint_auth_method == "none"

    def test_a_registration_the_flow_cannot_use_is_refused(self):
        """A private_key_jwt registration is one this flow has no key to sign."""
        from mcp.client.auth.exceptions import OAuthRegistrationError

        oauth = _oauth(proactive_authorization=True)
        oauth.context.oauth_metadata = _metadata()
        oauth.context.auth_server_url = "https://huggingface.co"

        registration = _json_response(
            201,
            {
                "client_id": "minted-client-id",
                "token_endpoint_auth_method": "private_key_jwt",
                "redirect_uris": ["https://example.com/callback"],
            },
        )

        with patch(
            "docsgpt.agents.tools.mcp_tool._mcp_http_client",
            _http_client(registration),
        ):
            with pytest.raises(OAuthRegistrationError, match="unsupported"):
                asyncio.run(oauth._proactive_register_client())

    def test_a_registration_with_no_usable_secret_is_refused(self):
        from mcp.client.auth.exceptions import OAuthRegistrationError

        oauth = _oauth(proactive_authorization=True)
        oauth.context.oauth_metadata = _metadata()
        oauth.context.auth_server_url = "https://huggingface.co"

        registration = _json_response(
            201,
            {
                "client_id": "minted-client-id",
                "token_endpoint_auth_method": "client_secret_basic",
                "redirect_uris": ["https://example.com/callback"],
            },
        )

        with patch(
            "docsgpt.agents.tools.mcp_tool._mcp_http_client",
            _http_client(registration),
        ):
            with pytest.raises(OAuthRegistrationError, match="client_secret"):
                asyncio.run(oauth._proactive_register_client())


# ---- The token response --------------------------------------------------


class TestTokenResponse:
    """The token endpoint's answer is parsed and stored."""

    def _exchange(self, oauth, response):
        with patch(
            "docsgpt.agents.tools.mcp_tool._mcp_http_client",
            _http_client(response),
        ):
            asyncio.run(oauth._handle_token_response(response))

    def test_the_access_token_is_stored(self):
        oauth = _oauth(proactive_authorization=True)

        self._exchange(
            oauth,
            _json_response(
                200,
                {"access_token": "the-token", "token_type": "Bearer", "expires_in": 3600},
            ),
        )

        assert oauth.context.current_tokens is not None
        assert oauth.context.current_tokens.access_token == "the-token"

    def test_the_granted_scope_is_recorded(self):
        oauth = _oauth(scopes=["read-mcp"], proactive_authorization=True)

        self._exchange(
            oauth,
            _json_response(
                200,
                {
                    "access_token": "the-token",
                    "token_type": "Bearer",
                    "scope": "read-mcp read-repos",
                },
            ),
        )

        assert oauth.context.current_tokens.scope == "read-mcp read-repos"

    def test_an_omitted_scope_becomes_the_requested_scope(self):
        """RFC 6749 §5.1: an omitted scope means the granted scope is the request."""
        oauth = _oauth(scopes=["read-mcp", "read-repos"], proactive_authorization=True)

        self._exchange(
            oauth,
            _json_response(
                200, {"access_token": "the-token", "token_type": "Bearer"}
            ),
        )

        assert oauth.context.current_tokens.scope == "read-mcp read-repos"

    def test_a_refused_exchange_is_reported(self):
        from mcp.client.auth.exceptions import OAuthTokenError

        oauth = _oauth(proactive_authorization=True)

        with pytest.raises(OAuthTokenError, match="Token exchange failed"):
            self._exchange(oauth, _json_response(400, {"error": "invalid_grant"}))

    def test_the_tokens_are_persisted(self):
        oauth = _oauth(proactive_authorization=True)

        self._exchange(
            oauth,
            _json_response(
                200, {"access_token": "the-token", "token_type": "Bearer"}
            ),
        )

        oauth.context.storage.set_tokens.assert_awaited_once()


# ---- The handshake as a whole --------------------------------------------


class TestProactiveHandshake:
    """The sign-in runs discovery, selection, registration and the exchange."""

    def test_the_steps_run_in_order(self):
        oauth = _oauth(proactive_authorization=True)
        calls = []

        async def discover(server_url):
            calls.append("discover")

        def select_scopes():
            calls.append("select_scopes")

        async def register():
            calls.append("register")

        async def grant():
            calls.append("grant")
            return "the-code", "the-verifier"

        async def exchange(auth_code, code_verifier):
            calls.append("exchange")
            return MagicMock(name="token_request")

        async def handle(response):
            calls.append("handle")

        oauth._proactive_discover = AsyncMock(side_effect=discover)
        oauth._proactive_select_scopes = MagicMock(side_effect=select_scopes)
        oauth._proactive_register_client = AsyncMock(side_effect=register)
        oauth._perform_authorization_code_grant = AsyncMock(side_effect=grant)
        oauth._exchange_token_authorization_code = AsyncMock(side_effect=exchange)
        oauth._handle_token_response = AsyncMock(side_effect=handle)

        token_response = _json_response(
            200, {"access_token": "the-token", "token_type": "Bearer"}
        )

        with patch(
            "docsgpt.agents.tools.mcp_tool._mcp_http_client",
            _http_client(token_response),
        ):
            asyncio.run(oauth._proactive_sign_in())

        assert calls == [
            "discover",
            "select_scopes",
            "register",
            "grant",
            "exchange",
            "handle",
        ]

    def test_a_failed_discovery_stops_the_handshake(self):
        from mcp.client.auth.exceptions import OAuthFlowError

        oauth = _oauth(proactive_authorization=True)
        oauth._proactive_discover = AsyncMock(
            side_effect=OAuthFlowError("No protected resource metadata published")
        )
        oauth._proactive_register_client = AsyncMock()

        with pytest.raises(OAuthFlowError, match="No protected resource metadata"):
            asyncio.run(oauth._proactive_sign_in())

        oauth._proactive_register_client.assert_not_awaited()

    def test_the_sign_in_happens_before_the_first_request(self):
        """The SDK only asks for a token after a 401, which HF never sends."""
        from mcp.client.auth.oauth2 import OAuthClientProvider

        oauth = _oauth(proactive_authorization=True)
        oauth._ensure_authorized = AsyncMock()

        async def empty_flow(self, request):
            return
            yield  # pragma: no cover - makes this an async generator

        request = httpx2.Request("GET", "https://huggingface.co/mcp")

        async def drive():
            async for _ in oauth.async_auth_flow(request):
                pass

        with patch.object(OAuthClientProvider, "async_auth_flow", empty_flow):
            asyncio.run(drive())

        oauth._ensure_authorized.assert_awaited_once()

    def test_the_sign_in_is_skipped_when_a_valid_token_is_stored(self):
        oauth = _oauth(proactive_authorization=True)
        oauth.context.is_token_valid = MagicMock(return_value=True)
        oauth._proactive_sign_in = AsyncMock()

        asyncio.run(oauth._ensure_authorized())

        oauth._proactive_sign_in.assert_not_awaited()
        assert oauth.proactive_signed_in is True
