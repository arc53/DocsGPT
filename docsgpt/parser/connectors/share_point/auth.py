import datetime
import logging
import time
from typing import Optional, Dict, Any

from msal import ConfidentialClientApplication

from docsgpt.core.settings import settings
from docsgpt.parser.connectors.base import BaseConnectorAuth

logger = logging.getLogger(__name__)


class SharePointAuth(BaseConnectorAuth):
    """
    Handles Microsoft OAuth 2.0 authentication for SharePoint/OneDrive.

    Note: Files.Read scope allows access to files the user has granted access to,
    similar to Google Drive's drive.file scope.
    """

    SCOPES = [
        "Files.Read",
        "Sites.Read.All",
        "User.Read",
    ]

    def __init__(self):
        self.client_id = settings.MICROSOFT_CLIENT_ID
        self.client_secret = settings.MICROSOFT_CLIENT_SECRET

        if not self.client_id:
            raise ValueError(
                "Microsoft OAuth credentials not configured. Please set MICROSOFT_CLIENT_ID in settings."
            )
        
        if not self.client_secret:
            raise ValueError(
                "Microsoft OAuth credentials not configured. Please set MICROSOFT_CLIENT_SECRET in settings."
            )

        self.redirect_uri = settings.CONNECTOR_REDIRECT_BASE_URI
        self.tenant_id = settings.MICROSOFT_TENANT_ID
        self.authority = settings.MICROSOFT_AUTHORITY or f"https://login.microsoftonline.com/{self.tenant_id}"

        self.auth_app = ConfidentialClientApplication(
            client_id=self.client_id,
            client_credential=self.client_secret,
            authority=self.authority
        )

    def get_authorization_url(self, state: Optional[str] = None) -> str:
        return self.auth_app.get_authorization_request_url(
            scopes=self.SCOPES, state=state, redirect_uri=self.redirect_uri
        )

    def exchange_code_for_tokens(self, authorization_code: str) -> Dict[str, Any]:
        result = self.auth_app.acquire_token_by_authorization_code(
            code=authorization_code,
            scopes=self.SCOPES,
            redirect_uri=self.redirect_uri
        )

        if "error" in result:
            logger.error("Token exchange failed: %s", result.get("error_description"))
            raise ValueError(f"Error acquiring token: {result.get('error_description')}")

        return self.map_token_response(result)

    def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        result = self.auth_app.acquire_token_by_refresh_token(refresh_token=refresh_token, scopes=self.SCOPES)

        if "error" in result:
            logger.error("Token refresh failed: %s", result.get("error_description"))
            raise ValueError(f"Error refreshing token: {result.get('error_description')}")

        return self.map_token_response(result)

    def is_token_expired(self, token_info: Dict[str, Any]) -> bool:
        if not token_info:
            return True

        expiry_timestamp = token_info.get("expiry")

        if expiry_timestamp is None:
            return True

        current_timestamp = int(datetime.datetime.now().timestamp())
        return (expiry_timestamp - current_timestamp) < 60

    def sanitize_token_info(self, token_info: Dict[str, Any], **extra_fields) -> Dict[str, Any]:
        return super().sanitize_token_info(
            token_info,
            allows_shared_content=token_info.get("allows_shared_content", False),
            **extra_fields,
        )

    PERSONAL_ACCOUNT_TENANT_ID = "9188040d-6c67-4c5b-b112-36a304b66dad"

    def _allows_shared_content(self, id_token_claims: Dict[str, Any]) -> bool:
        """Return True when the account is a work/school tenant that can access SharePoint shared content."""
        tid = id_token_claims.get("tid", "")
        return bool(tid) and tid != self.PERSONAL_ACCOUNT_TENANT_ID

    @staticmethod
    def _access_token_expiry(result: Dict[str, Any], claims: Dict[str, Any]) -> Optional[int]:
        """When the access token expires: ``expires_in`` from now, else the id_token's ``exp``.

        The id_token has its own lifetime, so its ``exp`` is only a fallback.
        """
        try:
            return int(time.time()) + int(result["expires_in"])
        except (KeyError, TypeError, ValueError):
            return claims.get("exp")

    def map_token_response(self, result) -> Dict[str, Any]:
        # Fields read from id_token claims stay None without them, so a refresh keeps the stored values.
        claims = result.get("id_token_claims") or {}
        return {
            "access_token": result.get("access_token"),
            "refresh_token": result.get("refresh_token"),
            "token_uri": claims.get("iss"),
            "scopes": result.get("scope"),
            "expiry": self._access_token_expiry(result, claims),
            "allows_shared_content": self._allows_shared_content(claims) if claims else None,
            "user_info": {
                "name": claims.get("name"),
                "email": claims.get("preferred_username"),
            },
        }
