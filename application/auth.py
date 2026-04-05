from datetime import datetime, timedelta, timezone

from jose import jwt

from application.core.settings import settings

# Default token lifetime: 24 hours
JWT_TOKEN_LIFETIME_HOURS = 24


def generate_token_claims():
    """Return standard JWT claims with an expiration time."""
    now = datetime.now(timezone.utc)
    return {
        "iat": now,
        "exp": now + timedelta(hours=JWT_TOKEN_LIFETIME_HOURS),
    }


def handle_auth(request, data={}):
    if settings.AUTH_TYPE in ["simple_jwt", "session_jwt"]:
        jwt_token = request.headers.get("Authorization")
        if not jwt_token:
            return None

        jwt_token = jwt_token.replace("Bearer ", "")

        try:
            decoded_token = jwt.decode(
                jwt_token,
                settings.JWT_SECRET_KEY,
                algorithms=["HS256"],
            )
            return decoded_token
        except Exception:
            return {
                "message": "Authentication error: invalid token",
                "error": "invalid_token",
            }
    else:
        return {"sub": "local"}
