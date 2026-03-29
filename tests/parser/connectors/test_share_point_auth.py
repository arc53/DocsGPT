"""Tests for SharePointAuth."""

import datetime
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.MICROSOFT_CLIENT_ID = "ms-client-id"
    s.MICROSOFT_CLIENT_SECRET = "ms-client-secret"
    s.MICROSOFT_TENANT_ID = "tenant-id-123"
    s.CONNECTOR_REDIRECT_BASE_URI = "https://redirect.example.com/callback"
    s.MONGO_DB_NAME = "test_db"
    # Delete MICROSOFT_AUTHORITY so getattr falls back to default
    del s.MICROSOFT_AUTHORITY
    return s


@pytest.fixture
def mock_msal():
    with patch("application.parser.connectors.share_point.auth.ConfidentialClientApplication") as MockMSAL:
        mock_app = MagicMock()
        MockMSAL.return_value = mock_app
        yield mock_app


@pytest.fixture
def auth(mock_settings, mock_msal):
    with patch("application.parser.connectors.share_point.auth.settings", mock_settings):
        from application.parser.connectors.share_point.auth import SharePointAuth
        return SharePointAuth()


class TestSharePointAuthInit:

    @pytest.mark.unit
    def test_init_sets_attributes(self, auth, mock_settings):
        assert auth.client_id == "ms-client-id"
        assert auth.client_secret == "ms-client-secret"
        assert auth.redirect_uri == "https://redirect.example.com/callback"
        assert auth.tenant_id == "tenant-id-123"

    @pytest.mark.unit
    def test_missing_client_id_raises(self, mock_settings):
        mock_settings.MICROSOFT_CLIENT_ID = None
        with patch("application.parser.connectors.share_point.auth.settings", mock_settings), \
             patch("application.parser.connectors.share_point.auth.ConfidentialClientApplication"):
            from application.parser.connectors.share_point.auth import SharePointAuth
            with pytest.raises(ValueError, match="MICROSOFT_CLIENT_ID"):
                SharePointAuth()

    @pytest.mark.unit
    def test_missing_client_secret_raises(self, mock_settings):
        mock_settings.MICROSOFT_CLIENT_SECRET = None
        with patch("application.parser.connectors.share_point.auth.settings", mock_settings), \
             patch("application.parser.connectors.share_point.auth.ConfidentialClientApplication"):
            from application.parser.connectors.share_point.auth import SharePointAuth
            with pytest.raises(ValueError, match="MICROSOFT_CLIENT_SECRET"):
                SharePointAuth()

    @pytest.mark.unit
    def test_default_authority(self, auth):
        assert "login.microsoftonline.com" in auth.authority
        assert "tenant-id-123" in auth.authority


class TestGetAuthorizationUrl:

    @pytest.mark.unit
    def test_returns_url(self, auth, mock_msal):
        mock_msal.get_authorization_request_url.return_value = "https://login.microsoftonline.com/auth?state=s1"
        url = auth.get_authorization_url(state="s1")
        assert url == "https://login.microsoftonline.com/auth?state=s1"
        mock_msal.get_authorization_request_url.assert_called_once()


class TestExchangeCodeForTokens:

    @pytest.mark.unit
    def test_successful_exchange(self, auth, mock_msal):
        mock_msal.acquire_token_by_authorization_code.return_value = {
            "access_token": "at",
            "refresh_token": "rt",
            "scope": ["Files.Read"],
            "id_token_claims": {
                "iss": "https://login.microsoftonline.com/tid/v2.0",
                "exp": 1700000000,
                "tid": "work-tenant-id",
                "name": "Test User",
                "preferred_username": "test@example.com",
            },
        }
        result = auth.exchange_code_for_tokens("auth_code")
        assert result["access_token"] == "at"
        assert result["refresh_token"] == "rt"
        assert result["user_info"]["name"] == "Test User"
        assert result["user_info"]["email"] == "test@example.com"
        assert result["allows_shared_content"] is True

    @pytest.mark.unit
    def test_error_in_response_raises(self, auth, mock_msal):
        mock_msal.acquire_token_by_authorization_code.return_value = {
            "error": "invalid_grant",
            "error_description": "Code expired",
        }
        with pytest.raises(ValueError, match="Code expired"):
            auth.exchange_code_for_tokens("bad_code")


class TestRefreshAccessToken:

    @pytest.mark.unit
    def test_successful_refresh(self, auth, mock_msal):
        mock_msal.acquire_token_by_refresh_token.return_value = {
            "access_token": "new_at",
            "refresh_token": "new_rt",
            "scope": ["Files.Read"],
            "id_token_claims": {
                "iss": "https://issuer",
                "exp": 1700001000,
                "tid": "work-tid",
                "name": "User",
                "preferred_username": "u@example.com",
            },
        }
        result = auth.refresh_access_token("old_rt")
        assert result["access_token"] == "new_at"
        assert result["refresh_token"] == "new_rt"

    @pytest.mark.unit
    def test_error_in_response_raises(self, auth, mock_msal):
        mock_msal.acquire_token_by_refresh_token.return_value = {
            "error": "invalid_grant",
            "error_description": "Token revoked",
        }
        with pytest.raises(ValueError, match="Token revoked"):
            auth.refresh_access_token("bad_rt")


class TestIsTokenExpired:

    @pytest.mark.unit
    def test_expired_token(self, auth):
        past = int((datetime.datetime.now() - datetime.timedelta(hours=1)).timestamp())
        assert auth.is_token_expired({"expiry": past}) is True

    @pytest.mark.unit
    def test_valid_token(self, auth):
        future = int((datetime.datetime.now() + datetime.timedelta(hours=1)).timestamp())
        assert auth.is_token_expired({"expiry": future}) is False

    @pytest.mark.unit
    def test_within_buffer(self, auth):
        almost_expired = int((datetime.datetime.now() + datetime.timedelta(seconds=30)).timestamp())
        assert auth.is_token_expired({"expiry": almost_expired}) is True

    @pytest.mark.unit
    def test_none_token_info(self, auth):
        assert auth.is_token_expired(None) is True

    @pytest.mark.unit
    def test_missing_expiry(self, auth):
        assert auth.is_token_expired({}) is True

    @pytest.mark.unit
    def test_none_expiry(self, auth):
        assert auth.is_token_expired({"expiry": None}) is True


class TestSanitizeTokenInfo:

    @pytest.mark.unit
    def test_includes_allows_shared_content(self, auth):
        token_info = {
            "access_token": "at",
            "refresh_token": "rt",
            "token_uri": "https://uri",
            "expiry": 123,
            "allows_shared_content": True,
        }
        result = auth.sanitize_token_info(token_info)
        assert result["allows_shared_content"] is True
        assert result["access_token"] == "at"

    @pytest.mark.unit
    def test_defaults_allows_shared_content_to_false(self, auth):
        token_info = {
            "access_token": "at",
            "refresh_token": "rt",
            "token_uri": "https://uri",
            "expiry": 123,
        }
        result = auth.sanitize_token_info(token_info)
        assert result["allows_shared_content"] is False

    @pytest.mark.unit
    def test_with_extra_fields(self, auth):
        token_info = {
            "access_token": "at",
            "refresh_token": "rt",
            "token_uri": "https://uri",
            "expiry": 123,
            "allows_shared_content": True,
        }
        result = auth.sanitize_token_info(token_info, custom="val")
        assert result["custom"] == "val"


class TestAllowsSharedContent:

    @pytest.mark.unit
    def test_work_account_returns_true(self, auth):
        claims = {"tid": "some-work-tenant-id"}
        assert auth._allows_shared_content(claims) is True

    @pytest.mark.unit
    def test_personal_account_returns_false(self, auth):
        claims = {"tid": "9188040d-6c67-4c5b-b112-36a304b66dad"}
        assert auth._allows_shared_content(claims) is False

    @pytest.mark.unit
    def test_empty_tid_returns_false(self, auth):
        assert auth._allows_shared_content({"tid": ""}) is False
        assert auth._allows_shared_content({}) is False


class TestMapTokenResponse:

    @pytest.mark.unit
    def test_maps_all_fields(self, auth):
        result = {
            "access_token": "at",
            "refresh_token": "rt",
            "scope": ["Files.Read"],
            "id_token_claims": {
                "iss": "https://issuer",
                "exp": 1700000000,
                "tid": "work-tid",
                "name": "User Name",
                "preferred_username": "user@example.com",
            },
        }
        mapped = auth.map_token_response(result)
        assert mapped["access_token"] == "at"
        assert mapped["refresh_token"] == "rt"
        assert mapped["token_uri"] == "https://issuer"
        assert mapped["scopes"] == ["Files.Read"]
        assert mapped["expiry"] == 1700000000
        assert mapped["user_info"]["name"] == "User Name"
        assert mapped["user_info"]["email"] == "user@example.com"
        assert mapped["allows_shared_content"] is True

    @pytest.mark.unit
    def test_missing_claims_uses_defaults(self, auth):
        result = {"access_token": "at", "refresh_token": "rt"}
        mapped = auth.map_token_response(result)
        assert mapped["token_uri"] is None
        assert mapped["expiry"] is None
        assert mapped["user_info"]["name"] is None
        assert mapped["allows_shared_content"] is False


class TestGetTokenInfoFromSession:

    def _mock_mongo(self, mock_settings, find_one_return):
        mock_collection = MagicMock()
        mock_collection.find_one.return_value = find_one_return
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        mock_client = {mock_settings.MONGO_DB_NAME: mock_db}
        return mock_client

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
            assert "token_uri" in result

    @pytest.mark.unit
    def test_session_not_found_raises(self, auth, mock_settings):
        mock_client = self._mock_mongo(mock_settings, None)

        with patch("application.core.mongo_db.MongoDB.get_client", return_value=mock_client), \
             patch("application.core.settings.settings", mock_settings):
            with pytest.raises(ValueError, match="Failed to retrieve SharePoint token"):
                auth.get_token_info_from_session("bad")

    @pytest.mark.unit
    def test_missing_token_info_raises(self, auth, mock_settings):
        mock_client = self._mock_mongo(mock_settings, {"session_token": "st"})

        with patch("application.core.mongo_db.MongoDB.get_client", return_value=mock_client), \
             patch("application.core.settings.settings", mock_settings):
            with pytest.raises(ValueError, match="Failed to retrieve SharePoint token"):
                auth.get_token_info_from_session("st")

    @pytest.mark.unit
    def test_empty_token_info_raises(self, auth, mock_settings):
        mock_client = self._mock_mongo(mock_settings, {"session_token": "st", "token_info": None})

        with patch("application.core.mongo_db.MongoDB.get_client", return_value=mock_client), \
             patch("application.core.settings.settings", mock_settings):
            with pytest.raises(ValueError, match="Failed to retrieve SharePoint token"):
                auth.get_token_info_from_session("st")

    @pytest.mark.unit
    def test_missing_required_fields_raises(self, auth, mock_settings):
        mock_client = self._mock_mongo(mock_settings, {
            "session_token": "st",
            "token_info": {"access_token": "at"},
        })

        with patch("application.core.mongo_db.MongoDB.get_client", return_value=mock_client), \
             patch("application.core.settings.settings", mock_settings):
            with pytest.raises(ValueError, match="Failed to retrieve SharePoint token"):
                auth.get_token_info_from_session("st")
