"""SSRF protection for user-supplied OpenAI-compatible base URLs.

This module is the single chokepoint for validating any URL that a user
provides as an OpenAI-compatible ``base_url`` ("Bring Your Own Model").
The backend will later issue outbound HTTP requests to that URL on the
user's behalf, so we must reject anything that could be used to reach
internal-network resources (cloud metadata services, RFC 1918 ranges,
loopback, link-local, etc.).

Three entry points:

* :func:`validate_user_base_url` — called at create/update time on REST
  routes that persist the URL, to give the user immediate feedback.
* :func:`pinned_post` — called at dispatch time when the caller drives
  ``requests`` directly (e.g. the ``/api/models/test`` endpoint).
  Resolves once, dials the IP literal, preserves the original hostname
  in the ``Host`` header and via SNI / cert verification for HTTPS.
* :func:`pinned_httpx_client` — called at dispatch time when the caller
  hands an ``httpx.Client`` to a third-party SDK (e.g. the OpenAI
  Python SDK via ``OpenAI(http_client=...)``). Same DNS-rebinding
  closure on the httpx transport layer.

Why all three: the OpenAI / httpx ecosystem performs its own DNS lookup
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
from urllib.parse import urlsplit, urlunsplit

import httpx
import requests
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
    """

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

    host, ip, parts = _validate_and_pick_ip(url)

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
    if parts.scheme == "https":
        session.mount("https://", _PinnedHostAdapter(host))
    try:
        return session.post(
            pinned_url,
            json=json,
            headers=request_headers,
            timeout=timeout,
            allow_redirects=allow_redirects,
        )
    finally:
        session.close()


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
       cert is for the original hostname, not the IP).
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
            "sni_hostname": self._host.encode("ascii"),
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
