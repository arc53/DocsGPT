from unittest.mock import Mock, patch

import pytest


@pytest.mark.unit
class TestHandleAuth:

    def test_returns_local_when_no_auth_type(self):
        from application.auth import handle_auth

        mock_request = Mock()
        with patch("application.auth.settings") as mock_settings:
            mock_settings.AUTH_TYPE = "none"
            result = handle_auth(mock_request)

        assert result == {"sub": "local"}

    def test_returns_none_when_no_jwt_header(self):
        from application.auth import handle_auth

        mock_request = Mock()
        mock_request.headers.get.return_value = None
        with patch("application.auth.settings") as mock_settings:
            mock_settings.AUTH_TYPE = "simple_jwt"
            result = handle_auth(mock_request)

        assert result is None

    def test_decodes_valid_jwt(self):
        from application.auth import handle_auth

        mock_request = Mock()
        mock_request.headers.get.return_value = "Bearer valid_token"

        with patch("application.auth.settings") as mock_settings, patch(
            "application.auth.jwt"
        ) as mock_jwt:
            mock_settings.AUTH_TYPE = "simple_jwt"
            mock_settings.JWT_SECRET_KEY = "secret"
            mock_jwt.decode.return_value = {"sub": "user123"}
            result = handle_auth(mock_request)

        assert result == {"sub": "user123"}
        mock_jwt.decode.assert_called_once_with(
            "valid_token",
            "secret",
            algorithms=["HS256"],
        )

    def test_returns_error_on_invalid_jwt(self):
        from application.auth import handle_auth

        mock_request = Mock()
        mock_request.headers.get.return_value = "Bearer bad_token"

        with patch("application.auth.settings") as mock_settings, patch(
            "application.auth.jwt"
        ) as mock_jwt:
            mock_settings.AUTH_TYPE = "session_jwt"
            mock_settings.JWT_SECRET_KEY = "secret"
            mock_jwt.decode.side_effect = Exception("Invalid token")
            result = handle_auth(mock_request)

        assert result["error"] == "invalid_token"

    def test_strips_bearer_prefix(self):
        from application.auth import handle_auth

        mock_request = Mock()
        mock_request.headers.get.return_value = "Bearer my_token"

        with patch("application.auth.settings") as mock_settings, patch(
            "application.auth.jwt"
        ) as mock_jwt:
            mock_settings.AUTH_TYPE = "simple_jwt"
            mock_settings.JWT_SECRET_KEY = "secret"
            mock_jwt.decode.return_value = {"sub": "user1"}
            handle_auth(mock_request)

        mock_jwt.decode.assert_called_once()
        assert mock_jwt.decode.call_args[0][0] == "my_token"
