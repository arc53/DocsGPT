import logging
import datetime
from typing import Optional, Dict, Any

from msal import ConfidentialClientApplication

from application.core.settings import settings
from application.parser.connectors.base import BaseConnectorAuth


class SharePointAuth(BaseConnectorAuth):
    """
    Handles Microsoft OAuth 2.0 authentication for SharePoint/OneDrive.

    Note: Files.Read scope allows access to files the user has granted access to,
    similar to Google Drive's drive.file scope.
    """

    SCOPES = [
        "Files.Read",
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

        logging.info(f"SharePointAuth initialized with: client_id={self.client_id[:8]}, tenant_id={self.tenant_id}, redirect_uri={self.redirect_uri}, authority={self.authority}")

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
        logging.info(f"Exchanging authorization code for token with scopes: {self.SCOPES}")
        logging.info(f"Redirect URI: {self.redirect_uri}")
        
        result = self.auth_app.acquire_token_by_authorization_code(
            code=authorization_code, 
            scopes=self.SCOPES, 
            redirect_uri=self.redirect_uri
        )

        if "error" in result:
            error_msg = f"Error acquiring token: {result.get('error_description')}"
            logging.error(f"{error_msg} - Full result: {result}")
            raise ValueError(error_msg)

        logging.info(f"Token acquired successfully")
        return self.map_token_response(result)

    def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        logging.info(f"Refreshing access token")
        result = self.auth_app.acquire_token_by_refresh_token(refresh_token=refresh_token, scopes=self.SCOPES)

        if "error" in result:
            logging.error(f"Error refreshing token: {result.get('error_description')} - Full result: {result}")
            raise ValueError(f"Error acquiring token: {result.get('error_description')}")

        logging.info(f"Token refreshed successfully")
        return self.map_token_response(result)

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
                token_info['client_id'] = settings.MICROSOFT_CLIENT_ID
            if 'tenant_id' not in token_info:
                token_info['tenant_id'] = settings.MICROSOFT_TENANT_ID
            if 'client_secret' not in token_info:
                token_info['client_secret'] = settings.MICROSOFT_CLIENT_SECRET
            if 'token_uri' not in token_info:
                token_info['token_uri'] = f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/token"

            logging.info(f"Retrieved token from session. Expiry: {token_info.get('expiry')}")
            return token_info

        except Exception as e:
            raise ValueError(f"Failed to retrieve SharePoint token information: {str(e)}")

    def is_token_expired(self, token_info: Dict[str, Any]) -> bool:
        if not token_info:
            return True

        expiry_timestamp = token_info.get("expiry")

        if expiry_timestamp is None:
            logging.warning("Token expiry is None, treating as expired")
            return True

        current_timestamp = int(datetime.datetime.now().timestamp())
        expires_in = expiry_timestamp - current_timestamp
        
        if expires_in < 60:
            logging.info(f"Token expires in {expires_in} seconds, treating as expired")
            return True
        
        logging.debug(f"Token not expired. Expires in {expires_in} seconds")
        return False

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
