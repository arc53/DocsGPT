import logging
import os
import platform
import uuid

import dotenv
from flask import Flask, Response, jsonify, redirect, request
from jose import jwt

from application.auth import handle_auth

from application.core import log_context
from application.core.logging_config import setup_logging

setup_logging()

from application.api import api  # noqa: E402
from application.api.answer import answer  # noqa: E402
from application.api.internal.routes import internal  # noqa: E402
from application.api.user.routes import user  # noqa: E402
from application.api.connector.routes import connector  # noqa: E402
from application.api.v1 import v1_bp  # noqa: E402
from application.celery_init import celery  # noqa: E402
from application.core.settings import settings  # noqa: E402
from application.storage.db.bootstrap import ensure_database_ready  # noqa: E402
from application.stt.upload_limits import (  # noqa: E402
    build_stt_file_size_limit_message,
    should_reject_stt_request,
)


if platform.system() == "Windows":
    import pathlib

    pathlib.PosixPath = pathlib.WindowsPath
dotenv.load_dotenv()

# Self-bootstrap the user-data Postgres DB. Runs before any blueprint or
# repository touches the engine, so the first request can't race the
# schema being created. Gated by AUTO_CREATE_DB / AUTO_MIGRATE settings
# (default ON for dev; disable in prod if schema is managed out-of-band).
ensure_database_ready(
    settings.POSTGRES_URI,
    create_db=settings.AUTO_CREATE_DB,
    migrate=settings.AUTO_MIGRATE,
    logger=logging.getLogger("application.app"),
)

app = Flask(__name__)
app.register_blueprint(user)
app.register_blueprint(answer)
app.register_blueprint(internal)
app.register_blueprint(connector)
app.register_blueprint(v1_bp)
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


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


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


_LOG_CTX_TOKEN_ATTR = "_log_ctx_token"


@app.before_request
def _bind_log_context():
    """Bind activity_id + endpoint for the duration of this request.

    Runs before ``authenticate_request``; ``user_id`` is overlaid in a
    follow-up handler once the JWT has been decoded.
    """
    if request.method == "OPTIONS":
        return None
    activity_id = str(uuid.uuid4())
    request.activity_id = activity_id
    token = log_context.bind(
        activity_id=activity_id,
        endpoint=request.endpoint,
    )
    setattr(request, _LOG_CTX_TOKEN_ATTR, token)
    return None


@app.teardown_request
def _reset_log_context(_exc):
    # SSE streams keep yielding after teardown fires, but a2wsgi runs each
    # request inside ``copy_context().run(...)``, so this reset doesn't
    # leak into the stream's view of the context.
    token = getattr(request, _LOG_CTX_TOKEN_ATTR, None)
    if token is not None:
        log_context.reset(token)


@app.before_request
def enforce_stt_request_size_limits():
    if request.method == "OPTIONS":
        return None
    if should_reject_stt_request(request.path, request.content_length):
        return (
            jsonify(
                {
                    "success": False,
                    "message": build_stt_file_size_limit_message(),
                }
            ),
            413,
        )
    return None


@app.before_request
def authenticate_request():
    if request.method == "OPTIONS":
        return "", 200
    # OpenAI-compatible routes authenticate via opaque agent API keys in the
    # Authorization header, which the JWT decoder below would reject. Defer
    # auth to the route handlers (see application/api/v1/routes.py).
    if request.path.startswith("/v1/"):
        request.decoded_token = None
        return None
    decoded_token = handle_auth(request)
    if not decoded_token:
        request.decoded_token = None
    elif "error" in decoded_token:
        return jsonify(decoded_token), 401
    else:
        request.decoded_token = decoded_token


@app.before_request
def _bind_user_id_to_log_context():
    # Registered after ``authenticate_request`` (Flask runs before_request
    # handlers in registration order), so ``request.decoded_token`` is
    # populated by the time we read it. ``teardown_request`` unwinds the
    # whole request-level bind, so no separate reset token is needed here.
    if request.method == "OPTIONS":
        return None
    decoded_token = getattr(request, "decoded_token", None)
    user_id = decoded_token.get("sub") if isinstance(decoded_token, dict) else None
    if user_id:
        log_context.bind(user_id=user_id)
    return None


@app.after_request
def after_request(response: Response) -> Response:
    """Add CORS headers for the pure Flask development entrypoint."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    return response


if __name__ == "__main__":
    app.run(debug=settings.FLASK_DEBUG_MODE, port=7091)
