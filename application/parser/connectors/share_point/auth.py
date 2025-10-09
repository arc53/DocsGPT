import logging
import datetime
from typing import Optional, Dict, Any

from msal import ConfidentialClientApplication

from application.core.settings import settings
from application.parser.connectors.base import BaseConnectorAuth


class SharePointAuth(BaseConnectorAuth):
    """
    Handles Microsoft OAuth 2.0 authentication.

    # Documentation:
    - https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow
    - https://learn.microsoft.com/en-gb/entra/msal/python/
    """

    # Microsoft Graph scopes for SharePoint access
    SCOPES = [
        "User.Read",
    ]

    def __init__(self):
        self.client_id = settings.MICROSOFT_CLIENT_ID
        self.client_secret = settings.MICROSOFT_CLIENT_SECRET

        if not self.client_id or not self.client_secret:
            raise ValueError(
                "Microsoft OAuth credentials not configured. Please set MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET in settings."
            )

        self.redirect_uri = settings.CONNECTOR_REDIRECT_BASE_URI
        self.tenant_id = settings.MICROSOFT_TENANT_ID
        self.authority = getattr(settings, "MICROSOFT_AUTHORITY", f"https://{self.tenant_id}.ciamlogin.com/{self.tenant_id}")

        self.auth_app = ConfidentialClientApplication(
            client_id=self.client_id, client_credential=self.client_secret, authority=self.authority
        )

    def get_authorization_url(self, state: Optional[str] = None) -> str:
        return self.auth_app.get_authorization_request_url(
            scopes=self.SCOPES, state=state, redirect_uri=self.redirect_uri
        )

    def exchange_code_for_tokens(self, authorization_code: str) -> Dict[str, Any]:
        result = self.auth_app.acquire_token_by_authorization_code(
            code=authorization_code, scopes=self.SCOPES, redirect_uri=self.redirect_uri
        )

        if "error" in result:
            logging.error(f"Error acquiring token: {result.get('error_description')}")
            raise ValueError(f"Error acquiring token: {result.get('error_description')}")

        return self.map_token_response(result)

    def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        result = self.auth_app.acquire_token_by_refresh_token(refresh_token=refresh_token, scopes=self.SCOPES)

        if "error" in result:
            logging.error(f"Error acquiring token: {result.get('error_description')}")
            raise ValueError(f"Error acquiring token: {result.get('error_description')}")

        return self.map_token_response(result)

    def is_token_expired(self, token_info: Dict[str, Any]) -> bool:
        if not token_info or "expiry" not in token_info:
            # If no expiry info, consider token expired to be safe
            return True

        # Get expiry timestamp and current time
        expiry_timestamp = token_info["expiry"]
        current_timestamp = int(datetime.datetime.now().timestamp())

        # Token is expired if current time is greater than or equal to expiry time
        return current_timestamp >= expiry_timestamp

    def map_token_response(self, result) -> Dict[str, Any]:
        return {
            "access_token": result.get("access_token"),
            "refresh_token": result.get("refresh_token"),
            "token_uri": result.get("id_token_claims", {}).get("iss"),
            "scopes": result.get("scope"),
            "expiry": result.get("id_token_claims", {}).get("exp"),
            "user_info": {
                "name": result.get("id_token_claims", {}).get("name"),
                "email": result.get("id_token_claims", {}).get("preferred_username"),
            },
            "raw_token": result,
        }
