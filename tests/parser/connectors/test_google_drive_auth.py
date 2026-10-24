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
    s.GOOGLE_DRIVE_ACCESS = "file"
    s.GOOGLE_SERVICE_ACCOUNT_KEY = None
    return s


@pytest.fixture
def auth(mock_settings):
    with patch("docsgpt.parser.connectors.google_drive.auth.settings", mock_settings):
        from docsgpt.parser.connectors.google_drive.auth import GoogleDriveAuth
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
        with patch("docsgpt.parser.connectors.google_drive.auth.settings", mock_settings):
            from docsgpt.parser.connectors.google_drive.auth import GoogleDriveAuth
            with pytest.raises(ValueError, match="Google OAuth credentials not configured"):
                GoogleDriveAuth()

    @pytest.mark.unit
    def test_init_missing_client_secret_raises(self, mock_settings):
        mock_settings.GOOGLE_CLIENT_SECRET = None
        with patch("docsgpt.parser.connectors.google_drive.auth.settings", mock_settings):
            from docsgpt.parser.connectors.google_drive.auth import GoogleDriveAuth
            with pytest.raises(ValueError, match="Google OAuth credentials not configured"):
                GoogleDriveAuth()


class TestGetAuthorizationUrl:

    @pytest.mark.unit
    def test_returns_authorization_url(self, auth):
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/auth?state=s1", "s1")

        with patch("docsgpt.parser.connectors.google_drive.auth.Flow") as MockFlow:
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
        with patch("docsgpt.parser.connectors.google_drive.auth.Flow") as MockFlow:
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

        with patch("docsgpt.parser.connectors.google_drive.auth.Flow") as MockFlow:
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

        with patch("docsgpt.parser.connectors.google_drive.auth.Flow") as MockFlow:
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

        with patch("docsgpt.parser.connectors.google_drive.auth.Flow") as MockFlow:
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

        with patch("docsgpt.parser.connectors.google_drive.auth.Flow") as MockFlow:
            MockFlow.from_client_config.return_value = mock_flow
            result = auth.exchange_code_for_tokens("code")

        assert result["token_uri"] == "https://oauth2.googleapis.com/token"
        assert result["client_id"] == "test-client-id"
        assert result["client_secret"] == "test-client-secret"


class TestRefreshAccessToken:

    @pytest.mark.unit
    def test_successful_refresh(self, auth):
        mock_request_cls = MagicMock()
        with patch("docsgpt.parser.connectors.google_drive.auth.Credentials") as MockCreds, \
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
        with patch("docsgpt.parser.connectors.google_drive.auth.Credentials") as MockCreds, \
             patch("google.auth.transport.requests.Request"):
            mock_cred_instance = MagicMock()
            mock_cred_instance.refresh.side_effect = Exception("refresh failed")
            MockCreds.return_value = mock_cred_instance

            with pytest.raises(Exception, match="refresh failed"):
                auth.refresh_access_token("rt")


class TestCreateCredentialsFromTokenInfo:

    @pytest.mark.unit
    def test_creates_credentials(self, auth, mock_settings):
        with patch("docsgpt.parser.connectors.google_drive.auth.Credentials") as MockCreds, \
             patch("docsgpt.parser.connectors.google_drive.auth.settings", mock_settings):
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
        with patch("docsgpt.parser.connectors.google_drive.auth.settings", mock_settings):
            with pytest.raises(ValueError, match="No access token found"):
                auth.create_credentials_from_token_info({})

    @pytest.mark.unit
    def test_credentials_without_valid_token_raises(self, auth, mock_settings):
        with patch("docsgpt.parser.connectors.google_drive.auth.Credentials") as MockCreds, \
             patch("docsgpt.parser.connectors.google_drive.auth.settings", mock_settings):
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

        with patch("docsgpt.parser.connectors.google_drive.auth.build") as mock_build:
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

        with patch("docsgpt.parser.connectors.google_drive.auth.build") as mock_build, \
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

        with patch("docsgpt.parser.connectors.google_drive.auth.build") as mock_build:
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


class _FakeRepo:
    """Fake ConnectorSessionsRepository returning a preset session dict."""

    _session = None

    def __init__(self, conn):
        self.conn = conn

    def get_by_session_token(self, session_token):
        return self._session


class _FakeReadonlyCtx:
    """Fake db_readonly context manager yielding a dummy connection."""

    def __enter__(self):
        return MagicMock()

    def __exit__(self, exc_type, exc, tb):
        return False


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


DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"
DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
SA_INFO = {
    "type": "service_account",
    "client_email": "reader@project.iam.gserviceaccount.com",
    "private_key": "-----BEGIN PRIVATE KEY-----\nkey\n-----END PRIVATE KEY-----\n",
    "token_uri": "https://oauth2.googleapis.com/token",
}


def _auth_with(mock_settings, **overrides):
    for name, value in overrides.items():
        setattr(mock_settings, name, value)
    with patch("docsgpt.parser.connectors.google_drive.auth.settings", mock_settings):
        from docsgpt.parser.connectors.google_drive.auth import GoogleDriveAuth
        return GoogleDriveAuth()


class TestRequestedScope:

    @pytest.mark.unit
    @pytest.mark.parametrize("access, scope", [("file", DRIVE_FILE), ("readonly", DRIVE_READONLY)])
    def test_scope_follows_the_access_setting(self, mock_settings, access, scope):
        auth = _auth_with(mock_settings, GOOGLE_DRIVE_ACCESS=access)
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/auth", "s")
        with patch("docsgpt.parser.connectors.google_drive.auth.Flow") as MockFlow:
            MockFlow.from_client_config.return_value = mock_flow
            auth.get_authorization_url(state="s")
        assert MockFlow.from_client_config.call_args.kwargs["scopes"] == [scope]

    @pytest.mark.unit
    def test_exchange_returns_the_granted_scopes(self, auth):
        mock_creds = MagicMock()
        mock_creds.token = "at"
        mock_creds.refresh_token = "rt"
        mock_creds.scopes = [DRIVE_FILE]
        mock_creds.granted_scopes = [DRIVE_FILE, "openid"]
        mock_creds.expiry = None
        mock_flow = MagicMock()
        mock_flow.credentials = mock_creds
        with patch("docsgpt.parser.connectors.google_drive.auth.Flow") as MockFlow:
            MockFlow.from_client_config.return_value = mock_flow
            result = auth.exchange_code_for_tokens("code")
        assert result["scopes"] == [DRIVE_FILE, "openid"]

    @pytest.mark.unit
    @pytest.mark.parametrize("scopes, expected", [
        ([DRIVE_FILE], [DRIVE_FILE]),
        (f"{DRIVE_FILE} openid", [DRIVE_FILE, "openid"]),
        (None, None),
    ])
    def test_sanitized_token_info_keeps_the_scopes(self, auth, scopes, expected):
        sanitized = auth.sanitize_token_info({"access_token": "at", "client_secret": "s", "scopes": scopes})
        assert sanitized["scopes"] == expected
        assert "client_secret" not in sanitized


class TestReadsWholeDrive:

    @pytest.mark.unit
    @pytest.mark.parametrize("scopes, expected", [
        ([DRIVE_READONLY], True),
        (["https://www.googleapis.com/auth/drive"], True),
        ([DRIVE_FILE], False),
        ([DRIVE_FILE, "https://www.googleapis.com/auth/drive.metadata.readonly"], False),
    ])
    def test_from_stored_scopes(self, auth, scopes, expected):
        with patch("docsgpt.parser.connectors.google_drive.auth.requests") as mock_requests:
            assert auth.reads_whole_drive({"access_token": "at", "scopes": scopes}) is expected
        mock_requests.post.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.parametrize("granted, expected", [(DRIVE_READONLY, True), (DRIVE_FILE, False)])
    def test_asks_google_when_scopes_were_not_stored(self, auth, granted, expected):
        with patch("docsgpt.parser.connectors.google_drive.auth.requests") as mock_requests:
            mock_requests.post.return_value.status_code = 200
            mock_requests.post.return_value.json.return_value = {"scope": f"{granted} openid"}
            assert auth.reads_whole_drive({"access_token": "at"}) is expected
        assert mock_requests.post.call_args.kwargs["data"] == {"access_token": "at"}

    @pytest.mark.unit
    def test_unknown_scopes_read_as_per_file_access(self, auth):
        with patch("docsgpt.parser.connectors.google_drive.auth.requests") as mock_requests:
            mock_requests.post.side_effect = Exception("network down")
            assert auth.reads_whole_drive({"access_token": "at"}) is False


class TestServiceAccount:

    @pytest.mark.unit
    def test_not_configured(self, auth):
        assert auth.service_account_email() is None
        assert auth.build_service_account_service() is None

    @pytest.mark.unit
    def test_key_given_as_json(self, mock_settings):
        import json
        auth = _auth_with(mock_settings, GOOGLE_SERVICE_ACCOUNT_KEY=json.dumps(SA_INFO))
        assert auth.service_account_email() == "reader@project.iam.gserviceaccount.com"
        with patch("docsgpt.parser.connectors.google_drive.auth.service_account") as mock_sa, \
             patch("docsgpt.parser.connectors.google_drive.auth.build") as mock_build:
            service = auth.build_service_account_service()
        mock_sa.Credentials.from_service_account_info.assert_called_once_with(SA_INFO, scopes=[DRIVE_READONLY])
        mock_build.assert_called_once_with(
            "drive", "v3", credentials=mock_sa.Credentials.from_service_account_info.return_value,
            cache_discovery=False,
        )
        assert service is mock_build.return_value

    @pytest.mark.unit
    def test_key_given_as_a_file_path(self, mock_settings, tmp_path):
        import json
        key_file = tmp_path / "key.json"
        key_file.write_text(json.dumps(SA_INFO))
        auth = _auth_with(mock_settings, GOOGLE_SERVICE_ACCOUNT_KEY=str(key_file))
        assert auth.service_account_email() == "reader@project.iam.gserviceaccount.com"

    @pytest.mark.unit
    def test_unreadable_key_raises(self, mock_settings):
        auth = _auth_with(mock_settings, GOOGLE_SERVICE_ACCOUNT_KEY="/missing/key.json")
        with pytest.raises(ValueError, match="GOOGLE_SERVICE_ACCOUNT_KEY"):
            auth.service_account_email()


class TestPickerOptions:

    @pytest.mark.unit
    def test_whole_drive_sign_in_picks_folders_itself(self, auth):
        options = auth.picker_options({"access_token": "at", "scopes": [DRIVE_READONLY]})
        assert options == {"folders": "account"}

    @pytest.mark.unit
    def test_per_file_sign_in_shares_folders_with_the_service_account(self, mock_settings):
        import json
        auth = _auth_with(mock_settings, GOOGLE_SERVICE_ACCOUNT_KEY=json.dumps(SA_INFO))
        options = auth.picker_options({"access_token": "at", "scopes": [DRIVE_FILE]})
        assert options == {
            "folders": "service_account",
            "share_with": "reader@project.iam.gserviceaccount.com",
        }

    @pytest.mark.unit
    def test_per_file_sign_in_without_a_service_account_picks_files_only(self, auth):
        options = auth.picker_options({"access_token": "at", "scopes": [DRIVE_FILE]})
        assert options == {"folders": "off"}

    @pytest.mark.unit
    def test_unreadable_service_account_key_picks_files_only(self, mock_settings):
        auth = _auth_with(mock_settings, GOOGLE_SERVICE_ACCOUNT_KEY="/missing/key.json")
        options = auth.picker_options({"access_token": "at", "scopes": [DRIVE_FILE]})
        assert options == {"folders": "off"}
