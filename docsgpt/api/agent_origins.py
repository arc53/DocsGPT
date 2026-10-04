"""Refuse an agent's API key when the request comes from an origin it does not allow.

An agent's ``config.allowed_origins`` (on while ``config.restrict_origins`` is)
limits which websites can call it with its key. The key is accepted in many
places (a JSON or form ``api_key``, an ``api_key`` query parameter, the ``/v1``
and ``/mcp`` bearer token), so the check runs once per request rather than in
each route: :func:`enforce_agent_origin` is a Flask ``before_request`` hook,
and the two ASGI-only entry points, the MCP tool and the artifact download,
call :func:`origin_refusal` themselves.

The ``Origin`` header is set by browsers, so this keeps other websites from
embedding a key, not a script that sets its own header. A request with no
origin at all (a server, ``curl``) is refused by a restricted agent.
"""

from __future__ import annotations

import logging
from typing import Iterable, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from flask import jsonify, make_response, request

from docsgpt.core.settings import settings
from docsgpt.guardrails.config import AgentConfig
from docsgpt.security.origins import DEV_FRONTEND_PORT, LOOPBACK_HOSTS, normalize_origin, request_origin
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.session import db_readonly

logger = logging.getLogger(__name__)

DENIED_MESSAGE = "This origin is not allowed to use this agent's API key."
UNAVAILABLE_MESSAGE = "Could not check this request's origin. Please try again later."

_FORM_MIMETYPES = ("multipart/form-data", "application/x-www-form-urlencoded")


def trusted_origins(host_url: Optional[str]) -> list[str]:
    """Origins every restricted agent accepts besides its own list.

    DocsGPT's own pages call agents with their keys too (a promptable shared
    conversation does), so this instance's frontend is always trusted: the
    API's own origin (the UI served by the backend), ``OIDC_FRONTEND_URL``,
    and the Vite dev server when the API runs on loopback. Then come the
    operator's ``AGENT_TRUSTED_ORIGINS``.

    Args:
        host_url: The URL the request reached the API at.

    Returns:
        The normalized origins, without duplicates.
    """
    candidates = [host_url, settings.OIDC_FRONTEND_URL]
    own = normalize_origin(host_url)
    if own and urlsplit(own).hostname in LOOPBACK_HOSTS:
        candidates += [f"http://{host}:{DEV_FRONTEND_PORT}" for host in ("localhost", "127.0.0.1")]
    candidates += settings.AGENT_TRUSTED_ORIGINS
    origins: list[str] = []
    for candidate in candidates:
        origin = normalize_origin(candidate)
        if origin and origin not in origins:
            origins.append(origin)
    return origins


def origin_denied(
    api_keys: Iterable[Optional[str]], headers: Mapping[str, str], host_url: Optional[str]
) -> bool:
    """Whether any of ``api_keys`` belongs to an agent that refuses this request's origin.

    An unknown key is not refused here: the route answers it with its own
    invalid-key error.

    Args:
        api_keys: Every agent key the request carries; empty values are skipped.
        headers: The request headers, read for ``Origin`` and ``Referer``.
        host_url: The URL the request reached the API at, for :func:`trusted_origins`.

    Returns:
        True when the request must be refused.
    """
    keys = {key.strip() for key in api_keys if isinstance(key, str) and key.strip()}
    if not keys:
        return False
    origin = request_origin(headers)
    trusted = trusted_origins(host_url)
    with db_readonly() as conn:
        repo = AgentsRepository(conn)
        for key in keys:
            agent = repo.find_by_key(key)
            if agent is None:
                continue
            if not AgentConfig.parse(agent.get("config")).origin_allowed(origin, trusted):
                logger.warning(
                    "Refused agent API key for agent %s from origin %s",
                    agent.get("id"),
                    origin or "(none)",
                )
                return True
    return False


def origin_refusal(
    api_keys: Iterable[Optional[str]], headers: Mapping[str, str], host_url: Optional[str]
) -> Optional[Tuple[str, int]]:
    """The ``(message, status)`` to refuse a request with, or None to let it through.

    Fails closed: when the agents cannot be looked up, the request is refused
    with a 503 rather than let through, or a database hiccup would serve a
    restricted key to any origin.

    Args:
        api_keys: Every agent key the request carries.
        headers: The request headers.
        host_url: The URL the request reached the API at.

    Returns:
        ``(DENIED_MESSAGE, 403)``, ``(UNAVAILABLE_MESSAGE, 503)`` or None.
    """
    try:
        denied = origin_denied(api_keys, headers, host_url)
    except Exception:
        logger.exception("Could not check the origin of an agent API key request")
        return UNAVAILABLE_MESSAGE, 503
    return (DENIED_MESSAGE, 403) if denied else None


def _flask_request_keys() -> list[str]:
    """Every agent key the current Flask request carries, wherever a route may read it."""
    keys = request.args.getlist("api_key")
    if request.mimetype in _FORM_MIMETYPES:
        keys += request.form.getlist("api_key")
    if request.is_json:
        body = request.get_json(silent=True)
        if isinstance(body, dict):
            keys.append(body.get("api_key"))
    # Elsewhere a bearer token is a user's session or access token, never an agent key.
    if request.path.startswith("/v1/"):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            keys.append(auth[7:])
    return [key for key in keys if isinstance(key, str)]


def enforce_agent_origin():
    """Flask ``before_request`` hook: refuse a request whose agent key refuses its origin."""
    if request.method == "OPTIONS":
        return None
    refusal = origin_refusal(_flask_request_keys(), request.headers, request.host_url)
    if refusal is None:
        return None
    message, status = refusal
    if request.path.startswith("/v1/"):
        error_type = "permission_error" if status == 403 else "server_error"
        body = {"error": {"message": message, "type": error_type}}
    else:
        body = {"success": False, "message": message}
    return make_response(jsonify(body), status)
