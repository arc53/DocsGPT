"""Sign in with GitHub through a GitHub App (user access tokens).

A GitHub App's user token can read what both the user and the app's
installations can see: the repositories are chosen when the user installs
the app, not with OAuth scopes. Tokens last eight hours and come with a
six-month refresh token, unless the app turned token expiry off, in which
case they carry no expiry and never need refreshing.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests

from docsgpt.core.settings import settings
from docsgpt.parser.connectors.base import BaseConnectorAuth

logger = logging.getLogger(__name__)

API_URL = "https://api.github.com"


class GitHubAuth(BaseConnectorAuth):
    """OAuth web flow of the GitHub App set in ``GITHUB_CLIENT_ID`` and friends."""

    AUTH_URL = "https://github.com/login/oauth/authorize"
    TOKEN_URL = "https://github.com/login/oauth/access_token"
    # Refresh this long before the stated expiry, so a token never lapses mid-request.
    EXPIRY_MARGIN = datetime.timedelta(minutes=5)

    def __init__(self):
        self.client_id = settings.GITHUB_CLIENT_ID
        self.client_secret = settings.GITHUB_CLIENT_SECRET
        self.app_slug = settings.GITHUB_APP_SLUG
        self.redirect_uri = settings.CONNECTOR_REDIRECT_BASE_URI
        if not self.client_id or not self.client_secret:
            raise ValueError(
                "GitHub App credentials not configured. "
                "Please set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in settings."
            )

    def get_authorization_url(self, state: Optional[str] = None) -> str:
        """The GitHub page that asks the user to authorize the app."""
        params = {"client_id": self.client_id, "redirect_uri": self.redirect_uri, "state": state}
        return f"{self.AUTH_URL}?{urlencode({k: v for k, v in params.items() if v})}"

    def get_installation_url(self, state: Optional[str] = None) -> str:
        """The GitHub page where the user installs the app and picks repositories.

        With "Request user authorization (OAuth) during installation" on, GitHub
        sends the user back to the callback with a code and this ``state``.
        """
        base = f"https://github.com/apps/{self.app_slug}/installations/new"
        return f"{base}?{urlencode({'state': state})}" if state else base

    def _token_request(self, data: Dict[str, str]) -> Dict[str, Any]:
        """POST to the token endpoint; GitHub reports failures as 200 with ``error``."""
        response = requests.post(
            self.TOKEN_URL,
            data={"client_id": self.client_id, "client_secret": self.client_secret, **data},
            headers={"Accept": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("error") or not payload.get("access_token"):
            error = payload.get("error") if isinstance(payload, dict) else None
            raise ValueError(f"GitHub refused the sign-in: {error or 'no access token returned'}")
        return payload

    @staticmethod
    def _tokens(payload: Dict[str, Any], refresh_token: Optional[str] = None) -> Dict[str, Any]:
        """Token info from a token response; ``expiry`` is None for non-expiring tokens."""
        expires_in = payload.get("expires_in")
        expiry = None
        if expires_in:
            expiry = (
                datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=int(expires_in))
            ).isoformat()
        return {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token") or refresh_token,
            "token_uri": GitHubAuth.TOKEN_URL,
            "expiry": expiry,
        }

    def exchange_code_for_tokens(self, authorization_code: str) -> Dict[str, Any]:
        """Trade the callback's code for tokens, plus the account's login.

        Raises:
            ValueError: No code, or GitHub refused it.
        """
        if not authorization_code:
            raise ValueError("Authorization code is required")
        payload = self._token_request({"code": authorization_code, "redirect_uri": self.redirect_uri})
        token_info = self._tokens(payload)
        token_info["user_info"] = self._fetch_user(token_info["access_token"])
        return token_info

    def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """A new access token (and a new refresh token: GitHub rotates them).

        Raises:
            ValueError: The refresh token was refused (expired or revoked).
        """
        if not refresh_token:
            raise ValueError("Refresh token is required")
        payload = self._token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})
        return self._tokens(payload, refresh_token)

    def is_token_expired(self, token_info: Dict[str, Any]) -> bool:
        """Whether the access token is (about to be) expired.

        A token with no expiry never expires: the app has token expiry
        turned off.
        """
        if not token_info or not token_info.get("access_token"):
            return True
        expiry = token_info.get("expiry")
        if not expiry:
            return False
        try:
            expiry_dt = datetime.datetime.fromisoformat(expiry)
        except (TypeError, ValueError):
            return True
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=datetime.timezone.utc)
        return datetime.datetime.now(datetime.timezone.utc) >= expiry_dt - self.EXPIRY_MARGIN

    @staticmethod
    def _fetch_user(access_token: str) -> Dict[str, Any]:
        """``{login, name}`` of the signed-in account; empty when GitHub does not say."""
        try:
            response = requests.get(
                f"{API_URL}/user",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
                timeout=30,
            )
            response.raise_for_status()
            user = response.json()
        except Exception as exc:  # the sign-in still works; only its label is missing
            logger.warning("Could not read the GitHub account: %s", type(exc).__name__)
            return {}
        return {"login": user.get("login", ""), "name": user.get("name") or ""}
