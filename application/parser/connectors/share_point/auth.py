import datetime
import logging
from typing import Optional, Dict, Any

from msal import ConfidentialClientApplication

from application.core.settings import settings
from application.parser.connectors._auth_utils import session_token_fingerprint
from application.parser.connectors.base import BaseConnectorAuth

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
        self.authority = getattr(settings, "MICROSOFT_AUTHORITY", f"https://login.microsoftonline.com/{self.tenant_id}")

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

    def get_token_info_from_session(self, session_token: str) -> Dict[str, Any]:
        try:
            from application.storage.db.repositories.connector_sessions import (
                ConnectorSessionsRepository,
            )
            from application.storage.db.session import db_readonly

            with db_readonly() as conn:
                session = ConnectorSessionsRepository(conn).get_by_session_token(
                    session_token
                )

            if not session:
                raise ValueError(
                    f"Invalid session token ({session_token_fingerprint(session_token)})"
                )

            token_info = session.get("token_info")
            if not token_info:
                raise ValueError("Session missing token information")

            required_fields = ["access_token", "refresh_token"]
            missing_fields = [field for field in required_fields if field not in token_info or not token_info.get(field)]
            if missing_fields:
                raise ValueError(f"Missing required token fields: {missing_fields}")

            if 'token_uri' not in token_info:
                token_info['token_uri'] = f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/token"

            return token_info

        except Exception as e:
            logger.error("Failed to retrieve token from session: %s", e)
            raise ValueError(f"Failed to retrieve SharePoint token information: {str(e)}")

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

    def map_token_response(self, result) -> Dict[str, Any]:
        claims = result.get("id_token_claims", {})
        return {
            "access_token": result.get("access_token"),
            "refresh_token": result.get("refresh_token"),
            "token_uri": claims.get("iss"),
            "scopes": result.get("scope"),
            "expiry": claims.get("exp"),
            "allows_shared_content": self._allows_shared_content(claims),
            "user_info": {
                "name": claims.get("name"),
                "email": claims.get("preferred_username"),
            },
        }
