"""The client's real address behind reverse proxies and Cloudflare.

Every IP the app records (audit rows, a token's last-used address, the access
log) comes from the ASGI ``client``. Behind a proxy that is the proxy's own
address, typically a 10.x container or ingress hop. :class:`ClientAddressMiddleware`
rewrites it from ``X-Forwarded-For`` when the request arrives through a trusted
proxy, walking the header right to left and stopping at the first address it does
not trust, so a client cannot spoof the leftmost entries. It uses only the standard
library, so settings can import it for validation. With
``TRUST_CF_CONNECTING_IP`` it also takes ``CF-Connecting-IP``, but only when that
walk ends on a Cloudflare address, so a request that bypasses Cloudflare cannot
set it.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING, Iterable, Optional, Union

if TYPE_CHECKING:  # settings import this module; keep it free of ASGI dependencies at runtime
    from starlette.types import ASGIApp, Receive, Scope, Send

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


_Network = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]
_Address = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]


def _parse_address(value: str) -> Optional[_Address]:
    """An IP from a forwarded entry (``1.2.3.4``, ``1.2.3.4:80``, ``::1``, ``[::1]:443``), or None."""
    value = value.strip()
    if value.startswith("["):
        value = value[1 : value.find("]")] if "]" in value else ""
    elif value.count(":") == 1:
        value = value.split(":", 1)[0]
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _in(address: _Address, networks: tuple[_Network, ...]) -> bool:
    return any(address.version == net.version and address in net for net in networks)


def _header_values(scope: Scope, name: bytes) -> list[str]:
    return [value.decode("latin1") for key, value in scope.get("headers", ()) if key == name]


def _cf_connecting_ip(scope: Scope) -> Optional[_Address]:
    values = _header_values(scope, b"cf-connecting-ip")
    return _parse_address(values[0]) if len(values) == 1 else None


class ClientAddressMiddleware:
    """Resolve the ASGI ``client`` from forwarding headers set by trusted proxies.

    Starting at the peer, each hop that is a trusted proxy hands over to the
    ``X-Forwarded-For`` entry it appended, right to left; the first untrusted
    hop is the client. With ``trust_cf_connecting_ip``, reaching a Cloudflare
    hop ends the walk at ``CF-Connecting-IP`` instead. An entry that is not an
    IP (``unknown``) breaks the chain, and the last valid hop is kept. A
    trusted peer's ``X-Forwarded-Proto`` sets the scheme.
    """

    def __init__(
        self,
        app: ASGIApp,
        trusted_proxies: Optional[Iterable[str]] = None,
        trust_cf_connecting_ip: Optional[bool] = None,
    ) -> None:
        """Read the trust rules from explicit values, or from settings when omitted.

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
        self.app = app
        self._trust_all = trusted == ["*"]
        self._trusted: tuple[_Network, ...] = (
            () if self._trust_all else tuple(ipaddress.ip_network(net) for net in trusted)
        )
        self._trust_cf = bool(trust_cf_connecting_ip)

    def _is_trusted(self, address: _Address) -> bool:
        return self._trust_all or _in(address, self._trusted)

    def _resolve(self, peer: _Address, scope: Scope) -> _Address:
        forwarded = [entry for value in _header_values(scope, b"x-forwarded-for") for entry in value.split(",")]
        if self._trust_all:
            first = _parse_address(forwarded[0]) if forwarded else None
            return first or peer
        current = peer
        for entry in reversed(forwarded):
            if self._trust_cf and _in(current, _CLOUDFLARE):
                break
            if not self._is_trusted(current):
                return current
            nxt = _parse_address(entry)
            if nxt is None:
                return current
            current = nxt
        if self._trust_cf and _in(current, _CLOUDFLARE):
            return _cf_connecting_ip(scope) or current
        return current

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Rewrite ``client`` (and ``scheme``) in place, then call the app."""
        client = scope.get("client") if scope["type"] in ("http", "websocket") else None
        peer = _parse_address(client[0]) if client else None
        if peer is not None:
            resolved = self._resolve(peer, scope)
            if resolved != peer:
                scope["client"] = (str(resolved), 0)
            if self._is_trusted(peer):
                proto = _header_values(scope, b"x-forwarded-proto")
                scheme = proto[-1].strip().lower() if proto else ""
                if scheme in ("http", "https", "ws", "wss"):
                    scope["scheme"] = scheme.replace("http", "ws") if scope["type"] == "websocket" else scheme
        await self.app(scope, receive, send)
