"""Browser origins: normalizing them and reading the one a request came from.

An origin is ``scheme://host[:port]``, the unit browsers send in the ``Origin``
header. Everything here compares origins in one canonical form: lowercase
scheme and host, the default port dropped, no path. Browsers already send
hosts in that form (an internationalized host as punycode), so a stored entry
and a request header match by plain string equality.
"""

from __future__ import annotations

from typing import Mapping, Optional
from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# Where ``npm run dev`` serves the frontend.
DEV_FRONTEND_PORT = 5173


def normalize_origin(url: Optional[str]) -> Optional[str]:
    """Normalized ``scheme://host[:port]`` origin of an http(s) URL, or None.

    Lenient: any path, query or fragment is ignored, so a full URL (a
    ``Referer`` header, a configured callback URL) yields its origin.

    Args:
        url: An origin or a full URL.

    Returns:
        The origin, or None when ``url`` is empty, not http(s) or has no host.
    """
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname
    if parts.scheme not in _DEFAULT_PORTS or not host:
        return None
    if ":" in host:
        host = f"[{host}]"
    if port is None or port == _DEFAULT_PORTS[parts.scheme]:
        return f"{parts.scheme}://{host}"
    return f"{parts.scheme}://{host}:{port}"


def canonical_origin(value: str) -> str:
    """Validate an origin a person typed and return its canonical form.

    Strict, unlike :func:`normalize_origin`: a path, query, fragment,
    credentials or wildcard is refused rather than dropped, so what is stored
    is exactly what will be enforced. A trailing ``/`` is accepted, and an
    internationalized host is converted to the punycode browsers send.

    Args:
        value: The origin as entered, e.g. ``https://Example.com/``.

    Returns:
        The canonical origin, e.g. ``https://example.com``.

    Raises:
        ValueError: With a message naming the entry, when it is not an origin.
    """
    text = str(value or "").strip()
    if not text:
        raise ValueError("an origin cannot be empty")
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise ValueError(f"'{text}' is not a valid origin")
    if parts.scheme not in _DEFAULT_PORTS:
        raise ValueError(f"'{text}' must start with http:// or https://")
    host = parts.hostname
    if not host:
        raise ValueError(f"'{text}' has no host")
    if "*" in host:
        raise ValueError(f"'{text}' contains a wildcard; list each origin separately")
    if parts.username is not None or parts.password is not None:
        raise ValueError(f"'{text}' must not contain credentials")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError(f"'{text}' must be an origin such as https://example.com, without a path")
    if ":" not in host:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            raise ValueError(f"'{text}' has an invalid host")
    else:
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    origin = normalize_origin(f"{parts.scheme}://{netloc}")
    if origin is None:
        raise ValueError(f"'{text}' is not a valid origin")
    return origin


def request_origin(headers: Mapping[str, str]) -> Optional[str]:
    """The origin a browser request came from, or None when it names none.

    ``Origin`` comes first. Browsers leave it off some requests (a plain
    ``GET`` such as an image or a link), so without it the origin of
    ``Referer`` stands in. An opaque ``Origin: null`` (a sandboxed frame, a
    ``file:`` page) names no origin, and the ``Referer`` is not consulted.

    Args:
        headers: The request headers: a case-insensitive mapping (Flask,
            Starlette) or a plain dict with lowercase names (FastMCP).

    Returns:
        The normalized origin, or None.
    """
    origin = _header(headers, "Origin")
    if origin is not None:
        origin = origin.strip()
        if origin and origin.lower() != "null":
            return normalize_origin(origin)
        if origin:
            return None
    return normalize_origin(_header(headers, "Referer"))


def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
    """``headers[name]``, falling back to the lowercase name."""
    value = headers.get(name)
    return value if value is not None else headers.get(name.lower())
