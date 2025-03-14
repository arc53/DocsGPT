import uuid

from jose import jwt

from application.core.settings import settings


def handle_auth(request, data={}):
    if settings.AUTH_TYPE == "simple_jwt":
        jwt_token = request.headers.get("Authorization")
        if not jwt_token:
            return {"message": "Missing Authorization header"}

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
            return {"message": f"Authentication error: {str(e)}"}
    else:
        return {"sub": "local"}


def get_or_create_user_id():
    try:
        with open(settings.USER_ID_FILE, "r") as f:
            user_id = f.read().strip()
            return user_id
    except FileNotFoundError:
        user_id = str(uuid.uuid4())
        with open(settings.USER_ID_FILE, "w") as f:
            f.write(user_id)
        return user_id
