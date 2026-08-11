"""Device session-token verification + machine-key signature check."""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from typing import Optional, Tuple

from flask import jsonify, make_response, request

from application.core.settings import settings
from application.storage.db.repositories.devices import DevicesRepository
from application.storage.db.session import db_readonly, db_session


logger = logging.getLogger(__name__)


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


def verify_device_session(*, touch: bool = True) -> Tuple[Optional[dict], Optional[tuple]]:
    """Validate the device session token on the current request.

    Returns ``(device_row, None)`` on success or ``(None, response)`` on
    failure, where ``response`` is a ``(json, status)`` Flask tuple.

    Args:
        touch: When True, bump ``last_seen_at`` on the device row.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None, _error("missing_token", 401)
    token = auth.split(" ", 1)[1].strip()
    if not token:
        return None, _error("missing_token", 401)

    token_hash = hash_session_token(token)
    with db_readonly() as conn:
        device = DevicesRepository(conn).find_by_token_hash(token_hash)
    if device is None:
        return None, _error("invalid_token", 401)

    if settings.REMOTE_DEVICE_REQUIRE_SIGNATURE:
        sig_error = _verify_signature(device)
        if sig_error is not None:
            return None, sig_error

    if touch:
        try:
            with db_session() as conn:
                DevicesRepository(conn).touch_last_seen(device["id"])
        except Exception:
            logger.exception("touch_last_seen failed for device %s", device["id"])

    return device, None


def _verify_signature(device: dict) -> Optional[tuple]:
    """Verify ``X-Device-Signature`` against the stored machine pubkey."""
    sig_b64 = request.headers.get("X-Device-Signature")
    ts = request.headers.get("X-Device-Timestamp")
    fp = request.headers.get("X-Device-Machine-Key")
    if not sig_b64 or not ts or not fp:
        return _error("missing_signature", 401)

    try:
        ts_int = int(ts)
    except (TypeError, ValueError):
        return _error("invalid_timestamp", 401)
    if abs(time.time() - ts_int) > 300:
        return _error("timestamp_skew", 401)

    if fp != device.get("machine_pubkey_fingerprint"):
        return _error("fingerprint_mismatch", 401)

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
        return _error("signature_unsupported", 500)

    # The full public key isn't stored — only the fingerprint. For signature
    # verification we accept the pubkey in a header too; we trust it iff
    # its fingerprint matches the stored one. This avoids a separate pubkey
    # column for MVP.
    pubkey_b64 = request.headers.get("X-Device-Machine-Pubkey")
    if not pubkey_b64:
        return _error("missing_pubkey", 401)
    if fingerprint_pubkey(pubkey_b64) != device["machine_pubkey_fingerprint"]:
        return _error("pubkey_fingerprint_mismatch", 401)

    payload = _canonical_payload(
        request.method, request.path, ts, request.get_data()
    ).encode("utf-8")
    try:
        pubkey = Ed25519PublicKey.from_public_bytes(base64.b64decode(pubkey_b64))
        pubkey.verify(base64.b64decode(sig_b64), payload)
    except (InvalidSignature, ValueError):
        return _error("invalid_signature", 401)

    return None


def _error(code: str, status: int) -> tuple:
    return make_response(
        jsonify({"success": False, "error": code}), status
    )
