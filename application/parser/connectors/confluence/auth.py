import datetime
import logging
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests

from application.core.settings import settings
from application.parser.connectors._auth_utils import session_token_fingerprint
from application.parser.connectors.base import BaseConnectorAuth

logger = logging.getLogger(__name__)


class ConfluenceAuth(BaseConnectorAuth):

    SCOPES = [
        "read:page:confluence",
        "read:space:confluence",
        "read:attachment:confluence",
        "read:me",
        "offline_access",
    ]

    AUTH_URL = "https://auth.atlassian.com/authorize"
    TOKEN_URL = "https://auth.atlassian.com/oauth/token"
    RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"
    ME_URL = "https://api.atlassian.com/me"

    def __init__(self):
        self.client_id = settings.CONFLUENCE_CLIENT_ID
        self.client_secret = settings.CONFLUENCE_CLIENT_SECRET
        self.redirect_uri = settings.CONNECTOR_REDIRECT_BASE_URI

        if not self.client_id or not self.client_secret:
            raise ValueError(
                "Confluence OAuth credentials not configured. "
                "Please set CONFLUENCE_CLIENT_ID and CONFLUENCE_CLIENT_SECRET in settings."
            )

    def get_authorization_url(self, state: Optional[str] = None) -> str:
        params = {
            "audience": "api.atlassian.com",
            "client_id": self.client_id,
            "scope": " ".join(self.SCOPES),
            "redirect_uri": self.redirect_uri,
            "state": state,
            "response_type": "code",
            "prompt": "consent",
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_tokens(self, authorization_code: str) -> Dict[str, Any]:
        if not authorization_code:
            raise ValueError("Authorization code is required")

        response = requests.post(
            self.TOKEN_URL,
            json={
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": authorization_code,
                "redirect_uri": self.redirect_uri,
            },
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        token_data = response.json()

        access_token = token_data.get("access_token")
        if not access_token:
            raise ValueError("OAuth flow did not return an access token")

        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            raise ValueError("OAuth flow did not return a refresh token")

        expires_in = token_data.get("expires_in", 3600)
        expiry = (
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(seconds=expires_in)
        ).isoformat()

        cloud_id = self._fetch_cloud_id(access_token)
        user_info = self._fetch_user_info(access_token)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_uri": self.TOKEN_URL,
            "scopes": self.SCOPES,
            "expiry": expiry,
            "cloud_id": cloud_id,
            "user_info": {
                "name": user_info.get("display_name", ""),
                "email": user_info.get("email", ""),
            },
        }

    def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        if not refresh_token:
            raise ValueError("Refresh token is required")

        response = requests.post(
            self.TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        token_data = response.json()

        access_token = token_data.get("access_token")
        new_refresh_token = token_data.get("refresh_token", refresh_token)

        expires_in = token_data.get("expires_in", 3600)
        expiry = (
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(seconds=expires_in)
        ).isoformat()

        cloud_id = self._fetch_cloud_id(access_token)

        return {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "token_uri": self.TOKEN_URL,
            "scopes": self.SCOPES,
            "expiry": expiry,
            "cloud_id": cloud_id,
        }

    def is_token_expired(self, token_info: Dict[str, Any]) -> bool:
        if not token_info:
            return True

        expiry = token_info.get("expiry")
        if not expiry:
            return bool(token_info.get("access_token"))

        try:
            expiry_dt = datetime.datetime.fromisoformat(expiry)
            now = datetime.datetime.now(datetime.timezone.utc)
            return now >= expiry_dt - datetime.timedelta(seconds=60)
        except Exception:
            return True

    def get_token_info_from_session(self, session_token: str) -> Dict[str, Any]:
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

        required = ["access_token", "refresh_token", "cloud_id"]
        missing = [f for f in required if not token_info.get(f)]
        if missing:
            raise ValueError(f"Missing required token fields: {missing}")

        return token_info

    def sanitize_token_info(
        self, token_info: Dict[str, Any], **extra_fields
    ) -> Dict[str, Any]:
        return super().sanitize_token_info(
            token_info,
            cloud_id=token_info.get("cloud_id"),
            **extra_fields,
        )

    def _fetch_cloud_id(self, access_token: str) -> str:
        response = requests.get(
            self.RESOURCES_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            timeout=30,
        )
        response.raise_for_status()
        resources = response.json()

        if not resources:
            raise ValueError("No accessible Confluence sites found for this account")

        return resources[0]["id"]

    def _fetch_user_info(self, access_token: str) -> Dict[str, Any]:
        try:
            response = requests.get(
                self.ME_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning("Could not fetch user info: %s", e)
            return {}
