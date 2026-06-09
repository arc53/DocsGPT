from jose import jwt
from jose.exceptions import ExpiredSignatureError

from application.core.settings import settings


def handle_auth(request, data={}):
    if settings.AUTH_TYPE in ["simple_jwt", "session_jwt", "oidc"]:
        jwt_token = request.headers.get("Authorization")
        if not jwt_token:
            return None

        jwt_token = jwt_token.replace("Bearer ", "")

        try:
            decoded_token = jwt.decode(
                jwt_token,
                settings.JWT_SECRET_KEY,
                algorithms=["HS256"],
                # oidc sessions are minted with an exp at the login callback;
                # simple_jwt/session_jwt tokens never carried one.
                options={"verify_exp": settings.AUTH_TYPE == "oidc"},
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
