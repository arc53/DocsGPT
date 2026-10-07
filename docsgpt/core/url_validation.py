"""
URL validation utilities to prevent SSRF (Server-Side Request Forgery) attacks.

This module provides functions to validate URLs before making HTTP requests,
blocking access to internal networks, cloud metadata services, and other
potentially dangerous endpoints.
"""

import ipaddress
import socket
from urllib.parse import urlparse
from typing import Optional, Set

from docsgpt.security.safe_url import reject_ambiguous_url


class SSRFError(Exception):
    """Raised when a URL fails SSRF validation."""
    pass


# Blocked hostnames that should never be accessed
BLOCKED_HOSTNAMES: Set[str] = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
}

# Cloud metadata IP addresses (AWS, GCP, Azure, etc.)
METADATA_IPS: Set[str] = {
    "169.254.169.254",  # AWS, GCP, Azure metadata
    "169.254.170.2",    # AWS ECS task metadata
    "fd00:ec2::254",    # AWS IPv6 metadata
}

# Allowed schemes for external requests
ALLOWED_SCHEMES: Set[str] = {"http", "https"}

# Carrier-grade NAT (RFC 6598). Python's ``ipaddress`` does not count it as
# ``is_private``, so it is checked on its own, as in docsgpt/security/safe_url.py.
CGNAT_NETWORK_V4 = ipaddress.IPv4Network("100.64.0.0/10")


def _unwrap_ipv4_mapped(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Return the IPv4 address an IPv4-mapped IPv6 address carries.

    ``::ffff:a.b.c.d`` reaches ``a.b.c.d`` on a dual-stack socket, so it is
    judged by the IPv4 rules (the CGNAT range among them).

    Args:
        ip: A parsed IPv4 or IPv6 address.

    Returns:
        The embedded IPv4 address for ``::ffff:0:0/96``, otherwise ``ip``.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def is_private_ip(ip_str: str) -> bool:
    """
    Check if an IP address is private, loopback, link-local, reserved,
    multicast, unspecified or carrier-grade NAT.

    Args:
        ip_str: IP address as a string

    Returns:
        True if the IP is private/internal, False otherwise
    """
    try:
        ip = _unwrap_ipv4_mapped(ipaddress.ip_address(ip_str))
        return (
            ip.is_private or
            ip.is_loopback or
            ip.is_link_local or
            ip.is_reserved or
            ip.is_multicast or
            ip.is_unspecified or
            (isinstance(ip, ipaddress.IPv4Address) and ip in CGNAT_NETWORK_V4)
        )
    except ValueError:
        # If we can't parse it as an IP, return False
        return False


def is_metadata_ip(ip_str: str) -> bool:
    """
    Check if an IP address is a cloud metadata service IP, in any spelling
    (IPv4-mapped IPv6, or an IPv6 address written out differently).

    Args:
        ip_str: IP address as a string

    Returns:
        True if the IP is a metadata service, False otherwise
    """
    try:
        return str(_unwrap_ipv4_mapped(ipaddress.ip_address(ip_str))) in METADATA_IPS
    except ValueError:
        return ip_str in METADATA_IPS


def resolve_hostname(hostname: str) -> Optional[str]:
    """
    Resolve a hostname to an IP address.

    Args:
        hostname: The hostname to resolve

    Returns:
        The resolved IP address, or None if resolution fails
    """
    try:
        return socket.gethostbyname(hostname)
    except socket.gaierror:
        return None


def validate_url(url: str, allow_localhost: bool = False) -> str:
    """
    Validate a URL to prevent SSRF attacks.

    This function checks that:
    1. The URL has an allowed scheme (http or https)
    2. The hostname is not a blocked hostname
    3. The resolved IP is not a private/internal IP
    4. The resolved IP is not a cloud metadata service

    Args:
        url: The URL to validate
        allow_localhost: If True, allow localhost connections (for testing only)

    Returns:
        The validated URL (with scheme added if missing)

    Raises:
        SSRFError: If the URL fails validation
    """
    if not url or not isinstance(url, str):
        raise SSRFError("No URL was provided.")
    # ``urlparse`` and ``.hostname`` raise ValueError on malformed input such
    # as an unclosed IPv6 bracket (``http://[bad``); callers only catch SSRFError.
    try:
        # Ensure URL has a scheme
        if not urlparse(url).scheme:
            url = "http://" + url
        # The host checked below must be the one requests/boto will dial.
        reject_ambiguous_url(url)

        parsed = urlparse(url)
        hostname = parsed.hostname
    except ValueError as e:
        raise SSRFError(f"Invalid URL: {e}") from e

    # Check scheme
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise SSRFError(f"URL scheme '{parsed.scheme}' is not allowed. Only HTTP(S) is permitted.")

    if not hostname:
        raise SSRFError("URL must have a valid hostname.")

    hostname_lower = hostname.lower()

    # Check blocked hostnames
    if hostname_lower in BLOCKED_HOSTNAMES and not allow_localhost:
        raise SSRFError(f"Access to '{hostname}' is not allowed.")

    # Check if hostname is an IP address directly
    try:
        ip = ipaddress.ip_address(hostname)
        ip_str = str(ip)

        if is_metadata_ip(ip_str):
            raise SSRFError("Access to cloud metadata services is not allowed.")

        if is_private_ip(ip_str) and not allow_localhost:
            raise SSRFError("Access to private/internal IP addresses is not allowed.")

        return url
    except ValueError:
        # Not an IP address, it's a hostname - resolve it
        pass

    # Resolve hostname and check the IP
    resolved_ip = resolve_hostname(hostname)
    if resolved_ip is None:
        raise SSRFError(f"Unable to resolve hostname: {hostname}")

    if is_metadata_ip(resolved_ip):
        raise SSRFError("Access to cloud metadata services is not allowed.")

    if is_private_ip(resolved_ip) and not allow_localhost:
        raise SSRFError("Access to private/internal networks is not allowed.")

    return url


def validate_url_safe(url: str, allow_localhost: bool = False) -> tuple[bool, str, Optional[str]]:
    """
    Validate a URL and return a tuple with validation result.

    This is a non-throwing version of validate_url for cases where
    you want to handle validation failures gracefully.

    Args:
        url: The URL to validate
        allow_localhost: If True, allow localhost connections (for testing only)

    Returns:
        Tuple of (is_valid, validated_url_or_original, error_message_or_none)
    """
    try:
        validated = validate_url(url, allow_localhost)
        return (True, validated, None)
    except SSRFError as e:
        return (False, url, str(e))
