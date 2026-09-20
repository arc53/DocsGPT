from unittest.mock import Mock, patch

import pytest


@pytest.mark.unit
class TestHandleAuth:
    @pytest.mark.parametrize(
        "authorization",
        ["Token token", "Bearer", "Bearer ", "", 123],
    )
    def test_rejects_malformed_authorization_headers(self, authorization):
        from docsgpt.auth import handle_auth

        mock_request = Mock()
        mock_request.headers.get.return_value = authorization
        with patch("docsgpt.auth.settings") as mock_settings:
            mock_settings.AUTH_TYPE = "simple_jwt"
            with patch("docsgpt.auth.jwt.decode") as mock_decode:
                result = handle_auth(mock_request)

        assert result == {
            "message": "Authentication error: invalid token",
            "error": "invalid_token",
        }
        mock_decode.assert_not_called()

    def test_preserves_valid_bearer_token(self):
        from docsgpt.auth import handle_auth

        mock_request = Mock()
        mock_request.headers.get.return_value = "Bearer tokenBearerValue"
        with patch("docsgpt.auth.settings") as mock_settings, patch(
            "docsgpt.auth.jwt"
        ) as mock_jwt:
            mock_settings.AUTH_TYPE = "simple_jwt"
            mock_settings.JWT_SECRET_KEY = "secret"
            mock_jwt.decode.return_value = {"sub": "user123"}
            result = handle_auth(mock_request)

        assert result == {"sub": "user123"}
        assert mock_jwt.decode.call_args.args[0] == "tokenBearerValue"

    @pytest.mark.parametrize("header_prefix", ["raw", "Token", "XBearer", "Bearer Bearer"])
    def test_rejects_valid_jwt_with_invalid_authorization_scheme(self, header_prefix):
        from jose import jwt as real_jwt

        from docsgpt.auth import handle_auth

        token = real_jwt.encode({"sub": "user123"}, "secret", algorithm="HS256")
        authorization = token if header_prefix == "raw" else f"{header_prefix} {token}"
        mock_request = Mock()
        mock_request.headers.get.return_value = authorization
        with patch("docsgpt.auth.settings") as mock_settings, patch(
            "docsgpt.auth.jwt.decode"
        ) as mock_decode:
            mock_settings.AUTH_TYPE = "simple_jwt"
            mock_settings.JWT_SECRET_KEY = "secret"
            result = handle_auth(mock_request)

        assert result == {
            "message": "Authentication error: invalid token",
            "error": "invalid_token",
        }
        mock_decode.assert_not_called()

    def test_data_default_is_not_mutable(self):
        import inspect

        from docsgpt.auth import handle_auth

        assert inspect.signature(handle_auth).parameters["data"].default is None

    def test_returns_local_when_no_auth_type(self):
        from docsgpt.auth import handle_auth

        mock_request = Mock()
        with patch("docsgpt.auth.settings") as mock_settings:
            mock_settings.AUTH_TYPE = "none"
            result = handle_auth(mock_request)

        assert result == {"sub": "local"}

    def test_returns_none_when_no_jwt_header(self):
        from docsgpt.auth import handle_auth

        mock_request = Mock()
        mock_request.headers.get.return_value = None
        with patch("docsgpt.auth.settings") as mock_settings:
            mock_settings.AUTH_TYPE = "simple_jwt"
            result = handle_auth(mock_request)

        assert result is None

    def test_decodes_valid_jwt(self):
        from docsgpt.auth import handle_auth

        mock_request = Mock()
        mock_request.headers.get.return_value = "Bearer valid_token"

        with patch("docsgpt.auth.settings") as mock_settings, patch(
            "docsgpt.auth.jwt"
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
            options={"verify_exp": False, "require_exp": False},
        )

    def test_returns_error_on_invalid_jwt(self):
        from docsgpt.auth import handle_auth

        mock_request = Mock()
        mock_request.headers.get.return_value = "Bearer bad_token"

        with patch("docsgpt.auth.settings") as mock_settings, patch(
            "docsgpt.auth.jwt"
        ) as mock_jwt:
            mock_settings.AUTH_TYPE = "session_jwt"
            mock_settings.JWT_SECRET_KEY = "secret"
            mock_jwt.decode.side_effect = Exception("Invalid token")
            result = handle_auth(mock_request)

        assert result["error"] == "invalid_token"

    def test_strips_bearer_prefix(self):
        from docsgpt.auth import handle_auth

        mock_request = Mock()
        mock_request.headers.get.return_value = "Bearer my_token"

        with patch("docsgpt.auth.settings") as mock_settings, patch(
            "docsgpt.auth.jwt"
        ) as mock_jwt:
            mock_settings.AUTH_TYPE = "simple_jwt"
            mock_settings.JWT_SECRET_KEY = "secret"
            mock_jwt.decode.return_value = {"sub": "user1"}
            handle_auth(mock_request)

        mock_jwt.decode.assert_called_once()
        assert mock_jwt.decode.call_args[0][0] == "my_token"


@pytest.mark.unit
class TestHandleAuthOidc:
    """AUTH_TYPE=oidc: same local HS256 session tokens, but exp is verified."""

    def test_returns_none_when_no_jwt_header(self):
        from docsgpt.auth import handle_auth

        mock_request = Mock()
        mock_request.headers.get.return_value = None
        with patch("docsgpt.auth.settings") as mock_settings:
            mock_settings.AUTH_TYPE = "oidc"
            result = handle_auth(mock_request)

        assert result is None

    def test_decodes_valid_jwt_with_exp_verification(self):
        from docsgpt.auth import handle_auth

        mock_request = Mock()
        mock_request.headers.get.return_value = "Bearer valid_token"

        with patch("docsgpt.auth.settings") as mock_settings, patch(
            "docsgpt.auth.jwt"
        ) as mock_jwt:
            mock_settings.AUTH_TYPE = "oidc"
            mock_settings.JWT_SECRET_KEY = "secret"
            mock_jwt.decode.return_value = {"sub": "user123", "email": "u@example.com"}
            result = handle_auth(mock_request)

        assert result == {"sub": "user123", "email": "u@example.com"}
        mock_jwt.decode.assert_called_once_with(
            "valid_token",
            "secret",
            algorithms=["HS256"],
            options={"verify_exp": True, "require_exp": True},
        )

    def test_expired_token_returns_token_expired(self):
        from jose.exceptions import ExpiredSignatureError

        from docsgpt.auth import handle_auth

        mock_request = Mock()
        mock_request.headers.get.return_value = "Bearer stale_token"

        with patch("docsgpt.auth.settings") as mock_settings, patch(
            "docsgpt.auth.jwt"
        ) as mock_jwt:
            mock_settings.AUTH_TYPE = "oidc"
            mock_settings.JWT_SECRET_KEY = "secret"
            mock_jwt.decode.side_effect = ExpiredSignatureError("expired")
            result = handle_auth(mock_request)

        assert result["error"] == "token_expired"

    def test_invalid_token_returns_invalid_token(self):
        from docsgpt.auth import handle_auth

        mock_request = Mock()
        mock_request.headers.get.return_value = "Bearer bad_token"

        with patch("docsgpt.auth.settings") as mock_settings, patch(
            "docsgpt.auth.jwt"
        ) as mock_jwt:
            mock_settings.AUTH_TYPE = "oidc"
            mock_settings.JWT_SECRET_KEY = "secret"
            mock_jwt.decode.side_effect = Exception("bad")
            result = handle_auth(mock_request)

        assert result["error"] == "invalid_token"

    def test_token_without_exp_rejected_under_oidc(self):
        # Under oidc, exp is REQUIRED: an exp-less HS256 token signed with the
        # shared secret (e.g. a legacy simple_jwt/session_jwt token) must not
        # authenticate, or it would be valid forever and unrevocable.
        from jose import jwt as real_jwt

        from docsgpt.auth import handle_auth

        token = real_jwt.encode({"sub": "helper_user"}, "secret", algorithm="HS256")
        mock_request = Mock()
        mock_request.headers.get.return_value = f"Bearer {token}"

        with patch("docsgpt.auth.settings") as mock_settings:
            mock_settings.AUTH_TYPE = "oidc"
            mock_settings.JWT_SECRET_KEY = "secret"
            result = handle_auth(mock_request)

        assert result["error"] == "invalid_token"

    def test_expired_token_real_jose(self):
        import time

        from jose import jwt as real_jwt

        from docsgpt.auth import handle_auth

        token = real_jwt.encode(
            {"sub": "helper_user", "exp": int(time.time()) - 3600},
            "secret",
            algorithm="HS256",
        )
        mock_request = Mock()
        mock_request.headers.get.return_value = f"Bearer {token}"

        with patch("docsgpt.auth.settings") as mock_settings:
            mock_settings.AUTH_TYPE = "oidc"
            mock_settings.JWT_SECRET_KEY = "secret"
            result = handle_auth(mock_request)

        assert result["error"] == "token_expired"

    def test_simple_jwt_still_skips_exp_verification(self):
        import time

        from jose import jwt as real_jwt

        from docsgpt.auth import handle_auth

        token = real_jwt.encode(
            {"sub": "local", "exp": int(time.time()) - 3600},
            "secret",
            algorithm="HS256",
        )
        mock_request = Mock()
        mock_request.headers.get.return_value = f"Bearer {token}"

        with patch("docsgpt.auth.settings") as mock_settings:
            mock_settings.AUTH_TYPE = "simple_jwt"
            mock_settings.JWT_SECRET_KEY = "secret"
            result = handle_auth(mock_request)

        assert result["sub"] == "local"
