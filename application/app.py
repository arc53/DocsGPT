import os
import platform
import uuid

import dotenv
from flask import Flask, jsonify, redirect, request
from jose import jwt

from application.auth import handle_auth

from application.core.logging_config import setup_logging

setup_logging()

from application.api import api  # noqa: E402
from application.api.answer import answer  # noqa: E402
from application.api.internal.routes import internal  # noqa: E402
from application.api.user.routes import user  # noqa: E402
from application.celery_init import celery  # noqa: E402
from application.core.settings import settings  # noqa: E402


if platform.system() == "Windows":
    import pathlib

    pathlib.PosixPath = pathlib.WindowsPath
dotenv.load_dotenv()

app = Flask(__name__)
app.register_blueprint(user)
app.register_blueprint(answer)
app.register_blueprint(internal)
app.config.update(
    UPLOAD_FOLDER="inputs",
    CELERY_BROKER_URL=settings.CELERY_BROKER_URL,
    CELERY_RESULT_BACKEND=settings.CELERY_RESULT_BACKEND,
    MONGO_URI=settings.MONGO_URI,
)
celery.config_from_object("application.celeryconfig")
api.init_app(app)

if settings.AUTH_TYPE in ("simple_jwt", "session_jwt") and not settings.JWT_SECRET_KEY:
    key_file = ".jwt_secret_key"
    try:
        with open(key_file, "r") as f:
            settings.JWT_SECRET_KEY = f.read().strip()
    except FileNotFoundError:
        new_key = os.urandom(32).hex()
        with open(key_file, "w") as f:
            f.write(new_key)
        settings.JWT_SECRET_KEY = new_key
    except Exception as e:
        raise RuntimeError(f"Failed to setup JWT_SECRET_KEY: {e}")
SIMPLE_JWT_TOKEN = None
if settings.AUTH_TYPE == "simple_jwt":
    payload = {"sub": "local"}
    SIMPLE_JWT_TOKEN = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")
    print(f"Generated Simple JWT Token: {SIMPLE_JWT_TOKEN}")


@app.route("/")
def home():
    if request.remote_addr in ("0.0.0.0", "127.0.0.1", "localhost", "172.18.0.1"):
        return redirect("http://localhost:5173")
    else:
        return "Welcome to DocsGPT Backend!"


@app.route("/api/config")
def get_config():
    response = {
        "auth_type": settings.AUTH_TYPE,
        "requires_auth": settings.AUTH_TYPE in ["simple_jwt", "session_jwt"],
    }
    return jsonify(response)


@app.route("/api/generate_token")
def generate_token():
    if settings.AUTH_TYPE == "session_jwt":
        new_user_id = str(uuid.uuid4())
        token = jwt.encode(
            {"sub": new_user_id}, settings.JWT_SECRET_KEY, algorithm="HS256"
        )
        return jsonify({"token": token})
    return jsonify({"error": "Token generation not allowed in current auth mode"}), 400


@app.before_request
def authenticate_request():
    if request.method == "OPTIONS":
        return "", 200
    decoded_token = handle_auth(request)
    if not decoded_token:
        request.decoded_token = None
    elif "error" in decoded_token:
        return jsonify(decoded_token), 401
    else:
        request.decoded_token = decoded_token


@app.after_request
def after_request(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type, Authorization")
    response.headers.add(
        "Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS"
    )
    return response


if __name__ == "__main__":
    app.run(debug=settings.FLASK_DEBUG_MODE, port=7091)
