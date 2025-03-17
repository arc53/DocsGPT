from jose import jwt

from application.core.settings import settings


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
                options={"verify_exp": False},
            )
            return decoded_token
        except Exception as e:
            return {
                "message": f"Authentication error: {str(e)}",
                "error": "invalid_token",
            }
    else:
        return {"sub": "local"}
