"""The client's real address behind reverse proxies and Cloudflare.

Every IP the app records (audit rows, a token's last-used address, the access
log) comes from the ASGI ``client``. Behind a proxy that is the proxy's own
address, typically a 10.x container or ingress hop. :class:`ClientAddressMiddleware`
rewrites it from ``X-Forwarded-For`` when the request arrives through a trusted
proxy, walking the header right to left and stopping at the first address it does
not trust, so a client cannot spoof the leftmost entries. With
``TRUST_CF_CONNECTING_IP`` it also takes ``CF-Connecting-IP``, but only when that
walk ends on a Cloudflare address, so a request that bypasses Cloudflare cannot
set it.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from typing import Iterable, Optional

from starlette.types import ASGIApp, Receive, Scope, Send
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

PRIVATE_NETWORKS: tuple[str, ...] = (
    "127.0.0.0/8",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "fc00::/7",
)

# https://www.cloudflare.com/ips-v4 and /ips-v6 (fetched 2026-11-11).
CLOUDFLARE_NETWORKS: tuple[str, ...] = (
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
)

_KEYWORDS: dict[str, tuple[str, ...]] = {"private": PRIVATE_NETWORKS, "cloudflare": CLOUDFLARE_NETWORKS}

_CLOUDFLARE = tuple(ipaddress.ip_network(net) for net in CLOUDFLARE_NETWORKS)


def expand_trusted_proxies(entries: Iterable[str]) -> list[str]:
    """Expand ``private`` and ``cloudflare`` into networks and validate the rest.

    Args:
        entries: IPs, CIDR ranges, the keywords, or ``*`` alone (trust every peer).

    Returns:
        Normalized networks, deduplicated in order; ``["*"]`` for ``*``.

    Raises:
        ValueError: An entry is not an IP, a range or a keyword, or ``*`` is mixed with others.
    """
    cleaned = [entry.strip() for entry in entries if entry and entry.strip()]
    if "*" in cleaned:
        if len(cleaned) > 1:
            raise ValueError("TRUSTED_PROXIES: '*' trusts every peer and cannot be combined with other entries")
        return ["*"]
    networks: list[str] = []
    for entry in cleaned:
        for value in _KEYWORDS.get(entry.lower(), (entry,)):
            try:
                network = str(ipaddress.ip_network(value, strict=False))
            except ValueError as exc:
                raise ValueError(
                    f"TRUSTED_PROXIES: {entry!r} is not an IP, a CIDR range, 'private', 'cloudflare' or '*'"
                ) from exc
            if network not in networks:
                networks.append(network)
    return networks


@lru_cache(maxsize=4096)
def _is_cloudflare(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in network for network in _CLOUDFLARE)


def _cf_connecting_ip(scope: Scope) -> Optional[str]:
    values = [value for name, value in scope.get("headers", ()) if name == b"cf-connecting-ip"]
    if len(values) != 1:
        return None
    try:
        return str(ipaddress.ip_address(values[0].decode("latin1").strip()))
    except ValueError:
        return None


class _CloudflareClientIP:
    """Take ``CF-Connecting-IP`` as the client when the request came from Cloudflare."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            if client and _is_cloudflare(client[0]):
                real = _cf_connecting_ip(scope)
                if real:
                    scope["client"] = (real, 0)
        await self.app(scope, receive, send)


class ClientAddressMiddleware:
    """Resolve the ASGI ``client`` from forwarding headers set by trusted proxies.

    Also applies ``X-Forwarded-Proto`` from a trusted proxy to the scope's scheme.
    """

    def __init__(
        self,
        app: ASGIApp,
        trusted_proxies: Optional[Iterable[str]] = None,
        trust_cf_connecting_ip: Optional[bool] = None,
    ) -> None:
        """Build the chain from explicit values, or from settings when omitted.

        Args:
            app: The wrapped ASGI app.
            trusted_proxies: ``TRUSTED_PROXIES`` entries; settings when None.
            trust_cf_connecting_ip: ``TRUST_CF_CONNECTING_IP``; settings when None.
        """
        if trusted_proxies is None or trust_cf_connecting_ip is None:
            from docsgpt.core.settings import settings

            if trusted_proxies is None:
                trusted_proxies = settings.TRUSTED_PROXIES
            if trust_cf_connecting_ip is None:
                trust_cf_connecting_ip = settings.TRUST_CF_CONNECTING_IP
        trusted = expand_trusted_proxies(trusted_proxies)
        handler: ASGIApp = _CloudflareClientIP(app) if trust_cf_connecting_ip else app
        if trusted:
            handler = ProxyHeadersMiddleware(handler, trusted_hosts=trusted)
        self.app = app
        self._handler = handler

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._handler(scope, receive, send)
