from unittest.mock import Mock, patch

import pytest


@pytest.mark.unit
class TestHandleAuth:

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
            leeway=60,
            options={"verify_exp": False, "require": []},
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
            leeway=60,
            options={"verify_exp": True, "require": ["exp"]},
        )

    def test_expired_token_returns_token_expired(self):
        from jwt import ExpiredSignatureError

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
        import jwt as real_jwt

        from docsgpt.auth import handle_auth

        token = real_jwt.encode({"sub": "helper_user"}, "secret", algorithm="HS256")
        mock_request = Mock()
        mock_request.headers.get.return_value = f"Bearer {token}"

        with patch("docsgpt.auth.settings") as mock_settings:
            mock_settings.AUTH_TYPE = "oidc"
            mock_settings.JWT_SECRET_KEY = "secret"
            result = handle_auth(mock_request)

        assert result["error"] == "invalid_token"

    def test_expired_token_real_jwt(self):
        import time

        import jwt as real_jwt

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

    def test_oidc_session_minted_by_a_host_with_a_fast_clock_accepted(self):
        # Another API host whose clock runs a little ahead stamps a future iat;
        # a small skew must not log the user out.
        import time

        import jwt as real_jwt

        from docsgpt.auth import handle_auth

        now = int(time.time())
        token = real_jwt.encode({"sub": "u1", "iat": now + 30, "exp": now + 3600}, "secret", algorithm="HS256")
        mock_request = Mock()
        mock_request.headers.get.return_value = f"Bearer {token}"

        with patch("docsgpt.auth.settings") as mock_settings:
            mock_settings.AUTH_TYPE = "oidc"
            mock_settings.JWT_SECRET_KEY = "secret"
            result = handle_auth(mock_request)

        assert result["sub"] == "u1"

    @pytest.mark.parametrize(
        "algorithm,key",
        [("none", None), ("HS512", "secret")],
    )
    def test_token_not_signed_with_hs256_rejected(self, algorithm, key):
        import jwt as real_jwt

        from docsgpt.auth import handle_auth

        token = real_jwt.encode({"sub": "local"}, key, algorithm=algorithm)
        mock_request = Mock()
        mock_request.headers.get.return_value = f"Bearer {token}"

        with patch("docsgpt.auth.settings") as mock_settings:
            mock_settings.AUTH_TYPE = "simple_jwt"
            mock_settings.JWT_SECRET_KEY = "secret"
            result = handle_auth(mock_request)

        assert result["error"] == "invalid_token"

    def test_simple_jwt_still_skips_exp_verification(self):
        import time

        import jwt as real_jwt

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
