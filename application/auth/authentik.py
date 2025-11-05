"""Authentik OIDC authentication service.

This module provides OIDC authentication integration with Authentik,
including token validation, user info retrieval, and OIDC flow handling.
"""

import json
import secrets
import urllib.parse
from typing import Dict, Optional, Tuple

import requests
from jose import jwt, JWTError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from application.core.settings import settings


class AuthentikOIDCError(Exception):
    """Base exception for Authentik OIDC operations."""
    pass


class AuthentikOIDCService:
    """Service for handling Authentik OIDC authentication operations."""

    def __init__(self):
        """Initialize the Authentik OIDC service.
        
        Raises:
            AuthentikOIDCError: If required configuration is missing.
        """
        self._validate_config()
        self.session = self._create_session()
        self._discovery_cache: Optional[Dict] = None
        self._jwks_cache: Optional[Dict] = None

    def _validate_config(self) -> None:
        """Validate required Authentik configuration.
        
        Raises:
            AuthentikOIDCError: If required settings are missing.
        """
        required_settings = [
            "AUTHENTIK_BASE_URL",
            "AUTHENTIK_CLIENT_ID",
            "AUTHENTIK_CLIENT_SECRET",
            "AUTHENTIK_REDIRECT_URI"
        ]
        
        missing = []
        for setting in required_settings:
            if not getattr(settings, setting, None):
                missing.append(setting)
        
        if missing:
            raise AuthentikOIDCError(
                f"Missing required Authentik configuration: {', '.join(missing)}"
            )

    def _create_session(self) -> requests.Session:
        """Create HTTP session with retry strategy.
        
        Returns:
            Configured requests session.
        """
        session = requests.Session()
        
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        if not settings.AUTHENTIK_VERIFY_SSL:
            session.verify = False
            
        return session

    def get_oidc_discovery(self) -> Dict:
        """Get OIDC discovery document from Authentik.
        
        Returns:
            OIDC discovery document as dictionary.
            
        Raises:
            AuthentikOIDCError: If discovery document cannot be retrieved.
        """
        if self._discovery_cache:
            return self._discovery_cache
            
        discovery_url = f"{settings.AUTHENTIK_BASE_URL}/.well-known/openid_configuration"
        
        try:
            response = self.session.get(discovery_url, timeout=10)
            response.raise_for_status()
            self._discovery_cache = response.json()
            return self._discovery_cache
        except requests.RequestException as e:
            raise AuthentikOIDCError(f"Failed to fetch OIDC discovery document: {e}")

    def get_jwks(self) -> Dict:
        """Get JSON Web Key Set (JWKS) from Authentik.
        
        Returns:
            JWKS as dictionary.
            
        Raises:
            AuthentikOIDCError: If JWKS cannot be retrieved.
        """
        if self._jwks_cache:
            return self._jwks_cache
            
        discovery = self.get_oidc_discovery()
        jwks_uri = discovery.get("jwks_uri")
        
        if not jwks_uri:
            raise AuthentikOIDCError("JWKS URI not found in discovery document")
            
        try:
            response = self.session.get(jwks_uri, timeout=10)
            response.raise_for_status()
            self._jwks_cache = response.json()
            return self._jwks_cache
        except requests.RequestException as e:
            raise AuthentikOIDCError(f"Failed to fetch JWKS: {e}")

    def generate_auth_url(self, state: Optional[str] = None) -> Tuple[str, str]:
        """Generate authorization URL for OIDC flow.
        
        Args:
            state: Optional state parameter for CSRF protection.
            
        Returns:
            Tuple of (authorization_url, state)
            
        Raises:
            AuthentikOIDCError: If authorization URL cannot be generated.
        """
        if not state:
            state = secrets.token_urlsafe(32)
            
        discovery = self.get_oidc_discovery()
        auth_endpoint = discovery.get("authorization_endpoint")
        
        if not auth_endpoint:
            raise AuthentikOIDCError("Authorization endpoint not found in discovery document")
            
        params = {
            "client_id": settings.AUTHENTIK_CLIENT_ID,
            "response_type": "code",
            "scope": settings.AUTHENTIK_SCOPES,
            "redirect_uri": settings.AUTHENTIK_REDIRECT_URI,
            "state": state,
        }
        
        auth_url = f"{auth_endpoint}?{urllib.parse.urlencode(params)}"
        return auth_url, state

    def exchange_code_for_tokens(self, code: str) -> Dict:
        """Exchange authorization code for tokens.
        
        Args:
            code: Authorization code from callback.
            
        Returns:
            Token response containing access_token, id_token, etc.
            
        Raises:
            AuthentikOIDCError: If token exchange fails.
        """
        discovery = self.get_oidc_discovery()
        token_endpoint = discovery.get("token_endpoint")
        
        if not token_endpoint:
            raise AuthentikOIDCError("Token endpoint not found in discovery document")
            
        data = {
            "grant_type": "authorization_code",
            "client_id": settings.AUTHENTIK_CLIENT_ID,
            "client_secret": settings.AUTHENTIK_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.AUTHENTIK_REDIRECT_URI,
        }
        
        try:
            response = self.session.post(token_endpoint, data=data, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise AuthentikOIDCError(f"Failed to exchange code for tokens: {e}")

    def validate_id_token(self, id_token: str) -> Dict:
        """Validate and decode ID token.
        
        Args:
            id_token: JWT ID token to validate.
            
        Returns:
            Decoded token claims.
            
        Raises:
            AuthentikOIDCError: If token validation fails.
        """
        try:
            # Get JWKS for token validation
            jwks = self.get_jwks()
            
            # Decode token header to get key ID
            unverified_header = jwt.get_unverified_header(id_token)
            kid = unverified_header.get("kid")
            
            if not kid:
                raise AuthentikOIDCError("Token missing key ID")
                
            # Find matching key
            key = None
            for jwk in jwks.get("keys", []):
                if jwk.get("kid") == kid:
                    key = jwk
                    break
                    
            if not key:
                raise AuthentikOIDCError(f"Key with ID {kid} not found in JWKS")
                
            # Validate and decode token
            discovery = self.get_oidc_discovery()
            issuer = discovery.get("issuer")
            
            claims = jwt.decode(
                id_token,
                key,
                algorithms=["RS256"],
                audience=settings.AUTHENTIK_CLIENT_ID,
                issuer=issuer,
            )
            
            return claims
            
        except JWTError as e:
            raise AuthentikOIDCError(f"Token validation failed: {e}")

    def get_user_info(self, access_token: str) -> Dict:
        """Get user information using access token.
        
        Args:
            access_token: OAuth2 access token.
            
        Returns:
            User information dictionary.
            
        Raises:
            AuthentikOIDCError: If user info retrieval fails.
        """
        discovery = self.get_oidc_discovery()
        userinfo_endpoint = discovery.get("userinfo_endpoint")
        
        if not userinfo_endpoint:
            raise AuthentikOIDCError("Userinfo endpoint not found in discovery document")
            
        headers = {"Authorization": f"Bearer {access_token}"}
        
        try:
            response = self.session.get(userinfo_endpoint, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise AuthentikOIDCError(f"Failed to get user info: {e}")

    def revoke_token(self, token: str, token_type_hint: str = "access_token") -> bool:
        """Revoke token at Authentik.
        
        Args:
            token: Token to revoke.
            token_type_hint: Type of token being revoked.
            
        Returns:
            True if revocation was successful.
            
        Raises:
            AuthentikOIDCError: If token revocation fails.
        """
        discovery = self.get_oidc_discovery()
        revocation_endpoint = discovery.get("revocation_endpoint")
        
        if not revocation_endpoint:
            # Revocation not supported, return True
            return True
            
        data = {
            "token": token,
            "token_type_hint": token_type_hint,
            "client_id": settings.AUTHENTIK_CLIENT_ID,
            "client_secret": settings.AUTHENTIK_CLIENT_SECRET,
        }
        
        try:
            response = self.session.post(revocation_endpoint, data=data, timeout=10)
            return response.status_code in [200, 204]
        except requests.RequestException:
            # Revocation failure is not critical
            return False


# Global service instance
_authentik_service: Optional[AuthentikOIDCService] = None


def get_authentik_service() -> AuthentikOIDCService:
    """Get or create Authentik OIDC service instance.
    
    Returns:
        AuthentikOIDCService instance.
        
    Raises:
        AuthentikOIDCError: If service cannot be initialized.
    """
    global _authentik_service
    
    if _authentik_service is None:
        _authentik_service = AuthentikOIDCService()
        
    return _authentik_service
