"""
PoC test for CWE-287: JWT tokens never expire.

Demonstrates that:
1. Tokens with an expired `exp` claim are rejected (verify_exp enforced)
2. Valid tokens with future `exp` are accepted
3. Token generation helpers include `exp` claim
"""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from jose import jwt


SECRET = "test-secret-key-for-jwt"
ALGORITHM = "HS256"


def test_expired_token_is_rejected():
    """An expired JWT must be rejected by handle_auth."""
    from application.core.settings import settings

    original_auth = settings.AUTH_TYPE
    original_key = settings.JWT_SECRET_KEY
    try:
        settings.AUTH_TYPE = "session_jwt"
        settings.JWT_SECRET_KEY = SECRET

        # Create a token that expired 1 hour ago
        expired_payload = {
            "sub": "user123",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        expired_token = jwt.encode(expired_payload, SECRET, algorithm=ALGORITHM)

        mock_request = MagicMock()
        mock_request.headers.get.return_value = f"Bearer {expired_token}"

        from application.auth import handle_auth

        result = handle_auth(mock_request)

        # After the fix, expired tokens MUST return an error
        assert result is not None, "handle_auth returned None for expired token"
        assert "error" in result, (
            f"Expired token was accepted without error. Got: {result}"
        )
    finally:
        settings.AUTH_TYPE = original_auth
        settings.JWT_SECRET_KEY = original_key


def test_valid_token_still_works():
    """A valid, non-expired token must still be accepted after the fix."""
    from application.core.settings import settings

    original_auth = settings.AUTH_TYPE
    original_key = settings.JWT_SECRET_KEY
    try:
        settings.AUTH_TYPE = "session_jwt"
        settings.JWT_SECRET_KEY = SECRET

        valid_payload = {
            "sub": "user456",
            "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        }
        valid_token = jwt.encode(valid_payload, SECRET, algorithm=ALGORITHM)

        mock_request = MagicMock()
        mock_request.headers.get.return_value = f"Bearer {valid_token}"

        from application.auth import handle_auth

        result = handle_auth(mock_request)

        assert result is not None
        assert "error" not in result, f"Valid token rejected: {result}"
        assert result["sub"] == "user456"
    finally:
        settings.AUTH_TYPE = original_auth
        settings.JWT_SECRET_KEY = original_key


def test_generate_token_claims_includes_exp():
    """generate_token_claims() must produce an exp claim in the future."""
    from application.auth import generate_token_claims

    claims = generate_token_claims()
    assert "exp" in claims, f"Missing 'exp' in claims: {claims}"
    assert "iat" in claims, f"Missing 'iat' in claims: {claims}"

    # exp should be a datetime in the future
    exp = claims["exp"]
    if isinstance(exp, datetime):
        assert exp > datetime.now(timezone.utc), "exp is not in the future"
    else:
        # numeric timestamp
        assert exp > time.time(), "exp is not in the future"


def test_token_without_exp_is_still_accepted():
    """
    Tokens without an exp claim should still be accepted by python-jose
    when verify_exp is True (the default) as long as no exp is present.
    This verifies the decode path does not break for legacy tokens that
    have no exp claim at all — python-jose only rejects if exp IS present
    and is in the past.
    """
    from application.core.settings import settings

    original_auth = settings.AUTH_TYPE
    original_key = settings.JWT_SECRET_KEY
    try:
        settings.AUTH_TYPE = "session_jwt"
        settings.JWT_SECRET_KEY = SECRET

        # Token with no exp claim at all (legacy)
        no_exp_payload = {"sub": "legacy_user"}
        no_exp_token = jwt.encode(no_exp_payload, SECRET, algorithm=ALGORITHM)

        mock_request = MagicMock()
        mock_request.headers.get.return_value = f"Bearer {no_exp_token}"

        from application.auth import handle_auth

        result = handle_auth(mock_request)

        # python-jose with verify_exp=True (default) still accepts tokens
        # without an exp claim — it only rejects expired ones.
        assert result is not None
        assert result["sub"] == "legacy_user"
    finally:
        settings.AUTH_TYPE = original_auth
        settings.JWT_SECRET_KEY = original_key
