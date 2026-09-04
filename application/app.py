import logging
import os
import platform
import uuid

import dotenv
from flask import Flask, Response, jsonify, redirect, request
from jose import jwt
from werkzeug.exceptions import RequestEntityTooLarge

from application.auth import handle_auth

from application.core import log_context
from application.core.logging_config import setup_logging

setup_logging()

from application.api import api  # noqa: E402
from application.api.admin import admin_ns  # noqa: E402
from application.api.answer import answer  # noqa: E402
from application.api.devices import devices_bp  # noqa: E402
from application.api.events.routes import events  # noqa: E402
from application.api.internal.routes import internal  # noqa: E402
from application.api.oidc import oidc_bp  # noqa: E402
from application.api.oidc.denylist import is_denied as oidc_session_denied  # noqa: E402
from application.api.scim import scim_bp  # noqa: E402
from application.api.user.authz import resolve_roles  # noqa: E402
from application.api.user.routes import user  # noqa: E402
from application.api.connector.routes import connector  # noqa: E402
from application.api.v1 import v1_bp  # noqa: E402
from application.celery_init import celery  # noqa: E402
from application.core.secret_key import resolve_jwt_secret_key  # noqa: E402
from application.core.settings import settings  # noqa: E402
from application.storage.db.bootstrap import (  # noqa: E402
    ensure_database_ready,
    ensure_vector_schema,
)
from application.storage.db.embeddings_pin import (  # noqa: E402
    resolve_embeddings_pin,
    warn_on_source_model_mismatch,
)
from application.stt.upload_limits import (  # noqa: E402
    build_stt_file_size_limit_message,
    should_reject_stt_request,
)
from application.upload_limits import (  # noqa: E402
    is_document_upload_path,
    upload_request_limit_message,
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

# Which embedding model this installation uses is a property of its index, not of
# the release. Resolve it before the vector schema hook below, which sizes the
# table from EMBEDDINGS_NAME, and before anything embeds.
resolve_embeddings_pin(logging.getLogger("application.app"))
warn_on_source_model_mismatch(logging.getLogger("application.app"))

# Own the vector DB's schema here too, so the retrieval hot path is pure reads
# instead of re-running DDL for every source of every request.
if settings.AUTO_VECTOR_SCHEMA:
    _vector_schema_log = logging.getLogger("application.app")
    try:
        ensure_vector_schema(logger=_vector_schema_log)
    except Exception:
        # The vector DB is often a separate cluster. This runs at import time,
        # so re-raising would stop gunicorn and every Celery worker from
        # booting -- taking auth, chat history and webhooks down over a fault
        # that only affects retrieval. PGVectorStore re-checks the schema on
        # its write path, so degrading here loses nothing.
        _vector_schema_log.exception(
            "ensure_vector_schema failed; retrieval is degraded until the "
            "vector database is reachable and its width matches EMBEDDINGS_NAME."
        )

from application.agents.default_tools import (  # noqa: E402
    validate_default_chat_tools,
)

validate_default_chat_tools()

app = Flask(__name__)
app.register_blueprint(user)
app.register_blueprint(answer)
app.register_blueprint(events)
app.register_blueprint(internal)
app.register_blueprint(connector)
app.register_blueprint(devices_bp)
app.register_blueprint(oidc_bp)
app.register_blueprint(scim_bp)
app.register_blueprint(v1_bp)
# Register the admin namespace once. The membership guard makes this idempotent
# if application.app is re-imported (coverage tests reload the module): without
# it, re-running add_namespace would re-register routes on the already-served
# first app and raise "add_url_rule can no longer be called".
if admin_ns not in api.namespaces:
    api.add_namespace(admin_ns)
app.config.update(
    UPLOAD_FOLDER="inputs",
    CELERY_BROKER_URL=settings.CELERY_BROKER_URL,
    CELERY_RESULT_BACKEND=settings.CELERY_RESULT_BACKEND,
    MONGO_URI=settings.MONGO_URI,
)
celery.config_from_object("application.celeryconfig")
api.init_app(app)


def _upload_limit_error_payload() -> dict[str, bool | str]:
    """Build a consistent 413 payload using the active route-specific limit."""
    active_limit = request.max_content_length
    if active_limit is None:
        active_limit = settings.UPLOAD_MAX_REQUEST_BYTES
    return {
        "success": False,
        "message": upload_request_limit_message(active_limit),
    }


@app.errorhandler(RequestEntityTooLarge)
def handle_request_entity_too_large(_error):
    """Return API-shaped JSON instead of Werkzeug's HTML 413 page."""
    return jsonify(_upload_limit_error_payload()), 413


@api.errorhandler(RequestEntityTooLarge)
def handle_restx_request_entity_too_large(_error):
    """Keep Flask-RESTX from replacing the configured upload-limit response."""
    return _upload_limit_error_payload(), 413


@app.before_request
def enforce_document_upload_request_size_limit():
    """Bound multipart parsing for public file-upload routes only.

    Internal worker index uploads are intentionally excluded; they are trusted
    service traffic and can legitimately exceed the end-user document limit.
    """
    if request.method == "OPTIONS" or not is_document_upload_path(request.path):
        return None
    request_limit = (
        settings.PARSE_SPEC_MAX_BYTES
        if request.path == "/api/parse_spec" and request.is_json
        else settings.UPLOAD_MAX_REQUEST_BYTES
    )
    request.max_content_length = request_limit
    if (
        request.content_length is not None
        and request.content_length > request_limit
    ):
        raise RequestEntityTooLarge()
    return None

# The same stable secret also signs opaque agent-image capabilities, including
# in no-auth mode. Production replicas must receive one shared configured key;
# only local development may use the atomic filesystem fallback.
settings.JWT_SECRET_KEY = resolve_jwt_secret_key(
    settings.JWT_SECRET_KEY,
    os.getenv("DEPLOYMENT_TYPE"),
)
if settings.AUTH_TYPE == "oidc":
    _missing_oidc = [
        name
        for name in ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_FRONTEND_URL")
        if not getattr(settings, name)
    ]
    if _missing_oidc:
        raise RuntimeError(f"AUTH_TYPE=oidc requires settings: {', '.join(_missing_oidc)}")
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
    from application.graphrag import graphrag_available

    response = {
        "auth_type": settings.AUTH_TYPE,
        "requires_auth": settings.AUTH_TYPE in ["simple_jwt", "session_jwt", "oidc"],
        "graphrag_available": graphrag_available(),
        "hybrid_available": settings.VECTOR_STORE == "pgvector",
    }
    if settings.AUTH_TYPE == "oidc":
        response["oidc"] = {
            "login_path": "/api/auth/oidc/login",
            "logout_path": "/api/auth/oidc/logout",
            "provider_name": settings.OIDC_PROVIDER_NAME,
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
        # Flask >= 3.1.2 tears a stream_with_context request down twice: once
        # when the view returns, once when the generator is finalized. Clear
        # the token first — resetting one twice raises RuntimeError.
        setattr(request, _LOG_CTX_TOKEN_ATTR, None)
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
    # Remote-device CLI endpoints carry opaque ``tok_…`` session tokens
    # (not JWTs); ``verify_device_session`` runs inside the route handler.
    # The redeem endpoint is tokenless — it authenticates via the one-time
    # ``user_code`` inside ``redeem_pairing`` — so it's exempt too. Pairing
    # create + status stay JWT-protected (UI calls).
    if (
        request.path.startswith("/api/devices/poll")
        or request.path.startswith("/api/devices/sessions/")
        or request.path == "/api/devices/me"
        or request.path == "/api/devices/pairings/redeem"
    ):
        request.decoded_token = None
        return None
    # OIDC login/callback/token endpoints must stay reachable even when the
    # browser still carries a stale or expired Bearer token — otherwise the
    # 401 below would lock the user out of the only path to a fresh session.
    if request.path.startswith("/api/auth/oidc/"):
        request.decoded_token = None
        return None
    # SCIM provisioning authenticates with its own bearer token (SCIM_TOKEN),
    # validated inside the blueprint.
    if request.path.startswith("/scim/"):
        request.decoded_token = None
        return None
    decoded_token = handle_auth(request)
    if not decoded_token:
        request.decoded_token = None
    elif "error" in decoded_token:
        return jsonify(decoded_token), 401
    elif settings.AUTH_TYPE == "oidc" and oidc_session_denied(decoded_token):
        # Back-channel logout / SCIM deactivation revoked this session.
        return (
            jsonify(
                {
                    "message": "Authentication error: session revoked",
                    "error": "token_revoked",
                }
            ),
            401,
        )
    else:
        # Resolve roles once here, the single authenticated chokepoint. Roles
        # are computed (never read from the JWT) and overwrite any inbound
        # 'roles' claim. /v1, device, oidc, and scim paths set decoded_token
        # above and never reach here, so they stay role-less by design.
        decoded_token["roles"] = resolve_roles(decoded_token)
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
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization, Idempotency-Key"
    )
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    return response


if __name__ == "__main__":
    app.run(debug=settings.FLASK_DEBUG_MODE, port=7091)
