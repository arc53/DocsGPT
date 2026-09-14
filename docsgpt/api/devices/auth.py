"""Device session-token verification + machine-key signature check."""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from typing import Callable, Mapping, Optional, Tuple

from flask import jsonify, make_response, request

from docsgpt.core.settings import settings
from docsgpt.storage.db.repositories.devices import DevicesRepository
from docsgpt.storage.db.session import db_readonly, db_session


logger = logging.getLogger(__name__)

#: ``(error_code, http_status)`` for a rejected device request.
DeviceAuthFailure = Tuple[str, int]


def hash_session_token(token: str) -> str:
    """SHA-256 over the opaque session token. Stored in ``devices.token_hash``."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def fingerprint_pubkey(pubkey_b64: str) -> str:
    """SHA-256 over the raw public-key bytes; stored as the fingerprint."""
    raw = base64.b64decode(pubkey_b64)
    return hashlib.sha256(raw).hexdigest()


def _canonical_payload(method: str, path: str, ts: str, body: bytes) -> str:
    """Canonical string the device signs / the server verifies.

    Format: ``"{method} {path} {ts} {sha256_hex(body)}"``. The body hash
    binds the request body into the signature so a captured signature can't
    be replayed with a tampered body inside the timestamp window. For a GET
    (empty body) this is the SHA-256 of the empty string.

    KEEP IN SYNC with the DocsGPT-cli signer
    (``internal/host/identity.go`` ``CanonicalPayload`` / ``SignRequest``).
    The hex encoding and single-space separators must match byte-for-byte.
    """
    body_hash = hashlib.sha256(body or b"").hexdigest()
    return f"{method} {path} {ts} {body_hash}"


def authenticate_device(
    headers: Mapping[str, str],
    method: str,
    path: str,
    get_body: Callable[[], bytes],
    *,
    touch: bool = True,
) -> Tuple[Optional[dict], Optional[DeviceAuthFailure]]:
    """Validate a device session token from the raw request parts.

    Framework-neutral core shared by the Flask routes and the native-async
    SSE stream, which calls it from a worker thread since it reads Postgres.

    Args:
        headers: Request headers (a case-insensitive mapping).
        method: HTTP method, as the CLI signed it.
        path: Request path without the query string, as the CLI signed it.
        get_body: Returns the raw body; only called when signatures are required.
        touch: When True, bump ``last_seen_at`` on the device row.

    Returns:
        tuple: ``(device_row, None)`` on success or ``(None, (code, status))``.
    """
    auth = headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None, ("missing_token", 401)
    token = auth.split(" ", 1)[1].strip()
    if not token:
        return None, ("missing_token", 401)

    token_hash = hash_session_token(token)
    with db_readonly() as conn:
        device = DevicesRepository(conn).find_by_token_hash(token_hash)
    if device is None:
        return None, ("invalid_token", 401)

    if settings.REMOTE_DEVICE_REQUIRE_SIGNATURE:
        failure = _verify_signature(device, headers, method, path, get_body)
        if failure is not None:
            return None, failure

    if touch:
        try:
            with db_session() as conn:
                DevicesRepository(conn).touch_last_seen(device["id"])
        except Exception:
            logger.exception("touch_last_seen failed for device %s", device["id"])

    return device, None


def verify_device_session(*, touch: bool = True) -> Tuple[Optional[dict], Optional[tuple]]:
    """Validate the device session token on the current Flask request.

    Returns ``(device_row, None)`` on success or ``(None, response)`` on
    failure, where ``response`` is a ready Flask error response.

    Args:
        touch: When True, bump ``last_seen_at`` on the device row.
    """
    device, failure = authenticate_device(
        request.headers, request.method, request.path, request.get_data, touch=touch
    )
    if failure is not None:
        return None, _error(*failure)
    return device, None


def _verify_signature(
    device: dict,
    headers: Mapping[str, str],
    method: str,
    path: str,
    get_body: Callable[[], bytes],
) -> Optional[DeviceAuthFailure]:
    """Verify ``X-Device-Signature`` against the stored machine pubkey."""
    sig_b64 = headers.get("X-Device-Signature")
    ts = headers.get("X-Device-Timestamp")
    fp = headers.get("X-Device-Machine-Key")
    if not sig_b64 or not ts or not fp:
        return ("missing_signature", 401)

    try:
        ts_int = int(ts)
    except (TypeError, ValueError):
        return ("invalid_timestamp", 401)
    if abs(time.time() - ts_int) > 300:
        return ("timestamp_skew", 401)

    if fp != device.get("machine_pubkey_fingerprint"):
        return ("fingerprint_mismatch", 401)

    # Defer cryptography import to keep cold-start light when signatures
    # are disabled (the dev default).
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        logger.error(
            "Signature verification requested but ``cryptography`` is not installed."
        )
        return ("signature_unsupported", 500)

    # The full public key isn't stored — only the fingerprint. For signature
    # verification we accept the pubkey in a header too; we trust it iff
    # its fingerprint matches the stored one. This avoids a separate pubkey
    # column for MVP.
    pubkey_b64 = headers.get("X-Device-Machine-Pubkey")
    if not pubkey_b64:
        return ("missing_pubkey", 401)
    if fingerprint_pubkey(pubkey_b64) != device["machine_pubkey_fingerprint"]:
        return ("pubkey_fingerprint_mismatch", 401)

    payload = _canonical_payload(method, path, ts, get_body()).encode("utf-8")
    try:
        pubkey = Ed25519PublicKey.from_public_bytes(base64.b64decode(pubkey_b64))
        pubkey.verify(base64.b64decode(sig_b64), payload)
    except (InvalidSignature, ValueError):
        return ("invalid_signature", 401)

    return None


def _error(code: str, status: int) -> tuple:
    return make_response(
        jsonify({"success": False, "error": code}), status
    )
