"""Unit tests for Authentik OIDC authentication system.

Tests the authentication service, API endpoints, and integration
with the existing DocsGPT authentication middleware.
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from flask import Flask
import jwt as jose_jwt

from application.auth.authentik import AuthentikOIDCService, AuthentikOIDCError
from application.api.auth.routes import auth_bp
from application.core.settings import settings


class TestAuthentikOIDCService:
    """Test cases for AuthentikOIDCService."""

    def setup_method(self):
        """Set up test fixtures."""
        # Mock settings for testing
        self.mock_settings = {
            "AUTHENTIK_BASE_URL": "https://auth.example.com",
            "AUTHENTIK_CLIENT_ID": "test-client-id",
            "AUTHENTIK_CLIENT_SECRET": "test-client-secret",
            "AUTHENTIK_REDIRECT_URI": "http://localhost:5173/auth/callback",
            "AUTHENTIK_SCOPES": "openid profile email",
            "AUTHENTIK_VERIFY_SSL": True,
        }
        
        # Mock OIDC discovery response
        self.mock_discovery = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/auth",
            "token_endpoint": "https://auth.example.com/token",
            "userinfo_endpoint": "https://auth.example.com/userinfo",
            "jwks_uri": "https://auth.example.com/jwks",
            "revocation_endpoint": "https://auth.example.com/revoke",
        }
        
        # Mock JWKS response
        self.mock_jwks = {
            "keys": [
                {
                    "kid": "test-key-id",
                    "kty": "RSA",
                    "use": "sig",
                    "n": "test-n-value",
                    "e": "AQAB",
                }
            ]
        }
        
        # Mock user claims
        self.mock_user_claims = {
            "sub": "user123",
            "email": "test@example.com",
            "name": "Test User",
            "groups": ["admin", "users"],
            "iss": "https://auth.example.com",
            "aud": "test-client-id",
        }

    @patch('application.auth.authentik.settings')
    def test_validate_config_missing_settings(self, mock_settings):
        """Test configuration validation with missing settings."""
        mock_settings.AUTHENTIK_BASE_URL = None
        mock_settings.AUTHENTIK_CLIENT_ID = "test-id"
        mock_settings.AUTHENTIK_CLIENT_SECRET = "test-secret"
        mock_settings.AUTHENTIK_REDIRECT_URI = "http://localhost/callback"
        
        with pytest.raises(AuthentikOIDCError, match="Missing required Authentik configuration"):
            AuthentikOIDCService()

    @patch('application.auth.authentik.settings')
    @patch('application.auth.authentik.requests.Session')
    def test_get_oidc_discovery_success(self, mock_session_class, mock_settings):
        """Test successful OIDC discovery document retrieval."""
        # Setup mocks
        for key, value in self.mock_settings.items():
            setattr(mock_settings, key, value)
        
        mock_session = Mock()
        mock_session_class.return_value = mock_session
        
        mock_response = Mock()
        mock_response.json.return_value = self.mock_discovery
        mock_session.get.return_value = mock_response
        
        # Test
        service = AuthentikOIDCService()
        discovery = service.get_oidc_discovery()
        
        # Assertions
        assert discovery == self.mock_discovery
        mock_session.get.assert_called_once_with(
            "https://auth.example.com/.well-known/openid_configuration",
            timeout=10
        )

    @patch('application.auth.authentik.settings')
    @patch('application.auth.authentik.requests.Session')
    def test_generate_auth_url(self, mock_session_class, mock_settings):
        """Test authorization URL generation."""
        # Setup mocks
        for key, value in self.mock_settings.items():
            setattr(mock_settings, key, value)
        
        mock_session = Mock()
        mock_session_class.return_value = mock_session
        
        mock_response = Mock()
        mock_response.json.return_value = self.mock_discovery
        mock_session.get.return_value = mock_response
        
        # Test
        service = AuthentikOIDCService()
        auth_url, state = service.generate_auth_url()
        
        # Assertions
        assert "https://auth.example.com/auth" in auth_url
        assert "client_id=test-client-id" in auth_url
        assert "response_type=code" in auth_url
        assert "scope=openid+profile+email" in auth_url
        assert f"state={state}" in auth_url
        assert len(state) > 20  # State should be sufficiently long

    @patch('application.auth.authentik.settings')
    @patch('application.auth.authentik.requests.Session')
    def test_exchange_code_for_tokens_success(self, mock_session_class, mock_settings):
        """Test successful token exchange."""
        # Setup mocks
        for key, value in self.mock_settings.items():
            setattr(mock_settings, key, value)
        
        mock_session = Mock()
        mock_session_class.return_value = mock_session
        
        # Mock discovery response
        discovery_response = Mock()
        discovery_response.json.return_value = self.mock_discovery
        
        # Mock token response
        token_response = Mock()
        token_response.json.return_value = {
            "access_token": "test-access-token",
            "id_token": "test-id-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        
        mock_session.get.return_value = discovery_response
        mock_session.post.return_value = token_response
        
        # Test
        service = AuthentikOIDCService()
        tokens = service.exchange_code_for_tokens("test-code")
        
        # Assertions
        assert tokens["access_token"] == "test-access-token"
        assert tokens["id_token"] == "test-id-token"
        mock_session.post.assert_called_once_with(
            "https://auth.example.com/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "test-client-id",
                "client_secret": "test-client-secret",
                "code": "test-code",
                "redirect_uri": "http://localhost:5173/auth/callback",
            },
            timeout=10
        )

    @patch('application.auth.authentik.settings')
    @patch('application.auth.authentik.requests.Session')
    @patch('application.auth.authentik.jwt')
    def test_validate_id_token_success(self, mock_jwt, mock_session_class, mock_settings):
        """Test successful ID token validation."""
        # Setup mocks
        for key, value in self.mock_settings.items():
            setattr(mock_settings, key, value)
        
        mock_session = Mock()
        mock_session_class.return_value = mock_session
        
        # Mock discovery and JWKS responses
        discovery_response = Mock()
        discovery_response.json.return_value = self.mock_discovery
        
        jwks_response = Mock()
        jwks_response.json.return_value = self.mock_jwks
        
        mock_session.get.side_effect = [discovery_response, jwks_response]
        
        # Mock JWT operations
        mock_jwt.get_unverified_header.return_value = {"kid": "test-key-id"}
        mock_jwt.decode.return_value = self.mock_user_claims
        
        # Test
        service = AuthentikOIDCService()
        claims = service.validate_id_token("test-id-token")
        
        # Assertions
        assert claims == self.mock_user_claims
        mock_jwt.decode.assert_called_once_with(
            "test-id-token",
            self.mock_jwks["keys"][0],
            algorithms=["RS256"],
            audience="test-client-id",
            issuer="https://auth.example.com",
        )


class TestAuthentikAuthRoutes:
    """Test cases for Authentik authentication API routes."""

    def setup_method(self):
        """Set up test fixtures."""
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.secret_key = "test-secret-key"
        self.app.register_blueprint(auth_bp)
        self.client = self.app.test_client()

    @patch('application.api.auth.routes.settings')
    def test_auth_status(self, mock_settings):
        """Test authentication status endpoint."""
        mock_settings.AUTH_TYPE = "authentik"
        
        response = self.client.get("/api/auth/status")
        data = json.loads(response.data)
        
        assert response.status_code == 200
        assert data["auth_type"] == "authentik"
        assert data["authentik_enabled"] is True
        assert data["requires_auth"] is True

    @patch('application.api.auth.routes.settings')
    def test_authentik_login_not_enabled(self, mock_settings):
        """Test login endpoint when authentik is not enabled."""
        mock_settings.AUTH_TYPE = "simple_jwt"
        
        response = self.client.get("/api/auth/authentik/login")
        data = json.loads(response.data)
        
        assert response.status_code == 400
        assert data["error"] == "authentik_not_enabled"

    @patch('application.api.auth.routes.settings')
    @patch('application.api.auth.routes._get_authentik_service')
    def test_authentik_login_success(self, mock_get_service, mock_settings):
        """Test successful login initiation."""
        mock_settings.AUTH_TYPE = "authentik"
        
        mock_service = Mock()
        mock_service.generate_auth_url.return_value = (
            "https://auth.example.com/auth?...",
            "test-state"
        )
        mock_get_service.return_value = mock_service
        
        response = self.client.get("/api/auth/authentik/login")
        data = json.loads(response.data)
        
        assert response.status_code == 200
        assert "auth_url" in data
        assert data["state"] == "test-state"

    @patch('application.api.auth.routes.settings')
    def test_authentik_callback_missing_code(self, mock_settings):
        """Test callback endpoint with missing authorization code."""
        mock_settings.AUTH_TYPE = "authentik"
        
        response = self.client.get("/api/auth/authentik/callback?state=test-state")
        data = json.loads(response.data)
        
        assert response.status_code == 400
        assert data["error"] == "missing_code"

    @patch('application.api.auth.routes.settings')
    @patch('application.api.auth.routes._get_authentik_service')
    def test_authentik_callback_success(self, mock_get_service, mock_settings):
        """Test successful authentication callback."""
        mock_settings.AUTH_TYPE = "authentik"
        
        mock_service = Mock()
        mock_service.exchange_code_for_tokens.return_value = {
            "access_token": "test-access-token",
            "id_token": "test-id-token",
            "expires_in": 3600,
            "token_type": "Bearer"
        }
        mock_service.validate_id_token.return_value = {
            "sub": "user123",
            "email": "test@example.com",
            "name": "Test User",
            "groups": ["users"]
        }
        mock_get_service.return_value = mock_service
        
        with self.client.session_transaction() as sess:
            sess["authentik_state"] = "test-state"
        
        response = self.client.get(
            "/api/auth/authentik/callback?code=test-code&state=test-state"
        )
        data = json.loads(response.data)
        
        assert response.status_code == 200
        assert data["access_token"] == "test-access-token"
        assert data["id_token"] == "test-id-token"
        assert data["user"]["email"] == "test@example.com"

    @patch('application.api.auth.routes.settings')
    @patch('application.api.auth.routes._get_authentik_service')
    def test_authentik_userinfo_success(self, mock_get_service, mock_settings):
        """Test successful user info retrieval."""
        mock_settings.AUTH_TYPE = "authentik"
        
        mock_service = Mock()
        mock_service.get_user_info.return_value = {
            "sub": "user123",
            "email": "test@example.com",
            "name": "Test User",
        }
        mock_get_service.return_value = mock_service
        
        response = self.client.get(
            "/api/auth/authentik/userinfo",
            headers={"Authorization": "Bearer test-access-token"}
        )
        data = json.loads(response.data)
        
        assert response.status_code == 200
        assert data["email"] == "test@example.com"
        mock_service.get_user_info.assert_called_once_with("test-access-token")

    @patch('application.api.auth.routes.settings')
    @patch('application.api.auth.routes._get_authentik_service')
    def test_authentik_logout_success(self, mock_get_service, mock_settings):
        """Test successful logout."""
        mock_settings.AUTH_TYPE = "authentik"
        
        mock_service = Mock()
        mock_service.revoke_token.return_value = True
        mock_get_service.return_value = mock_service
        
        response = self.client.post(
            "/api/auth/authentik/logout",
            json={"access_token": "test-access-token"},
            content_type="application/json"
        )
        data = json.loads(response.data)
        
        assert response.status_code == 200
        assert "Logout completed" in data["message"]
        assert len(data["revocation_results"]) == 1
        assert data["revocation_results"][0]["revoked"] is True


class TestAuthentikIntegration:
    """Test integration with existing DocsGPT authentication system."""

    @patch('application.auth.settings')
    @patch('application.auth.get_authentik_service')
    def test_handle_auth_authentik_success(self, mock_get_service, mock_settings):
        """Test successful authentication through handle_auth function."""
        from application.auth import handle_auth
        
        mock_settings.AUTH_TYPE = "authentik"
        
        mock_service = Mock()
        mock_service.validate_id_token.return_value = {
            "sub": "user123",
            "email": "test@example.com",
            "name": "Test User",
            "groups": ["admin"]
        }
        mock_get_service.return_value = mock_service
        
        mock_request = Mock()
        mock_request.headers.get.return_value = "Bearer test-id-token"
        
        result = handle_auth(mock_request)
        
        assert result["sub"] == "user123"
        assert result["email"] == "test@example.com"
        assert result["name"] == "Test User"
        assert "admin" in result["groups"]
        mock_service.validate_id_token.assert_called_once_with("test-id-token")

    @patch('application.auth.settings')
    def test_handle_auth_authentik_missing_header(self, mock_settings):
        """Test authentication with missing authorization header."""
        from application.auth import handle_auth
        
        mock_settings.AUTH_TYPE = "authentik"
        
        mock_request = Mock()
        mock_request.headers.get.return_value = None
        
        result = handle_auth(mock_request)
        
        assert result is None

    @patch('application.auth.settings')
    def test_handle_auth_backward_compatibility(self, mock_settings):
        """Test that existing JWT auth still works."""
        from application.auth import handle_auth
        
        mock_settings.AUTH_TYPE = "simple_jwt"
        mock_settings.JWT_SECRET_KEY = "test-secret"
        
        # Create a valid JWT token
        payload = {"sub": "test-user"}
        token = jose_jwt.encode(payload, "test-secret", algorithm="HS256")
        
        mock_request = Mock()
        mock_request.headers.get.return_value = f"Bearer {token}"
        
        result = handle_auth(mock_request)
        
        assert result["sub"] == "test-user"


if __name__ == "__main__":
    pytest.main([__file__])
