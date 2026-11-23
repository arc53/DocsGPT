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
    # Unset, as in a real Settings object, so the tenant-derived authority is used.
    s.MICROSOFT_AUTHORITY = None
    return s


@pytest.fixture
def mock_msal():
    with patch("docsgpt.parser.connectors.share_point.auth.ConfidentialClientApplication") as MockMSAL:
        mock_app = MagicMock()
        MockMSAL.return_value = mock_app
        yield mock_app


@pytest.fixture
def auth(mock_settings, mock_msal):
    with patch("docsgpt.parser.connectors.share_point.auth.settings", mock_settings):
        from docsgpt.parser.connectors.share_point.auth import SharePointAuth
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
        with patch("docsgpt.parser.connectors.share_point.auth.settings", mock_settings), \
             patch("docsgpt.parser.connectors.share_point.auth.ConfidentialClientApplication"):
            from docsgpt.parser.connectors.share_point.auth import SharePointAuth
            with pytest.raises(ValueError, match="MICROSOFT_CLIENT_ID"):
                SharePointAuth()

    @pytest.mark.unit
    def test_missing_client_secret_raises(self, mock_settings):
        mock_settings.MICROSOFT_CLIENT_SECRET = None
        with patch("docsgpt.parser.connectors.share_point.auth.settings", mock_settings), \
             patch("docsgpt.parser.connectors.share_point.auth.ConfidentialClientApplication"):
            from docsgpt.parser.connectors.share_point.auth import SharePointAuth
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
    def test_missing_claims_leaves_claim_fields_unset(self, auth):
        result = {"access_token": "at", "refresh_token": "rt"}
        mapped = auth.map_token_response(result)
        assert mapped["token_uri"] is None
        assert mapped["expiry"] is None
        assert mapped["user_info"]["name"] is None
        # None, so a refresh without an id_token keeps the stored value instead of overwriting it.
        assert mapped["allows_shared_content"] is None


_NOW = 1_800_000_000
_WORK_TID = "72f988bf-86f1-41af-91ab-2d7cd011db47"
_PERSONAL_TID = "9188040d-6c67-4c5b-b112-36a304b66dad"


def _id_token_claims(tid, iat=_NOW):
    """Claims MSAL decodes from a v2.0 id_token; it lives one hour, independently of the access token."""
    return {
        "aud": "ms-client-id",
        "iss": f"https://login.microsoftonline.com/{tid}/v2.0",
        "iat": iat,
        "nbf": iat,
        "exp": iat + 3600,
        "name": "Test User",
        "oid": "00000000-0000-0000-0000-00000000abcd",
        "preferred_username": "test@example.com",
        "sub": "subject",
        "tid": tid,
        "ver": "2.0",
    }


def _token_response(expires_in, claims=None):
    """A token endpoint response as MSAL returns it, with or without an id_token."""
    result = {
        "token_type": "Bearer",
        "scope": "Files.Read Sites.Read.All User.Read openid profile email",
        "expires_in": expires_in,
        "ext_expires_in": expires_in,
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "token_source": "identity_provider",
    }
    if claims is not None:
        result["id_token"] = "header.payload.signature"
        result["id_token_claims"] = claims
    return result


class TestAccessTokenExpiry:

    @pytest.fixture(autouse=True)
    def _clock(self):
        with patch("docsgpt.parser.connectors.share_point.auth.time.time", return_value=_NOW + 0.7):
            yield

    @pytest.mark.unit
    def test_work_account_expiry_comes_from_expires_in(self, auth):
        # A work/school access token lives 60-90 minutes; the id_token one hour.
        mapped = auth.map_token_response(_token_response(4787, _id_token_claims(_WORK_TID)))
        assert mapped["expiry"] == _NOW + 4787
        assert mapped["allows_shared_content"] is True

    @pytest.mark.unit
    def test_personal_account_expiry_comes_from_expires_in(self, auth):
        mapped = auth.map_token_response(_token_response(3600, _id_token_claims(_PERSONAL_TID, iat=_NOW - 600)))
        assert mapped["expiry"] == _NOW + 3600
        assert mapped["allows_shared_content"] is False

    @pytest.mark.unit
    def test_string_expires_in_is_accepted(self, auth):
        assert auth.map_token_response(_token_response("3599", _id_token_claims(_WORK_TID)))["expiry"] == _NOW + 3599

    @pytest.mark.unit
    def test_without_expires_in_falls_back_to_id_token_exp(self, auth):
        result = _token_response(3600, _id_token_claims(_WORK_TID))
        del result["expires_in"]
        assert auth.map_token_response(result)["expiry"] == _NOW + 3600

    @pytest.mark.unit
    def test_refresh_without_id_token_still_sets_expiry(self, auth, mock_msal):
        mock_msal.acquire_token_by_refresh_token.return_value = _token_response(3600)
        refreshed = auth.refresh_access_token("old-rt")
        assert refreshed["expiry"] == _NOW + 3600
        assert refreshed["access_token"] == "access-token"
        assert refreshed["allows_shared_content"] is None
        assert refreshed["token_uri"] is None

    @pytest.mark.unit
    @pytest.mark.parametrize("tid", [_WORK_TID, _PERSONAL_TID])
    def test_refresh_with_id_token_uses_the_access_token_lifetime(self, auth, mock_msal, tid):
        # The refresh's id_token was issued earlier than the new access token.
        mock_msal.acquire_token_by_refresh_token.return_value = _token_response(
            5000, _id_token_claims(tid, iat=_NOW - 3000),
        )
        assert auth.refresh_access_token("old-rt")["expiry"] == _NOW + 5000

    @pytest.mark.unit
    def test_exchange_sets_expiry_from_expires_in(self, auth, mock_msal):
        mock_msal.acquire_token_by_authorization_code.return_value = _token_response(
            4200, _id_token_claims(_WORK_TID),
        )
        assert auth.exchange_code_for_tokens("code")["expiry"] == _NOW + 4200


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


