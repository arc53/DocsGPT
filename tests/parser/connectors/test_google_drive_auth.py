"""Tests for GoogleDriveAuth."""

import datetime
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.GOOGLE_CLIENT_ID = "test-client-id"
    s.GOOGLE_CLIENT_SECRET = "test-client-secret"
    s.CONNECTOR_REDIRECT_BASE_URI = "https://redirect.example.com/callback"
    s.MONGO_DB_NAME = "test_db"
    return s


@pytest.fixture
def auth(mock_settings):
    with patch("application.parser.connectors.google_drive.auth.settings", mock_settings):
        from application.parser.connectors.google_drive.auth import GoogleDriveAuth
        return GoogleDriveAuth()


class TestGoogleDriveAuthInit:

    @pytest.mark.unit
    def test_init_sets_credentials(self, auth, mock_settings):
        assert auth.client_id == "test-client-id"
        assert auth.client_secret == "test-client-secret"
        assert auth.redirect_uri == "https://redirect.example.com/callback"

    @pytest.mark.unit
    def test_init_missing_client_id_raises(self, mock_settings):
        mock_settings.GOOGLE_CLIENT_ID = None
        with patch("application.parser.connectors.google_drive.auth.settings", mock_settings):
            from application.parser.connectors.google_drive.auth import GoogleDriveAuth
            with pytest.raises(ValueError, match="Google OAuth credentials not configured"):
                GoogleDriveAuth()

    @pytest.mark.unit
    def test_init_missing_client_secret_raises(self, mock_settings):
        mock_settings.GOOGLE_CLIENT_SECRET = None
        with patch("application.parser.connectors.google_drive.auth.settings", mock_settings):
            from application.parser.connectors.google_drive.auth import GoogleDriveAuth
            with pytest.raises(ValueError, match="Google OAuth credentials not configured"):
                GoogleDriveAuth()


class TestGetAuthorizationUrl:

    @pytest.mark.unit
    def test_returns_authorization_url(self, auth):
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/auth?state=s1", "s1")

        with patch("application.parser.connectors.google_drive.auth.Flow") as MockFlow:
            MockFlow.from_client_config.return_value = mock_flow
            url = auth.get_authorization_url(state="s1")

        assert url == "https://accounts.google.com/auth?state=s1"
        mock_flow.authorization_url.assert_called_once_with(
            access_type='offline',
            prompt='consent',
            include_granted_scopes='false',
            state="s1"
        )

    @pytest.mark.unit
    def test_raises_on_flow_error(self, auth):
        with patch("application.parser.connectors.google_drive.auth.Flow") as MockFlow:
            MockFlow.from_client_config.side_effect = Exception("flow error")
            with pytest.raises(Exception, match="flow error"):
                auth.get_authorization_url()


class TestExchangeCodeForTokens:

    @pytest.mark.unit
    def test_successful_exchange(self, auth):
        mock_creds = MagicMock()
        mock_creds.token = "access_tok"
        mock_creds.refresh_token = "refresh_tok"
        mock_creds.token_uri = "https://oauth2.googleapis.com/token"
        mock_creds.client_id = "test-client-id"
        mock_creds.client_secret = "test-client-secret"
        mock_creds.scopes = ["https://www.googleapis.com/auth/drive.file"]
        mock_creds.expiry = datetime.datetime(2025, 1, 1, 12, 0, 0)

        mock_flow = MagicMock()
        mock_flow.credentials = mock_creds

        with patch("application.parser.connectors.google_drive.auth.Flow") as MockFlow:
            MockFlow.from_client_config.return_value = mock_flow
            result = auth.exchange_code_for_tokens("auth_code_123")

        assert result["access_token"] == "access_tok"
        assert result["refresh_token"] == "refresh_tok"
        assert result["token_uri"] == "https://oauth2.googleapis.com/token"
        assert result["client_id"] == "test-client-id"
        assert result["client_secret"] == "test-client-secret"
        assert result["expiry"] == "2025-01-01T12:00:00"

    @pytest.mark.unit
    def test_empty_code_raises(self, auth):
        with pytest.raises(ValueError, match="Authorization code is required"):
            auth.exchange_code_for_tokens("")

    @pytest.mark.unit
    def test_no_access_token_raises(self, auth):
        mock_creds = MagicMock()
        mock_creds.token = None
        mock_creds.refresh_token = "rt"
        mock_flow = MagicMock()
        mock_flow.credentials = mock_creds

        with patch("application.parser.connectors.google_drive.auth.Flow") as MockFlow:
            MockFlow.from_client_config.return_value = mock_flow
            with pytest.raises(ValueError, match="did not return an access token"):
                auth.exchange_code_for_tokens("code")

    @pytest.mark.unit
    def test_no_refresh_token_raises(self, auth):
        mock_creds = MagicMock()
        mock_creds.token = "at"
        mock_creds.refresh_token = None
        mock_flow = MagicMock()
        mock_flow.credentials = mock_creds

        with patch("application.parser.connectors.google_drive.auth.Flow") as MockFlow:
            MockFlow.from_client_config.return_value = mock_flow
            with pytest.raises(ValueError, match="No refresh token received"):
                auth.exchange_code_for_tokens("code")

    @pytest.mark.unit
    def test_fills_in_missing_token_uri(self, auth):
        mock_creds = MagicMock()
        mock_creds.token = "at"
        mock_creds.refresh_token = "rt"
        mock_creds.token_uri = None
        mock_creds.client_id = None
        mock_creds.client_secret = None
        mock_creds.scopes = []
        mock_creds.expiry = None
        mock_flow = MagicMock()
        mock_flow.credentials = mock_creds

        with patch("application.parser.connectors.google_drive.auth.Flow") as MockFlow:
            MockFlow.from_client_config.return_value = mock_flow
            result = auth.exchange_code_for_tokens("code")

        assert result["token_uri"] == "https://oauth2.googleapis.com/token"
        assert result["client_id"] == "test-client-id"
        assert result["client_secret"] == "test-client-secret"


class TestRefreshAccessToken:

    @pytest.mark.unit
    def test_successful_refresh(self, auth):
        mock_request_cls = MagicMock()
        with patch("application.parser.connectors.google_drive.auth.Credentials") as MockCreds, \
             patch("google.auth.transport.requests.Request", mock_request_cls):
            mock_cred_instance = MagicMock()
            mock_cred_instance.token = "new_access"
            mock_cred_instance.token_uri = "https://oauth2.googleapis.com/token"
            mock_cred_instance.client_id = "cid"
            mock_cred_instance.client_secret = "cs"
            mock_cred_instance.scopes = []
            mock_cred_instance.expiry = datetime.datetime(2025, 6, 1, 0, 0, 0)
            MockCreds.return_value = mock_cred_instance

            result = auth.refresh_access_token("old_refresh")

        assert result["access_token"] == "new_access"
        assert result["refresh_token"] == "old_refresh"
        mock_cred_instance.refresh.assert_called_once()

    @pytest.mark.unit
    def test_empty_refresh_token_raises(self, auth):
        with pytest.raises(ValueError, match="Refresh token is required"):
            auth.refresh_access_token("")

    @pytest.mark.unit
    def test_refresh_failure_raises(self, auth):
        with patch("application.parser.connectors.google_drive.auth.Credentials") as MockCreds, \
             patch("google.auth.transport.requests.Request"):
            mock_cred_instance = MagicMock()
            mock_cred_instance.refresh.side_effect = Exception("refresh failed")
            MockCreds.return_value = mock_cred_instance

            with pytest.raises(Exception, match="refresh failed"):
                auth.refresh_access_token("rt")


class TestCreateCredentialsFromTokenInfo:

    @pytest.mark.unit
    def test_creates_credentials(self, auth, mock_settings):
        with patch("application.parser.connectors.google_drive.auth.Credentials") as MockCreds, \
             patch("application.parser.connectors.google_drive.auth.settings", mock_settings):
            mock_cred = MagicMock()
            mock_cred.token = "at"
            MockCreds.return_value = mock_cred

            creds = auth.create_credentials_from_token_info({
                "access_token": "at",
                "refresh_token": "rt",
                "scopes": ["scope1"],
            })
            assert creds.token == "at"

    @pytest.mark.unit
    def test_missing_access_token_raises(self, auth, mock_settings):
        with patch("application.parser.connectors.google_drive.auth.settings", mock_settings):
            with pytest.raises(ValueError, match="No access token found"):
                auth.create_credentials_from_token_info({})

    @pytest.mark.unit
    def test_credentials_without_valid_token_raises(self, auth, mock_settings):
        with patch("application.parser.connectors.google_drive.auth.Credentials") as MockCreds, \
             patch("application.parser.connectors.google_drive.auth.settings", mock_settings):
            mock_cred = MagicMock()
            mock_cred.token = None
            MockCreds.return_value = mock_cred

            with pytest.raises(ValueError, match="Credentials created without valid access token"):
                auth.create_credentials_from_token_info({"access_token": "at"})


class TestBuildDriveService:

    @pytest.mark.unit
    def test_builds_service(self, auth):
        mock_creds = MagicMock()
        mock_creds.token = "at"
        mock_creds.refresh_token = "rt"
        mock_creds.expired = False

        with patch("application.parser.connectors.google_drive.auth.build") as mock_build:
            mock_build.return_value = MagicMock()
            service = auth.build_drive_service(mock_creds)
            mock_build.assert_called_once_with('drive', 'v3', credentials=mock_creds)
            assert service is not None

    @pytest.mark.unit
    def test_no_credentials_raises(self, auth):
        with pytest.raises(ValueError, match="No credentials provided"):
            auth.build_drive_service(None)

    @pytest.mark.unit
    def test_no_token_no_refresh_raises(self, auth):
        mock_creds = MagicMock()
        mock_creds.token = None
        mock_creds.refresh_token = None
        with pytest.raises(ValueError, match="No access token or refresh token"):
            auth.build_drive_service(mock_creds)

    @pytest.mark.unit
    def test_expired_token_refreshes(self, auth):
        mock_creds = MagicMock()
        mock_creds.token = "at"
        mock_creds.refresh_token = "rt"
        mock_creds.expired = True

        with patch("application.parser.connectors.google_drive.auth.build") as mock_build, \
             patch("google.auth.transport.requests.Request"):
            mock_build.return_value = MagicMock()
            auth.build_drive_service(mock_creds)
            mock_creds.refresh.assert_called_once()

    @pytest.mark.unit
    def test_expired_no_refresh_token_raises(self, auth):
        mock_creds = MagicMock()
        mock_creds.token = "at"
        mock_creds.refresh_token = None
        mock_creds.expired = True
        with pytest.raises(ValueError, match="No access token or refresh token"):
            auth.build_drive_service(mock_creds)

    @pytest.mark.unit
    def test_refresh_failure_raises(self, auth):
        mock_creds = MagicMock()
        mock_creds.token = "at"
        mock_creds.refresh_token = "rt"
        mock_creds.expired = True

        with patch("google.auth.transport.requests.Request"):
            mock_creds.refresh.side_effect = Exception("Cannot refresh")
            with pytest.raises(ValueError, match="Failed to refresh credentials"):
                auth.build_drive_service(mock_creds)

    @pytest.mark.unit
    def test_http_error_raises(self, auth):
        from googleapiclient.errors import HttpError
        mock_creds = MagicMock()
        mock_creds.token = "at"
        mock_creds.refresh_token = "rt"
        mock_creds.expired = False

        mock_resp = MagicMock()
        mock_resp.status = 500

        with patch("application.parser.connectors.google_drive.auth.build") as mock_build:
            mock_build.side_effect = HttpError(mock_resp, b"error")
            with pytest.raises(ValueError, match="HTTP 500"):
                auth.build_drive_service(mock_creds)


class TestIsTokenExpired:

    @pytest.mark.unit
    def test_expired_token(self, auth):
        past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat()
        assert auth.is_token_expired({"expiry": past}) is True

    @pytest.mark.unit
    def test_valid_token(self, auth):
        future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).isoformat()
        assert auth.is_token_expired({"expiry": future}) is False

    @pytest.mark.unit
    def test_token_within_buffer(self, auth):
        almost_expired = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=30)).isoformat()
        assert auth.is_token_expired({"expiry": almost_expired}) is True

    @pytest.mark.unit
    def test_no_expiry_with_access_token(self, auth):
        assert auth.is_token_expired({"access_token": "at"}) is False

    @pytest.mark.unit
    def test_no_expiry_no_access_token(self, auth):
        assert auth.is_token_expired({}) is True

    @pytest.mark.unit
    def test_invalid_expiry_format_returns_true(self, auth):
        assert auth.is_token_expired({"expiry": "not-a-date"}) is True

    @pytest.mark.unit
    def test_none_expiry_with_access_token(self, auth):
        assert auth.is_token_expired({"expiry": None, "access_token": "at"}) is False


class TestGetTokenInfoFromSession:

    def _mock_mongo(self, mock_settings, find_one_return):
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = find_one_return
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        return {mock_settings.MONGO_DB_NAME: mock_db}

    @pytest.mark.unit
    def test_valid_session(self, auth, mock_settings):
        mock_client = self._mock_mongo(mock_settings, {
            "session_token": "st",
            "token_info": {"access_token": "at", "refresh_token": "rt"},
        })

        with patch("application.core.mongo_db.MongoDB.get_client", return_value=mock_client), \
             patch("application.core.settings.settings", mock_settings):
            result = auth.get_token_info_from_session("st")
            assert result["access_token"] == "at"
            assert result["token_uri"] == "https://oauth2.googleapis.com/token"

    @pytest.mark.unit
    def test_session_not_found_raises(self, auth, mock_settings):
        mock_client = self._mock_mongo(mock_settings, None)

        with patch("application.core.mongo_db.MongoDB.get_client", return_value=mock_client), \
             patch("application.core.settings.settings", mock_settings):
            with pytest.raises(ValueError, match="Failed to retrieve Google Drive token"):
                auth.get_token_info_from_session("bad_token")

    @pytest.mark.unit
    def test_session_missing_token_info_raises(self, auth, mock_settings):
        mock_client = self._mock_mongo(mock_settings, {"session_token": "st"})

        with patch("application.core.mongo_db.MongoDB.get_client", return_value=mock_client), \
             patch("application.core.settings.settings", mock_settings):
            with pytest.raises(ValueError, match="Failed to retrieve Google Drive token"):
                auth.get_token_info_from_session("st")

    @pytest.mark.unit
    def test_missing_required_fields_raises(self, auth, mock_settings):
        mock_client = self._mock_mongo(mock_settings, {
            "session_token": "st",
            "token_info": {"access_token": "at"},
        })

        with patch("application.core.mongo_db.MongoDB.get_client", return_value=mock_client), \
             patch("application.core.settings.settings", mock_settings):
            with pytest.raises(ValueError, match="Failed to retrieve Google Drive token"):
                auth.get_token_info_from_session("st")

    @pytest.mark.unit
    def test_empty_token_info_raises(self, auth, mock_settings):
        mock_client = self._mock_mongo(mock_settings, {
            "session_token": "st",
            "token_info": None,
        })

        with patch("application.core.mongo_db.MongoDB.get_client", return_value=mock_client), \
             patch("application.core.settings.settings", mock_settings):
            with pytest.raises(ValueError, match="Failed to retrieve Google Drive token"):
                auth.get_token_info_from_session("st")


class TestValidateCredentials:

    @pytest.mark.unit
    def test_valid_credentials(self, auth):
        mock_creds = MagicMock()
        mock_creds.token = "at"
        mock_creds.refresh_token = "rt"
        mock_creds.expired = False

        mock_service = MagicMock()
        mock_service.about.return_value.get.return_value.execute.return_value = {"user": {}}

        with patch.object(auth, 'build_drive_service', return_value=mock_service):
            assert auth.validate_credentials(mock_creds) is True

    @pytest.mark.unit
    def test_http_error_returns_false(self, auth):
        from googleapiclient.errors import HttpError
        mock_creds = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 401
        mock_service = MagicMock()
        mock_service.about.return_value.get.return_value.execute.side_effect = HttpError(mock_resp, b"unauth")

        with patch.object(auth, 'build_drive_service', return_value=mock_service):
            assert auth.validate_credentials(mock_creds) is False

    @pytest.mark.unit
    def test_general_error_returns_false(self, auth):
        mock_creds = MagicMock()
        with patch.object(auth, 'build_drive_service', side_effect=Exception("fail")):
            assert auth.validate_credentials(mock_creds) is False
