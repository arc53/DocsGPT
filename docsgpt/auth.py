from typing import Any, Dict, Optional

from jose import jwt
from jose.exceptions import ExpiredSignatureError

from docsgpt.core.settings import settings


# Claims only the PAT verifier may set. Dropped from decoded JWTs so a session
# token can never present itself as a (differently scoped) personal access token.
_PAT_ONLY_CLAIMS = ("auth_method", "pat_id", "pat_name", "scopes", "resource_filter")


def _bearer_value(request):
    header = request.headers.get("Authorization")
    if not header or not isinstance(header, str):
        return None
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value else header.strip()


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
    # Personal access tokens are opaque (not JWTs) and resolve against the
    # database in every auth mode that supports them, including AUTH_TYPE unset.
    from docsgpt.api.pat.tokens import authenticate_pat, looks_like_pat

    bearer = _bearer_value(request)
    if looks_like_pat(bearer):
        return authenticate_pat(bearer, request)

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
            for claim in _PAT_ONLY_CLAIMS:
                decoded_token.pop(claim, None)
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
