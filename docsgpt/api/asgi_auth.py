"""Request authentication for the native-async (Starlette) routes.

Mirrors ``authenticate_request`` and the log-context hooks in
``docsgpt/app.py`` so a route moved off Flask keeps the same gates: the same
JWT decoder and 401 payloads, and the OIDC revocation check.
"""

from __future__ import annotations

import uuid
from contextvars import Token
from typing import Optional, Tuple

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse

from docsgpt.api.oidc.denylist import is_denied as oidc_session_denied
from docsgpt.auth import handle_auth
from docsgpt.core import log_context
from docsgpt.core.settings import settings


async def authenticate(request: Request) -> Tuple[Optional[dict], Optional[JSONResponse]]:
    """Decode the caller's JWT the way Flask's ``authenticate_request`` does.

    Args:
        request: The incoming Starlette request.

    Returns:
        tuple: ``(claims, None)`` for an authenticated caller, ``(None, None)``
        when no token was sent (the route decides whether that is allowed), or
        ``(None, response)`` carrying the 401 to return.
    """
    decoded = handle_auth(request)
    if not decoded:
        return None, None
    if "error" in decoded:
        return None, JSONResponse(decoded, status_code=401)
    # The denylist is a sync Redis read; keep it off the event loop.
    if settings.AUTH_TYPE == "oidc" and await anyio.to_thread.run_sync(oidc_session_denied, decoded):
        return None, JSONResponse(
            {"message": "Authentication error: session revoked", "error": "token_revoked"},
            status_code=401,
        )
    return decoded, None


def bind_log_context(endpoint: str, user_id: Optional[str] = None) -> Token:
    """Stamp this request's log records with a fresh activity id, the endpoint and user.

    Each request runs in its own task, so the binding ends with the request.
    """
    return log_context.bind(activity_id=str(uuid.uuid4()), endpoint=endpoint, user_id=user_id)


def json_error(message: str, status_code: int) -> JSONResponse:
    """Return the ``{"success": false, "message": ...}`` body the Flask routes use."""
    return JSONResponse({"success": False, "message": message}, status_code=status_code)
