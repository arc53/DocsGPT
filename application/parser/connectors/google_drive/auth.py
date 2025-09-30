import logging
import datetime
from typing import Optional, Dict, Any

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from application.core.settings import settings
from application.parser.connectors.base import BaseConnectorAuth


class GoogleDriveAuth(BaseConnectorAuth):
    """
    Handles Google OAuth 2.0 authentication for Google Drive access.
    """
    
    SCOPES = [
        'https://www.googleapis.com/auth/drive.file'
    ]
    
    def __init__(self):
        self.client_id = settings.GOOGLE_CLIENT_ID
        self.client_secret = settings.GOOGLE_CLIENT_SECRET
        self.redirect_uri = f"{settings.CONNECTOR_REDIRECT_BASE_URI}"
        
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
                scopes=self.SCOPES
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
                scopes=self.SCOPES
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
                'scopes': credentials.scopes,
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
    
    def create_credentials_from_token_info(self, token_info: Dict[str, Any]) -> Credentials:
        from application.core.settings import settings

        access_token = token_info.get('access_token')
        if not access_token:
            raise ValueError("No access token found in token_info")

        credentials = Credentials(
            token=access_token,
            refresh_token=token_info.get('refresh_token'),
            token_uri= 'https://oauth2.googleapis.com/token',
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            scopes=token_info.get('scopes', ['https://www.googleapis.com/auth/drive.readonly'])
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
    
    def get_token_info_from_session(self, session_token: str) -> Dict[str, Any]:
        try:
            from application.core.mongo_db import MongoDB
            from application.core.settings import settings

            mongo = MongoDB.get_client()
            db = mongo[settings.MONGO_DB_NAME]
            
            sessions_collection = db["connector_sessions"]
            session = sessions_collection.find_one({"session_token": session_token})   
            if not session:
                raise ValueError(f"Invalid session token: {session_token}")

            if "token_info" not in session:
                raise ValueError("Session missing token information")

            token_info = session["token_info"]
            if not token_info:
                raise ValueError("Invalid token information")

            required_fields = ["access_token", "refresh_token"]
            missing_fields = [field for field in required_fields if field not in token_info or not token_info.get(field)]
            if missing_fields:
                raise ValueError(f"Missing required token fields: {missing_fields}")

            if 'client_id' not in token_info:
                token_info['client_id'] = settings.GOOGLE_CLIENT_ID
            if 'client_secret' not in token_info:
                token_info['client_secret'] = settings.GOOGLE_CLIENT_SECRET
            if 'token_uri' not in token_info:
                token_info['token_uri'] = 'https://oauth2.googleapis.com/token'

            return token_info

        except Exception as e:
            raise ValueError(f"Failed to retrieve Google Drive token information: {str(e)}")

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
