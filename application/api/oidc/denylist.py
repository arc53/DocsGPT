"""Redis-backed session denylist for OIDC revocation.

Back-channel logout and SCIM deactivation drop identifiers here; the
request path refuses any session token whose identifiers match. Entries
live slightly longer than ``OIDC_SESSION_LIFETIME_SECONDS`` — every
session minted before the revocation expires before its denylist entry
does, so nothing needs to be stored durably.

Revocation is best-effort by design: if Redis is unreachable the check
fails open (sessions keep working) rather than taking the whole API down.
"""

from __future__ import annotations

import logging

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
        redis.set(key, "1", ex=_ttl_seconds())
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


def allow_user(user_id: str) -> None:
    """Clear a user-level denylist entry (SCIM reactivation)."""
    _delete(_USER_PREFIX + user_id)


def allow_idp_sub(sub: str) -> None:
    """Clear an IdP-sub denylist entry (fresh login supersedes a back-channel logout)."""
    _delete(_SUB_PREFIX + sub)


def _delete(key: str) -> None:
    redis = get_redis_instance()
    if redis is None:
        return
    try:
        redis.delete(key)
    except Exception:
        logger.warning("Failed to clear denylist key %s", key, exc_info=True)


def is_denied(decoded_token: dict) -> bool:
    """True when any identifier in a decoded session token is denylisted."""
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
        return any(value is not None for value in redis.mget(keys))
    except Exception:
        logger.warning("Denylist check failed — allowing request", exc_info=True)
        return False
