from typing import Any, Dict, Optional

from jose import jwt
from jose.exceptions import ExpiredSignatureError

from docsgpt.core.settings import settings


def handle_auth(request: Any, data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Decode the caller's JWT from the Authorization header.

    Args:
        request: Incoming request exposing ``headers.get("Authorization")``.
        data: Unused legacy parameter kept for backward compatibility.

    Returns:
        The decoded token dict, ``{"sub": "local"}`` when auth is disabled,
        ``None`` when no credentials were sent, or an ``{"error": ...}`` dict
        when credentials were sent but are malformed, expired, or invalid.
    """
    if data is None:
        data = {}
    _ = data
    if settings.AUTH_TYPE in ["simple_jwt", "session_jwt", "oidc"]:
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return None

        if not isinstance(auth_header, str):
            return {
                "message": "Authentication error: invalid token",
                "error": "invalid_token",
            }
        parts = auth_header.strip().split(None, 1)
        if len(parts) != 2 or parts[0] != "Bearer" or not parts[1].strip():
            return {
                "message": "Authentication error: invalid token",
                "error": "invalid_token",
            }
        jwt_token = parts[1].strip()

        is_oidc = settings.AUTH_TYPE == "oidc"
        try:
            decoded_token = jwt.decode(
                jwt_token,
                settings.JWT_SECRET_KEY,
                algorithms=["HS256"],
                # oidc sessions are minted with an exp at the login callback and
                # must carry one: require_exp rejects any exp-less HS256 token
                # signed with JWT_SECRET_KEY (e.g. a legacy simple_jwt/session_jwt
                # token), which would otherwise authenticate forever and be
                # unrevocable. simple_jwt/session_jwt never carried an exp, so the
                # requirement is scoped to oidc.
                options={"verify_exp": is_oidc, "require_exp": is_oidc},
            )
            return decoded_token
        except ExpiredSignatureError:
            return {
                "message": "Authentication error: token expired",
                "error": "token_expired",
            }
        except Exception:
            return {
                "message": "Authentication error: invalid token",
                "error": "invalid_token",
            }
    else:
        return {"sub": "local"}
