"""Verifying signed webhook deliveries: Standard Webhooks, GitHub, and a plain HMAC-SHA256 header.

Every comparison is constant-time (:func:`hmac.compare_digest`) and is made
over the raw request body exactly as received.

* ``standard_webhooks`` (https://www.standardwebhooks.com): headers
  ``webhook-id``, ``webhook-timestamp`` and ``webhook-signature`` (Svix's
  ``svix-*`` names are accepted too). The signed content is
  ``"{id}.{timestamp}.{body}"``, the key is the base64-decoded secret after
  its ``whsec_`` prefix, and the signature header is a space-separated list
  of ``v1,<base64 HMAC-SHA256>``; any one matching passes. The timestamp must
  be within :data:`TOLERANCE_SECONDS` of now, either way.
* ``github``: ``X-Hub-Signature-256: sha256=<hex HMAC-SHA256 of the body>``,
  keyed with the secret's UTF-8 bytes.
* ``hmac_sha256``: ``X-Signature: sha256=<hex>``, the same computation.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time
from typing import Mapping, Optional

#: How far a Standard Webhooks timestamp may be from now, in seconds (the spec's five minutes).
TOLERANCE_SECONDS = 300

_WHSEC_PREFIX = "whsec_"


class SignatureError(Exception):
    """The delivery's signature is missing, malformed, stale or wrong."""


def _header(headers: Mapping[str, str], *names: str) -> Optional[str]:
    """The first present header among ``names``, matched case-insensitively."""
    lowered = {str(k).lower(): v for k, v in headers.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value:
            return str(value).strip()
    return None


def _standard_key(secret: str) -> bytes:
    raw = secret[len(_WHSEC_PREFIX):] if secret.startswith(_WHSEC_PREFIX) else secret
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise SignatureError("the link's secret is not a valid Standard Webhooks secret") from None


def sign_standard(secret: str, msg_id: str, timestamp: int, body: bytes) -> str:
    """The ``webhook-signature`` value for a delivery (used by tests and examples)."""
    content = f"{msg_id}.{timestamp}.".encode("utf-8") + body
    digest = hmac.new(_standard_key(secret), content, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode("ascii")


def verify_standard(secret: str, headers: Mapping[str, str], body: bytes, *, now: Optional[float] = None) -> str:
    """Verify a Standard Webhooks delivery.

    Args:
        secret: The ``whsec_`` secret.
        headers: The request headers.
        body: The raw body.
        now: The current Unix time (for tests).

    Returns:
        The ``webhook-id`` (the delivery's dedupe key).

    Raises:
        SignatureError: Missing headers, a timestamp outside the tolerance, or no matching signature.
    """
    msg_id = _header(headers, "webhook-id", "svix-id")
    stamp = _header(headers, "webhook-timestamp", "svix-timestamp")
    signatures = _header(headers, "webhook-signature", "svix-signature")
    if not msg_id or not stamp or not signatures:
        raise SignatureError("missing webhook-id, webhook-timestamp or webhook-signature")
    try:
        timestamp = int(stamp)
    except ValueError:
        raise SignatureError("webhook-timestamp is not a Unix time") from None
    current = time.time() if now is None else now
    if abs(current - timestamp) > TOLERANCE_SECONDS:
        raise SignatureError("webhook-timestamp is too old or too new")
    expected = sign_standard(secret, msg_id, timestamp, body).split(",", 1)[1].encode("ascii")
    for candidate in signatures.split():
        version, _, value = candidate.partition(",")
        if version == "v1" and hmac.compare_digest(value.encode("ascii", "replace"), expected):
            return msg_id
    raise SignatureError("no webhook-signature matches")


def hex_hmac(secret: str, body: bytes) -> str:
    """Hex HMAC-SHA256 of the body keyed with the secret's UTF-8 bytes."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_hex(secret: str, header_value: Optional[str], body: bytes) -> None:
    """Verify a ``sha256=<hex>`` header (GitHub's ``X-Hub-Signature-256``, or ``X-Signature``).

    Raises:
        SignatureError: The header is missing, malformed or wrong.
    """
    if not header_value:
        raise SignatureError("the signature header is missing")
    algorithm, _, value = header_value.strip().partition("=")
    if algorithm.lower() != "sha256" or not value:
        raise SignatureError("the signature header must look like sha256=<hex>")
    expected = hex_hmac(secret, body)
    if not hmac.compare_digest(value.strip().lower().encode("ascii", "replace"), expected.encode("ascii")):
        raise SignatureError("the signature does not match")


def verify(scheme: str, secret: Optional[str], headers: Mapping[str, str], body: bytes,
           *, now: Optional[float] = None) -> Optional[str]:
    """Verify a delivery for the link's scheme.

    Args:
        scheme: ``none``, ``standard_webhooks``, ``github`` or ``hmac_sha256``.
        secret: The link's decrypted secret.
        headers: The request headers.
        body: The raw body.
        now: The current Unix time (for tests).

    Returns:
        The sender's delivery id when the scheme carries one (Standard Webhooks), else None.

    Raises:
        SignatureError: A signed link got a delivery that doesn't verify.
    """
    if scheme in (None, "", "none"):
        return None
    if not secret:
        raise SignatureError("the link has no secret")
    if scheme == "standard_webhooks":
        return verify_standard(secret, headers, body, now=now)
    if scheme == "github":
        verify_hex(secret, _header(headers, "X-Hub-Signature-256"), body)
        return None
    if scheme == "hmac_sha256":
        verify_hex(secret, _header(headers, "X-Signature"), body)
        return None
    raise SignatureError(f"unknown signature scheme {scheme!r}")
