"""Tests for ConnectorCreator factory class."""

from unittest.mock import patch, MagicMock

import pytest


class TestConnectorCreator:

    @pytest.fixture(autouse=True)
    def _patch_settings(self):
        """Patch settings so connector imports don't fail on missing credentials."""
        mock_settings = MagicMock()
        mock_settings.GOOGLE_CLIENT_ID = "gid"
        mock_settings.GOOGLE_CLIENT_SECRET = "gsecret"
        mock_settings.CONNECTOR_REDIRECT_BASE_URI = "https://redirect"
        mock_settings.MICROSOFT_CLIENT_ID = "mid"
        mock_settings.MICROSOFT_CLIENT_SECRET = "msecret"
        mock_settings.MICROSOFT_TENANT_ID = "tid"
        mock_settings.MONGO_DB_NAME = "test_db"

        with patch("application.core.settings.settings", mock_settings), \
             patch("application.parser.connectors.share_point.auth.settings", mock_settings), \
             patch("application.parser.connectors.google_drive.auth.settings", mock_settings), \
             patch("application.parser.connectors.share_point.auth.ConfidentialClientApplication"):
            from application.parser.connectors.connector_creator import ConnectorCreator
            self.ConnectorCreator = ConnectorCreator
            yield

    @pytest.mark.unit
    def test_get_supported_connectors(self):
        supported = self.ConnectorCreator.get_supported_connectors()
        assert "google_drive" in supported
        assert "share_point" in supported

    @pytest.mark.unit
    def test_is_supported_valid(self):
        assert self.ConnectorCreator.is_supported("google_drive") is True
        assert self.ConnectorCreator.is_supported("share_point") is True

    @pytest.mark.unit
    def test_is_supported_case_insensitive(self):
        assert self.ConnectorCreator.is_supported("Google_Drive") is True
        assert self.ConnectorCreator.is_supported("SHARE_POINT") is True

    @pytest.mark.unit
    def test_is_supported_invalid(self):
        assert self.ConnectorCreator.is_supported("dropbox") is False
        assert self.ConnectorCreator.is_supported("") is False

    @pytest.mark.unit
    def test_create_auth_google_drive(self):
        auth = self.ConnectorCreator.create_auth("google_drive")
        from application.parser.connectors.google_drive.auth import GoogleDriveAuth
        assert isinstance(auth, GoogleDriveAuth)

    @pytest.mark.unit
    def test_create_auth_share_point(self):
        auth = self.ConnectorCreator.create_auth("share_point")
        from application.parser.connectors.share_point.auth import SharePointAuth
        assert isinstance(auth, SharePointAuth)

    @pytest.mark.unit
    def test_create_auth_invalid_raises(self):
        with pytest.raises(ValueError, match="No auth class found"):
            self.ConnectorCreator.create_auth("invalid")

    @pytest.mark.unit
    def test_create_connector_invalid_raises(self):
        with pytest.raises(ValueError, match="No connector class found"):
            self.ConnectorCreator.create_connector("invalid", "session_tok")

    @pytest.mark.unit
    def test_create_connector_google_drive(self):
        with patch("application.parser.connectors.google_drive.loader.GoogleDriveAuth") as MockAuth:
            mock_auth_instance = MagicMock()
            mock_auth_instance.get_token_info_from_session.return_value = {
                "access_token": "at", "refresh_token": "rt"
            }
            mock_creds = MagicMock()
            mock_creds.token = "at"
            mock_creds.expired = False
            mock_auth_instance.create_credentials_from_token_info.return_value = mock_creds
            mock_auth_instance.build_drive_service.return_value = MagicMock()
            MockAuth.return_value = mock_auth_instance

            loader = self.ConnectorCreator.create_connector("google_drive", "session_tok")
            from application.parser.connectors.google_drive.loader import GoogleDriveLoader
            assert isinstance(loader, GoogleDriveLoader)

    @pytest.mark.unit
    def test_create_connector_share_point(self):
        with patch("application.parser.connectors.share_point.loader.SharePointAuth") as MockAuth:
            mock_auth_instance = MagicMock()
            mock_auth_instance.get_token_info_from_session.return_value = {
                "access_token": "at", "refresh_token": "rt"
            }
            MockAuth.return_value = mock_auth_instance

            loader = self.ConnectorCreator.create_connector("share_point", "session_tok")
            from application.parser.connectors.share_point.loader import SharePointLoader
            assert isinstance(loader, SharePointLoader)
