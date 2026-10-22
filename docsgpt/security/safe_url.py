"""SSRF protection for user-supplied OpenAI-compatible base URLs.

This module is the single chokepoint for validating any URL that a user
provides as an OpenAI-compatible ``base_url`` ("Bring Your Own Model").
The backend will later issue outbound HTTP requests to that URL on the
user's behalf, so we must reject anything that could be used to reach
internal-network resources (cloud metadata services, RFC 1918 ranges,
loopback, link-local, etc.).

Four entry points:

* :func:`validate_user_base_url` — called at create/update time on REST
  routes that persist the URL, to give the user immediate feedback.
* :func:`pinned_post` — called at dispatch time when the caller drives
  ``requests`` directly (e.g. the ``/api/models/test`` endpoint).
  Resolves once, dials the IP literal, preserves the original hostname
  in the ``Host`` header and via SNI / cert verification for HTTPS.
* :func:`pinned_httpx_client` — called at dispatch time when the caller
  hands an ``httpx2.Client`` to a third-party SDK (e.g. the OpenAI
  Python SDK via ``OpenAI(http_client=...)``). Same DNS-rebinding
  closure on the httpx transport layer.
* :func:`guarded_async_client` — an ``httpx2.AsyncClient`` for async SDKs
  (MCP) that may send requests to hosts beyond the validated URL: every
  host is checked and pinned on first use.

Why all of them: the OpenAI / httpx ecosystem performs its own DNS lookup
inside ``socket.getaddrinfo`` when a connection opens, so a hostile DNS
server can hand a public IP to the validator and a loopback / link-local
address to the HTTP client. Validate-then-construct-SDK is unsafe; the
pinned variants close that TOCTOU window by resolving exactly once and
dialing the chosen IP literal directly.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit, urlunsplit

# httpx2 (the maintained fork of httpx, by its original author, published by
# Pydantic at github.com/pydantic/httpx2) is what the OpenAI and Anthropic
# SDKs run on; a client built on the old ``httpx`` is rejected at their
# construction. This module uses it only for the pinned clients below — its
# own fetches go through ``requests``.
import anyio
import httpx2 as httpx
import requests
import urllib3
from requests.adapters import HTTPAdapter

# Allowed URL schemes. Anything else (file, gopher, ftp, data, ...) is
# rejected outright because it either bypasses HTTP entirely or enables
# protocol smuggling against the proxy stack.
_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Hostnames that resolve to a loopback / metadata / unspecified address
# but which we want to reject *by name* as well, so the rejection
# message is unambiguous and so we never accidentally call DNS on them.
_BLOCKED_HOSTNAMES: frozenset[str] = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "0.0.0.0",
        "::",
        "::1",
        "ip6-localhost",
        "ip6-loopback",
        # GCP metadata service. AWS/Azure use 169.254.169.254 which the
        # IP-range check below already covers via the link-local range,
        # but Google's hostname does not always resolve to a link-local
        # IP from every VPC, so we hard-deny the string too.
        "metadata.google.internal",
    }
)

# Carrier-grade NAT (RFC 6598). Python's ``ipaddress`` module does NOT
# classify this range as ``is_private``, so we must check it explicitly.
_CGNAT_NETWORK_V4: ipaddress.IPv4Network = ipaddress.IPv4Network("100.64.0.0/10")


class UnsafeUserUrlError(ValueError):
    """Raised when a user-supplied URL fails SSRF validation.

    Subclasses :class:`ValueError` so call sites that already treat
    invalid input as a 400-class error continue to work. The string
    message names the specific reason (scheme, hostname, resolved IP,
    DNS failure, ...) so that it can be surfaced to the user verbatim.
    """


class ResponseTooLargeError(Exception):
    """Raised by :func:`pinned_fetch_bytes` when a response body exceeds
    the caller's byte ceiling (declared via ``Content-Length`` or found
    during the bounded read)."""


def _strip_ipv6_brackets(host: str) -> str:
    """Return ``host`` with surrounding ``[`` / ``]`` removed if present."""

    if host.startswith("[") and host.endswith("]"):
        return host[1:-1]
    return host


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return ``True`` if ``ip`` falls in any range we refuse to dial.

    This is the single source of truth for the IP-range policy:

    * loopback (``127.0.0.0/8``, ``::1``)
    * private (RFC 1918, ULA ``fc00::/7``)
    * link-local (``169.254.0.0/16``, ``fe80::/10``)
    * multicast (``224.0.0.0/4``, ``ff00::/8``)
    * unspecified (``0.0.0.0``, ``::``)
    * reserved (``240.0.0.0/4``, etc.)
    * carrier-grade NAT (``100.64.0.0/10``) — not covered by ``is_private``

    An IPv4-mapped IPv6 address (``::ffff:a.b.c.d``) reaches the IPv4 host on a
    dual-stack socket, so it is judged by the IPv4 address it carries.
    """

    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    ):
        return True
    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT_NETWORK_V4:
        return True
    return False


def _resolve(host: str) -> Iterable[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve ``host`` to every A/AAAA record returned by the system.

    Returning *all* addresses (rather than the first one) is critical:
    a hostile DNS server can return a public IP first followed by a
    private IP, and the underlying HTTP client may fail over to the
    private one on connect. We treat the set as unsafe if any element
    is unsafe.
    """

    try:
        results = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:  # noqa: PERF203 — re-raise as our own type
        raise UnsafeUserUrlError(f"could not resolve hostname {host!r}: {exc}") from exc

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for entry in results:
        sockaddr = entry[4]
        # IPv4 sockaddr: (host, port). IPv6 sockaddr: (host, port, flowinfo, scope_id).
        ip_str = sockaddr[0]
        # Strip IPv6 zone-id ("fe80::1%lo0") before parsing.
        if "%" in ip_str:
            ip_str = ip_str.split("%", 1)[0]
        try:
            addresses.append(ipaddress.ip_address(ip_str))
        except ValueError:
            # An entry we can't parse is itself suspicious; treat as unsafe.
            raise UnsafeUserUrlError(
                f"hostname {host!r} resolved to unparseable address {ip_str!r}"
            ) from None
    return addresses


def _urllib3_host(url: str) -> str | None:
    """Host of ``url`` as urllib3 reads it, or ``None`` if it cannot parse it."""

    try:
        return urllib3.util.parse_url(url).host
    except urllib3.exceptions.LocationParseError:
        return None


def reject_ambiguous_url(url: str) -> None:
    """Refuse a URL whose host the HTTP libraries could read differently from ``urlsplit``.

    The SSRF guard checks the host ``urlsplit`` finds, but ``requests`` and
    ``boto`` dial the host urllib3 finds. For ``http://127.0.0.1\\@1.1.1.1``
    ``urlsplit`` reads ``1.1.1.1`` (``127.0.0.1\\`` as userinfo) while urllib3
    ends the authority at the backslash and dials ``127.0.0.1``. ``urlsplit``
    also silently drops tabs and newlines that other parsers keep.

    Raises:
        UnsafeUserUrlError: If the URL contains control characters, a
            backslash or whitespace in its authority, or a host urllib3
            reads differently.
    """

    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in url):
        raise UnsafeUserUrlError(f"url {url!r} contains control characters")
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError as exc:
        raise UnsafeUserUrlError(f"could not parse url {url!r}: {exc}") from exc
    if "\\" in parts.netloc or any(ch.isspace() for ch in parts.netloc):
        raise UnsafeUserUrlError(f"url {url!r} has a backslash or whitespace in its host part")
    if not host:
        return
    # Re-parse the host urlsplit found so both sides get urllib3's spelling
    # (IDNA, brackets, case) before they are compared.
    bracketed = f"[{host}]" if ":" in host else host
    expected = _urllib3_host(f"{parts.scheme}://{bracketed}/")
    actual = _urllib3_host(url)
    if expected is None or expected != actual:
        raise UnsafeUserUrlError(f"url {url!r} names its host ambiguously ({host!r} vs {actual!r})")


def _validate_and_pick_ip(
    url: str,
) -> tuple[str, ipaddress.IPv4Address | ipaddress.IPv6Address, "urlsplit"]:
    """Run the SSRF guard and return the data needed to dial safely.

    Performs every check :func:`validate_user_base_url` performs, but
    additionally returns ``(hostname, ip, parts)`` where ``ip`` is one
    of the validated addresses (the first record returned by the
    resolver, or the literal itself if the URL already used an IP) and
    ``parts`` is the :func:`urllib.parse.urlsplit` result so callers do
    not have to re-parse the URL.

    Raises :class:`UnsafeUserUrlError` on the same conditions as
    :func:`validate_user_base_url`.
    """

    if not isinstance(url, str) or not url.strip():
        raise UnsafeUserUrlError("url must be a non-empty string")

    reject_ambiguous_url(url)
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise UnsafeUserUrlError(f"could not parse url {url!r}: {exc}") from exc

    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUserUrlError(
            f"scheme {scheme!r} is not allowed; only http and https are permitted"
        )

    # ``urlsplit`` returns the bracketed form for IPv6 in ``netloc`` but
    # the bare form in ``hostname``. Normalize via lower() because
    # hostnames are case-insensitive and we compare against a lowercase
    # blocklist.
    raw_host = parts.hostname
    if not raw_host:
        raise UnsafeUserUrlError(f"url {url!r} has no hostname")

    host = raw_host.lower()

    # Check the literal-string blocklist first. urlsplit().hostname strips
    # IPv6 brackets, so we also test the bracketed form for completeness
    # (matches the public-spec note about ``[::]``).
    bracketed = f"[{host}]"
    if host in _BLOCKED_HOSTNAMES or bracketed in _BLOCKED_HOSTNAMES:
        raise UnsafeUserUrlError(
            f"hostname {raw_host!r} is not allowed (matches internal-only name)"
        )

    # If the host is already an IP literal (with or without IPv6 brackets),
    # check it directly without going to DNS — DNS for an IP literal is a
    # no-op but it's clearer to short-circuit and gives a better message.
    candidate = _strip_ipv6_brackets(host)
    try:
        literal = ipaddress.ip_address(candidate)
    except ValueError:
        literal = None

    if literal is not None:
        if _is_blocked_ip(literal):
            raise UnsafeUserUrlError(
                f"hostname {raw_host!r} resolves to blocked address {literal} "
                f"(loopback/private/link-local/multicast/reserved/CGNAT)"
            )
        return host, literal, parts

    # Hostname (not an IP literal) — resolve and validate every record.
    addresses = list(_resolve(host))
    for ip in addresses:
        if _is_blocked_ip(ip):
            raise UnsafeUserUrlError(
                f"hostname {raw_host!r} resolves to blocked address {ip} "
                f"(loopback/private/link-local/multicast/reserved/CGNAT)"
            )
    if not addresses:
        # ``getaddrinfo`` would normally raise instead of returning an
        # empty list, but treat the degenerate case as unsafe too — we
        # have nothing to bind a connection to.
        raise UnsafeUserUrlError(
            f"hostname {raw_host!r} returned no addresses from DNS"
        )
    return host, addresses[0], parts


def validate_user_base_url(url: str) -> None:
    """Validate that ``url`` is safe to use as an outbound base URL.

    Resolve the URL's hostname to one or more IPs and reject if any
    resolved IP is private/loopback/link-local/multicast/reserved, or if
    the URL uses a non-http(s) scheme, or if the hostname is one of the
    known dangerous strings (``localhost``, ``0.0.0.0``, ``[::]``).

    Raises :class:`UnsafeUserUrlError` on rejection. Returns ``None`` on
    success.

    This function is the create/update-time check. At dispatch time use
    :func:`pinned_post` instead, which performs the same validation
    *and* pins the outbound connection to the validated IP so a DNS
    rebinder cannot flip the resolution between check and connect.

    Args:
        url: The user-supplied URL to validate. Expected to be an
            absolute URL with an ``http`` or ``https`` scheme.

    Raises:
        UnsafeUserUrlError: If the URL fails to parse, uses a forbidden
            scheme, has an empty/blocklisted hostname, fails DNS
            resolution, or resolves to any IP in a blocked range.
    """

    _validate_and_pick_ip(url)


class _PinnedHostAdapter(HTTPAdapter):
    """HTTPS adapter that performs SNI and cert verification against a
    fixed hostname even when the URL connects to an IP literal.

    Used by :func:`pinned_post` so that resolving the user-supplied
    hostname once and dialing the resolved IP doesn't break TLS.
    Without this, ``urllib3`` would default ``server_hostname`` /
    ``assert_hostname`` to the connect host (the IP) and either send the
    wrong SNI or fail cert verification — the cert is for the original
    hostname, not the IP literal.
    """

    def __init__(self, server_hostname: str, *args: Any, **kwargs: Any) -> None:
        self._server_hostname = server_hostname
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        kwargs["server_hostname"] = self._server_hostname
        kwargs["assert_hostname"] = self._server_hostname
        super().init_poolmanager(*args, **kwargs)


def _ip_to_url_host(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """Return ``ip`` formatted for use in a URL netloc (brackets for v6)."""

    if isinstance(ip, ipaddress.IPv6Address):
        return f"[{ip}]"
    return str(ip)


def _pinned_session(
    url: str, headers: dict[str, str] | None
) -> tuple[requests.Session, str, dict[str, str]]:
    """Run the SSRF guard once and build a session pinned to the chosen IP.

    Single home for the pinning preamble (validate/pick IP, netloc rewrite,
    ``Host`` header, HTTPS adapter mount) shared by :func:`pinned_request`
    and :func:`pinned_fetch_bytes`, so the guard cannot drift between them.

    Returns:
        Tuple of the session (caller must close it), the IP-literal URL,
        and the request headers carrying the original ``Host``.

    Raises:
        UnsafeUserUrlError: If the URL fails the SSRF guard.
    """

    host, ip, parts = _validate_and_pick_ip(url)

    # The dialed URL is rebuilt from the validated IP alone: userinfo is sent
    # as Basic auth, never copied, so no user-written authority text reaches
    # the parser that picks the connect host.
    netloc = _ip_to_url_host(ip)
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    pinned_url = urlunsplit(
        (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
    )

    request_headers = dict(headers or {})
    host_header = host if parts.port is None else f"{host}:{parts.port}"
    request_headers["Host"] = host_header

    session = requests.Session()
    if parts.username is not None:
        session.auth = (unquote(parts.username), unquote(parts.password or ""))
    if parts.scheme == "https":
        session.mount("https://", _PinnedHostAdapter(host))
    return session, pinned_url, request_headers


def pinned_request(
    method: str,
    url: str,
    *,
    data: Any = None,
    json: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float = 90.0,
    allow_redirects: bool = False,
) -> requests.Response:
    """Send an HTTP request with the connection pinned to a validated IP,
    closing the DNS-rebinding TOCTOU window left by the naive
    validate-then-``requests`` pattern.

    Raises:
        UnsafeUserUrlError: If the URL fails the SSRF guard.
        requests.RequestException: For network-level failures.
    """

    session, pinned_url, request_headers = _pinned_session(url, headers)
    try:
        return session.request(
            method=method.upper(),
            url=pinned_url,
            data=data,
            json=json,
            headers=request_headers,
            timeout=timeout,
            allow_redirects=allow_redirects,
        )
    finally:
        session.close()


def pinned_fetch_bytes(
    url: str,
    *,
    max_bytes: int,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    allow_redirects: bool = False,
    truncate: bool = False,
) -> tuple[bytes, requests.Response]:
    """GET ``url`` with SSRF pinning, streaming at most ``max_bytes`` of body.

    The size limit is enforced twice: a declared ``Content-Length`` above
    the ceiling is rejected before any body is read, and the streamed
    read itself stops the moment the ceiling is crossed — a server that
    lies about (or omits) ``Content-Length`` cannot bypass the cap. With
    ``truncate`` the read stops at the ceiling and returns the first
    ``max_bytes`` instead of raising (a page watched for changes).

    Returns:
        Tuple of the body bytes and the (already-closed) ``Response``,
        kept for its status code and headers.

    Raises:
        UnsafeUserUrlError: If the URL fails the SSRF guard.
        ResponseTooLargeError: If the body exceeds ``max_bytes``.
        requests.RequestException: For network-level failures.
    """

    session, pinned_url, request_headers = _pinned_session(url, headers)
    try:
        response = session.request(
            method="GET",
            url=pinned_url,
            headers=request_headers,
            timeout=timeout,
            allow_redirects=allow_redirects,
            stream=True,
        )
        try:
            # An error response's body is never used (callers
            # raise_for_status) — skip the transfer and let the caller
            # surface the more informative HTTP-status error.
            if response.status_code >= 400:
                return b"", response
            declared = response.headers.get("Content-Length")
            if not truncate and declared and declared.isdigit() and int(declared) > max_bytes:
                raise ResponseTooLargeError(
                    f"response declares {declared} bytes, over the "
                    f"{max_bytes}-byte limit"
                )
            chunks: list[bytes] = []
            received = 0
            for chunk in response.iter_content(chunk_size=65536):
                received += len(chunk)
                if received > max_bytes and truncate:
                    chunks.append(chunk[: max_bytes - (received - len(chunk))])
                    break
                if received > max_bytes:
                    raise ResponseTooLargeError(
                        f"response body exceeds the {max_bytes}-byte limit"
                    )
                chunks.append(chunk)
            return b"".join(chunks), response
        finally:
            response.close()
    finally:
        session.close()


def pinned_post(
    url: str,
    *,
    json: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float = 5.0,
    allow_redirects: bool = False,
) -> requests.Response:
    """POST to ``url`` with the outbound connection pinned to a single
    validated IP, closing the DNS-rebinding TOCTOU window left by the
    naive validate-then-``requests.post`` pattern.

    The URL's hostname is resolved exactly once. Every returned address
    must pass the same SSRF guard as :func:`validate_user_base_url`. The
    outbound request is issued against the chosen IP literal (so
    ``urllib3`` cannot ask the resolver again and receive a different
    answer); the original hostname is preserved in the ``Host`` header
    and, for HTTPS, via :class:`_PinnedHostAdapter` for SNI and cert
    verification.

    Args:
        url: Absolute http(s) URL to POST to.
        json: JSON-serializable payload — passed through to ``requests``.
        headers: Caller-supplied headers. Any caller-supplied ``Host``
            entry is overwritten so the in-flight request matches what
            was validated.
        timeout: Per-request timeout (seconds).
        allow_redirects: Forwarded to ``requests``. Defaults to
            ``False`` because the SSRF guard only inspects the supplied
            URL — following redirects would let a hostile upstream
            bounce the request to an internal address.

    Raises:
        UnsafeUserUrlError: If the URL fails the SSRF guard.
        requests.RequestException: For network-level failures.
    """

    return pinned_request(
        "POST",
        url,
        json=json,
        headers=headers,
        timeout=timeout,
        allow_redirects=allow_redirects,
    )


class _PinnedHTTPSTransport(httpx.HTTPTransport):
    """``httpx`` transport pinned to a single validated IP literal.

    Closes the DNS-rebinding TOCTOU window that
    :func:`validate_user_base_url` cannot close on its own. The OpenAI
    Python SDK (and any other SDK that uses ``httpx``) re-resolves the
    hostname inside ``socket.getaddrinfo`` at request time, so a
    hostile DNS server can return a public IP at validation time and a
    private IP at request time. This transport rewrites every outgoing
    request's URL host to the validated IP literal so ``httpcore``
    dials that IP without a fresh lookup.

    The original hostname is preserved in two places:

    1. ``Host`` header — ``httpx.Request._prepare`` set it from the URL
       netloc *before* this transport runs, so it carries the hostname
       not the IP literal. We deliberately do not touch headers here.
    2. TLS SNI / cert verification — set via the
       ``request.extensions["sni_hostname"]`` extension which
       ``httpcore`` feeds into ``start_tls``'s ``server_hostname``
       parameter. Without this, ``urllib3``-equivalent code would use
       the IP literal as SNI and cert verification would fail (the
       cert is for the original hostname, not the IP). It must be a
       ``str``: ``httpcore`` passes it through to
       ``ssl.SSLContext.wrap_socket``, and the ``truststore`` backend
       httpx2 uses on macOS encodes it rather than accepting bytes.
    """

    def __init__(
        self,
        validated_host: str,
        validated_ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
        **kwargs: Any,
    ) -> None:
        # http2=False (the httpx default) — defense in depth against
        # HTTP/2 connection coalescing (RFC 7540 §9.1.1), where a
        # client may reuse a TCP connection for any host whose cert
        # covers it. Per-IP pinning never shares connections across
        # hosts, but explicit is safer than relying on the default.
        kwargs.setdefault("http2", False)
        super().__init__(**kwargs)
        self._host = validated_host
        self._ip_netloc = _ip_to_url_host(validated_ip)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        # Defense in depth: refuse if the request URL's host doesn't
        # match what we validated. Catches any future SDK regression
        # that rewrites the URL between Request construction and dial,
        # and any rare case where the SDK reuses our pinned client for
        # a different host (which it shouldn't, but assert it anyway).
        if request.url.host != self._host:
            raise UnsafeUserUrlError(
                f"pinned transport bound to {self._host!r}, refused "
                f"request for {request.url.host!r}"
            )
        # SNI/server_hostname for TLS verification. httpcore reads this
        # extension at _sync/connection.py and feeds it into
        # start_tls's server_hostname argument. Set before the URL host
        # is rewritten so cert validation continues to use the original
        # hostname even though TCP dials the IP literal.
        request.extensions = {
            **request.extensions,
            "sni_hostname": self._host,
        }
        request.url = request.url.copy_with(host=self._ip_netloc)
        return super().handle_request(request)


def pinned_httpx_client(
    base_url: str,
    *,
    timeout: float = 600.0,
) -> httpx.Client:
    """Return an :class:`httpx.Client` whose connections are pinned to
    one validated IP, closing the DNS-rebinding TOCTOU window the naive
    ``OpenAI(base_url=...)`` flow leaves open.

    The hostname in ``base_url`` is resolved exactly once. Every
    returned address must pass :func:`_validate_and_pick_ip`'s SSRF
    guard (loopback, RFC 1918, link-local, multicast, reserved, CGNAT,
    cloud metadata names). The chosen IP becomes the URL host on every
    outgoing request so ``httpcore`` cannot ask the resolver again.

    Pass via ``OpenAI(http_client=pinned_httpx_client(base_url))`` (or
    any other SDK that accepts an ``httpx.Client``) to make BYOM
    dispatch immune to DNS-rebinding TOCTOU.

    Args:
        base_url: User-supplied http(s) URL. Validated through the same
            SSRF guard as :func:`validate_user_base_url`.
        timeout: Per-request timeout (seconds). Defaults to 600 to
            match the OpenAI SDK's default; callers should override
            for non-LLM workloads.

    Raises:
        UnsafeUserUrlError: If ``base_url`` fails the SSRF guard.
    """

    host, ip, _parts = _validate_and_pick_ip(base_url)
    transport = _PinnedHTTPSTransport(host, ip)
    # follow_redirects=False — the SSRF guard only inspects the
    # supplied URL; following 3xx would let a hostile upstream bounce
    # the in-network request to an internal address (cloud metadata,
    # RFC1918, loopback) carrying whatever credentials the SDK adds.
    return httpx.Client(
        transport=transport,
        timeout=timeout,
        follow_redirects=False,
    )


class _GuardedAsyncTransport(httpx.AsyncBaseTransport):
    """Async ``httpx`` transport that runs the SSRF guard on every host it is sent to.

    Unlike :class:`_PinnedHTTPSTransport` it is not bound to one host: SDKs
    such as MCP's send OAuth discovery and token requests to hosts the remote
    server names, so each new host is validated (every DNS answer) on first
    use and pinned to the chosen IP for the transport's lifetime. The dial
    goes to that IP literal; the ``Host`` header and TLS SNI keep the
    hostname. The caller's request is not mutated, so redirect and
    relative-URL handling above the transport still see the hostname.

    Each hostname gets its own connection pool: pooled connections are
    matched on the dialed IP, so hostnames sharing an IP would otherwise
    reuse a TLS connection whose certificate was checked for only one of them.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("http2", False)
        self._transport_kwargs = kwargs
        self._hosts: dict[str, tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, httpx.AsyncHTTPTransport]] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        entry = self._hosts.get(host)
        if entry is None:
            _host, ip, _parts = await anyio.to_thread.run_sync(_validate_and_pick_ip, str(request.url))
            entry = self._hosts.setdefault(host, (ip, httpx.AsyncHTTPTransport(**self._transport_kwargs)))
        ip, transport = entry
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=_ip_to_url_host(ip)),
            headers=request.headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": host},
        )
        return await transport.handle_async_request(pinned)

    async def aclose(self) -> None:
        for _ip, transport in self._hosts.values():
            await transport.aclose()


def guarded_async_client(
    *,
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | float | None = 30.0,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """Return an :class:`httpx.AsyncClient` that SSRF-checks and pins every host it dials.

    For async SDKs that take a client factory and may send requests beyond
    the URL validated up front (MCP transports and their OAuth flows).
    Redirects are not followed; env proxies are not used, since passing a
    transport turns them off in ``httpx``.

    Args:
        headers: Default headers for every request.
        timeout: Client timeout.
        auth: Optional ``httpx`` auth flow; its own requests go through the
            same guarded transport.
    """

    return httpx.AsyncClient(
        transport=_GuardedAsyncTransport(),
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=False,
    )
