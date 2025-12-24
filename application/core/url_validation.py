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


def is_private_ip(ip_str: str) -> bool:
    """
    Check if an IP address is private, loopback, or link-local.

    Args:
        ip_str: IP address as a string

    Returns:
        True if the IP is private/internal, False otherwise
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private or
            ip.is_loopback or
            ip.is_link_local or
            ip.is_reserved or
            ip.is_multicast or
            ip.is_unspecified
        )
    except ValueError:
        # If we can't parse it as an IP, return False
        return False


def is_metadata_ip(ip_str: str) -> bool:
    """
    Check if an IP address is a cloud metadata service IP.

    Args:
        ip_str: IP address as a string

    Returns:
        True if the IP is a metadata service, False otherwise
    """
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
    # Ensure URL has a scheme
    if not urlparse(url).scheme:
        url = "http://" + url

    parsed = urlparse(url)

    # Check scheme
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise SSRFError(f"URL scheme '{parsed.scheme}' is not allowed. Only HTTP(S) is permitted.")

    hostname = parsed.hostname
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
            raise SSRFError(f"Access to private/internal IP addresses is not allowed.")

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
        raise SSRFError(f"Access to private/internal networks is not allowed.")

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
