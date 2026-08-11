"""Redis-backed session denylist for OIDC revocation.

Back-channel logout and SCIM deactivation drop identifiers here; the
request path refuses any session token whose identifiers match. Each entry
stores a revocation *watermark* (a Unix timestamp): a session is denied
only when it was issued (``iat``) at or before the watermark. Storing a
watermark instead of a boolean is what lets a fresh login self-supersede a
prior revocation — its newer ``iat`` simply sits above the watermark —
without deleting the entry and thereby resurrecting still-live sessions
that were revoked on other devices.

Entries live slightly longer than ``OIDC_SESSION_LIFETIME_SECONDS`` —
every session issued at or before the watermark expires before the entry
does, so nothing needs to be stored durably.

Revocation is best-effort by design: if Redis is unreachable the check
fails open (sessions keep working) rather than taking the whole API down.
"""

from __future__ import annotations

import logging
import time

from application.cache import get_redis_instance
from application.core.settings import settings

logger = logging.getLogger(__name__)

_USER_PREFIX = "oidc:deny:user:"
_SUB_PREFIX = "oidc:deny:sub:"
_SID_PREFIX = "oidc:deny:sid:"


def _ttl_seconds() -> int:
    return settings.OIDC_SESSION_LIFETIME_SECONDS + 60


def _set(key: str) -> bool:
    redis = get_redis_instance()
    if redis is None:
        logger.error("Redis unavailable — could not denylist %s", key)
        return False
    try:
        # Store the revocation instant; existing entries are overwritten with a
        # newer watermark (revoking again only ever moves it forward in time).
        redis.set(key, str(int(time.time())), ex=_ttl_seconds())
        return True
    except Exception:
        logger.error("Failed to denylist %s", key, exc_info=True)
        return False


def deny_user(user_id: str) -> bool:
    """Revoke every live session of the DocsGPT user ``user_id``."""
    return _set(_USER_PREFIX + user_id)


def deny_idp_sub(sub: str) -> bool:
    """Revoke sessions by IdP ``sub`` (back-channel logout tokens carry this)."""
    return _set(_SUB_PREFIX + sub)


def deny_sid(sid: str) -> bool:
    """Revoke sessions of one IdP session id (``sid``-only logout tokens)."""
    return _set(_SID_PREFIX + sid)


def _watermark(value) -> float:
    """Parse a stored watermark to a float; unparseable values deny everything."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "ignore")
    try:
        return float(value)
    except (TypeError, ValueError):
        # Corrupt/legacy entry: treat as "deny" (a watermark far in the future).
        return float("inf")


def is_denied(decoded_token: dict) -> bool:
    """True when the token was issued at/before a matching revocation watermark."""
    keys = []
    if decoded_token.get("sub"):
        keys.append(_USER_PREFIX + str(decoded_token["sub"]))
    if decoded_token.get("oidc_sub"):
        keys.append(_SUB_PREFIX + str(decoded_token["oidc_sub"]))
    if decoded_token.get("oidc_sid"):
        keys.append(_SID_PREFIX + str(decoded_token["oidc_sid"]))
    if not keys:
        return False
    redis = get_redis_instance()
    if redis is None:
        return False
    try:
        values = redis.mget(keys)
    except Exception:
        logger.warning("Denylist check failed — allowing request", exc_info=True)
        return False
    try:
        iat = float(decoded_token.get("iat"))
    except (TypeError, ValueError):
        # No usable issue time — if any revocation exists for this identity we
        # cannot prove the token post-dates it, so deny.
        return any(value is not None for value in values)
    # Strict ``<``: a session issued in the same second as (or after) the
    # revocation — e.g. an immediate re-login — is allowed.
    return any(value is not None and iat < _watermark(value) for value in values)
