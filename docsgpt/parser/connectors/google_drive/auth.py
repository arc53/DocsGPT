import json
import logging
import datetime
from typing import Optional, Dict, Any, List

import requests
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from docsgpt.core.settings import settings
from docsgpt.parser.connectors.base import BaseConnectorAuth


DRIVE_FILE_SCOPE = 'https://www.googleapis.com/auth/drive.file'
DRIVE_READONLY_SCOPE = 'https://www.googleapis.com/auth/drive.readonly'
# Scopes under which a user's own sign-in can list a folder's contents. With
# drive.file it sees only the items picked in Google's picker, not what is in them.
_WHOLE_DRIVE_SCOPES = {DRIVE_READONLY_SCOPE, 'https://www.googleapis.com/auth/drive'}
_TOKENINFO_URL = 'https://oauth2.googleapis.com/tokeninfo'


class GoogleDriveAuth(BaseConnectorAuth):
    """
    Handles Google OAuth 2.0 authentication for Google Drive access.
    """

    def __init__(self):
        self.client_id = settings.GOOGLE_CLIENT_ID
        self.client_secret = settings.GOOGLE_CLIENT_SECRET
        self.redirect_uri = f"{settings.CONNECTOR_REDIRECT_BASE_URI}"
        self.scopes = [DRIVE_READONLY_SCOPE if settings.GOOGLE_DRIVE_ACCESS == 'readonly' else DRIVE_FILE_SCOPE]
        self._service_account_key = settings.GOOGLE_SERVICE_ACCOUNT_KEY

        if not self.client_id or not self.client_secret:
            raise ValueError("Google OAuth credentials not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in settings.")



    def get_authorization_url(self, state: Optional[str] = None) -> str:
        try:
            flow = Flow.from_client_config(
                {
                    "web": {
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": [self.redirect_uri]
                    }
                },
                scopes=self.scopes,
                # Flow is rebuilt at exchange time, so an auto-generated
                # code_verifier wouldn't survive; confidential client doesn't
                # need PKCE anyway.
                autogenerate_code_verifier=False,
            )
            flow.redirect_uri = self.redirect_uri

            authorization_url, _ = flow.authorization_url(
                access_type='offline',
                prompt='consent',
                include_granted_scopes='false',
                state=state
            )

            return authorization_url

        except Exception as e:
            logging.error(f"Error generating authorization URL: {e}")
            raise

    def exchange_code_for_tokens(self, authorization_code: str) -> Dict[str, Any]:
        try:
            if not authorization_code:
                raise ValueError("Authorization code is required")

            flow = Flow.from_client_config(
                {
                    "web": {
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": [self.redirect_uri]
                    }
                },
                scopes=self.scopes,
                autogenerate_code_verifier=False,
            )
            flow.redirect_uri = self.redirect_uri

            flow.fetch_token(code=authorization_code)

            credentials = flow.credentials

            if not credentials.refresh_token:
                logging.warning("OAuth flow did not return a refresh_token.")
            if not credentials.token:
                raise ValueError("OAuth flow did not return an access token")

            if not credentials.token_uri:
                credentials.token_uri = "https://oauth2.googleapis.com/token"

            if not credentials.client_id:
                credentials.client_id = self.client_id

            if not credentials.client_secret:
                credentials.client_secret = self.client_secret

            if not credentials.refresh_token:
                raise ValueError(
                    "No refresh token received. This typically happens when offline access wasn't granted. "
                )

            return {
                'access_token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'token_uri': credentials.token_uri,
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
                'scopes': getattr(credentials, 'granted_scopes', None) or credentials.scopes,
                'expiry': credentials.expiry.isoformat() if credentials.expiry else None
            }

        except Exception as e:
            logging.error(f"Error exchanging code for tokens: {e}")
            raise
    
    def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        try:
            if not refresh_token:
                raise ValueError("Refresh token is required")

            credentials = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret
            )

            from google.auth.transport.requests import Request
            credentials.refresh(Request())

            return {
                'access_token': credentials.token,
                'refresh_token': refresh_token,
                'token_uri': credentials.token_uri,
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
                'scopes': credentials.scopes,
                'expiry': credentials.expiry.isoformat() if credentials.expiry else None
            }
        except Exception as e:
            logging.error(f"Error refreshing access token: {e}", exc_info=True)
            raise
    
    def sanitize_token_info(self, token_info: Dict[str, Any], **extra_fields) -> Dict[str, Any]:
        """The fields safe to persist, with the scopes Google granted.

        The scopes say whether the sign-in can read a picked folder's
        contents itself (``drive.readonly``) or only the picked items
        (``drive.file``).
        """
        return super().sanitize_token_info(
            token_info, scopes=_scope_list(token_info.get('scopes')), **extra_fields
        )

    def reads_whole_drive(self, token_info: Dict[str, Any]) -> bool:
        """Whether this sign-in can list what is inside a folder.

        A sign-in saved before its scopes were stored is looked up at
        Google. When that fails it counts as per-file access, so a folder is
        never read with more than the user granted.

        Args:
            token_info: The connection's stored token info.
        """
        scopes = _scope_list(token_info.get('scopes'))
        if scopes is None:
            scopes = self._granted_scopes(token_info.get('access_token'))
        return bool(set(scopes or ()) & _WHOLE_DRIVE_SCOPES)

    def _granted_scopes(self, access_token: Optional[str]) -> Optional[List[str]]:
        """The scopes Google says ``access_token`` carries; None when it cannot tell."""
        if not access_token:
            return None
        try:
            # In the body, not the URL, so the token never lands in a logged URL.
            response = requests.post(_TOKENINFO_URL, data={'access_token': access_token}, timeout=10)
            if response.status_code != 200:
                return None
            return _scope_list(response.json().get('scope'))
        except Exception as e:
            logging.warning(f"Could not look up the scopes of a Google Drive sign-in: {e}")
            return None

    def _service_account_info(self) -> Optional[Dict[str, Any]]:
        """The service account key from ``GOOGLE_SERVICE_ACCOUNT_KEY``: inline JSON or a file path."""
        key = (self._service_account_key or '').strip()
        if not key:
            return None
        try:
            if key.startswith('{'):
                return json.loads(key)
            with open(key, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError) as e:
            raise ValueError(f"GOOGLE_SERVICE_ACCOUNT_KEY is not a readable service account key: {e}") from e

    def service_account_email(self) -> Optional[str]:
        """The address users share a folder with; None when no service account is set."""
        info = self._service_account_info()
        return info.get('client_email') if info else None

    def build_service_account_service(self):
        """A Drive client signed in as the service account; None when none is set.

        It reads only what was shared with the service account, and only
        ever with read access.
        """
        info = self._service_account_info()
        if info is None:
            return None
        credentials = service_account.Credentials.from_service_account_info(info, scopes=[DRIVE_READONLY_SCOPE])
        return build('drive', 'v3', credentials=credentials, cache_discovery=False)

    def picker_options(self, token_info: Dict[str, Any]) -> Dict[str, Any]:
        """How a browser picker treats folders for this sign-in.

        ``folders`` is ``account`` when the sign-in reads folders itself,
        ``service_account`` when a picked folder is read through the service
        account (``share_with`` is its address) and ``off`` when folders
        cannot be read at all.
        """
        if self.reads_whole_drive(token_info):
            return {'folders': 'account'}
        try:
            email = self.service_account_email()
        except ValueError as e:
            logging.warning(f"Google Drive folders cannot be picked: {e}")
            email = None
        if email:
            return {'folders': 'service_account', 'share_with': email}
        return {'folders': 'off'}

    def create_credentials_from_token_info(self, token_info: Dict[str, Any]) -> Credentials:
        from docsgpt.core.settings import settings

        access_token = token_info.get('access_token')
        if not access_token:
            raise ValueError("No access token found in token_info")

        credentials = Credentials(
            token=access_token,
            refresh_token=token_info.get('refresh_token'),
            token_uri= 'https://oauth2.googleapis.com/token',
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            scopes=_scope_list(token_info.get('scopes')) or self.scopes
        )

        if not credentials.token:
            raise ValueError("Credentials created without valid access token")

        return credentials
    
    def build_drive_service(self, credentials: Credentials):
        try:
            if not credentials:
                raise ValueError("No credentials provided")

            if not credentials.token and not credentials.refresh_token:
                raise ValueError("No access token or refresh token available. User must re-authorize with offline access.")

            needs_refresh = credentials.expired or not credentials.token
            if needs_refresh:
                if credentials.refresh_token:
                    try:
                        from google.auth.transport.requests import Request
                        credentials.refresh(Request())
                    except Exception as refresh_error:
                        raise ValueError(f"Failed to refresh credentials: {refresh_error}")
                else:
                    raise ValueError("No access token or refresh token available. User must re-authorize with offline access.")

            return build('drive', 'v3', credentials=credentials)

        except HttpError as e:
            raise ValueError(f"Failed to build Google Drive service: HTTP {e.resp.status}")
        except Exception as e:
            raise ValueError(f"Failed to build Google Drive service: {str(e)}")
        
    def is_token_expired(self, token_info):
        if 'expiry' in token_info and token_info['expiry']:
            try:
                from dateutil import parser
                # Google Drive provides timezone-aware ISO8601 dates
                expiry_dt = parser.parse(token_info['expiry'])
                current_time = datetime.datetime.now(datetime.timezone.utc)
                return current_time >= expiry_dt - datetime.timedelta(seconds=60)
            except Exception:
                return True

        if 'access_token' in token_info and token_info['access_token']:
            return False

        return True
    
    def validate_credentials(self, credentials: Credentials) -> bool:
        """
        Validate Google Drive credentials by making a test API call.

        Args:
            credentials: Google credentials object

        Returns:
            True if credentials are valid, False otherwise
        """
        try:
            service = self.build_drive_service(credentials)
            service.about().get(fields="user").execute()
            return True

        except HttpError as e:
            logging.error(f"HTTP error validating credentials: {e}")
            return False
        except Exception as e:
            logging.error(f"Error validating credentials: {e}")
            return False


def _scope_list(scopes: Any) -> Optional[List[str]]:
    """Scopes as a list, from Google's space-separated string or a list; None when absent."""
    if not scopes:
        return None
    if isinstance(scopes, str):
        return scopes.split()
    return [str(scope) for scope in scopes]
