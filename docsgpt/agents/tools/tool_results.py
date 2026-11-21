"""Canonical builders for tool result payloads.

``ToolExecutor.result_status`` classifies a returned payload as a failure
only when it carries an in-band marker: ``status: "error"``, a truthy
``error`` key, or an integer ``status_code >= 400``. Hand-writing error
dicts at every failure site makes that contract easy to forget — issue
#3288 was exactly that: ``APITool._make_api_call`` returned 3xx-redirect,
timeout, connection and URL-validation payloads without any marker, so the
executor journaled failed tool calls as ``completed``.

Tools should build every failure result through :func:`tool_error` so the
marker is present by construction, and echo redirect targets through
:func:`strip_userinfo` so configured credentials never leak into the
model-visible conversation.
"""

from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit


def tool_error(
    message: str,
    *,
    status_code: Optional[int] = None,
    data: Any = None,
) -> Dict[str, Any]:
    """Build the canonical in-band error payload for a tool result.

    Args:
        message: Human- and model-readable failure description.
        status_code: HTTP status code when the failure came from a response.
        data: Any response payload worth showing (parsed error body, text).

    Both ``error`` and ``message`` carry the same text: ``error`` because
    ``result_status`` and the ntfy tool's historical shape key off it,
    ``message`` because the API tool's historical shape does.
    """
    return {
        "status": "error",
        "error": message,
        "message": message,
        "status_code": status_code,
        "data": data,
    }


def strip_userinfo(url: str) -> str:
    """Remove ``user:password`` userinfo from a URL.

    Redirect targets are echoed back into the model-visible result so the
    agent can fetch them directly; without this, credentials embedded in
    the configured URL (or in the ``Location`` header itself) would leak
    into the conversation. IPv6 hostnames are re-bracketed since
    ``urlsplit`` strips the brackets from ``hostname``.
    """
    parsed = urlsplit(url)
    if parsed.username or parsed.password:
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = host
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return urlunsplit(
            (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
        )
    return url
