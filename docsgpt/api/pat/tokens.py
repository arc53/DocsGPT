"""Personal access tokens: format, scope catalog and the per-request verifier.

A PAT is ``dgpt_pat_`` + 32 random bytes (urlsafe). Only its SHA-256 is stored
(``personal_access_tokens.token_hash``), the same shape as device session
tokens. Scopes and the resource filter are always read from the database row;
nothing about a token's authority is encoded in the credential itself.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from docsgpt.core.settings import settings
from docsgpt.storage.db.repositories.personal_access_tokens import (
    PersonalAccessTokensRepository,
)
from docsgpt.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "dgpt_pat_"
# Characters of the secret kept in ``token_prefix`` so users can tell tokens apart.
_DISPLAY_CHARS = 6

AUTH_METHOD_PAT = "pat"

#: Every grantable scope with the description shown in the UI and docs.
SCOPES: dict[str, str] = {
    "agents:read": "View agents, folders, guardrail events and export agent definitions",
    "agents:write": "Create, update, delete, share and import (apply) agents and folders",
    "agents:keys": "Regenerate agent API keys and read incoming webhook URLs",
    "sources:read": "View sources, their files, chunks and ingestion task status",
    "sources:write": "Upload, ingest, sync, edit and delete sources and chunks",
    "prompts:read": "View prompts",
    "prompts:write": "Create, update and delete prompts",
    "tools:read": "View configured tools",
    "tools:write": "Create, update and delete tools and MCP servers",
    "models:read": "View available and custom models",
    "models:write": "Create, update, test and delete custom models",
    "workflows:read": "View workflows",
    "workflows:write": "Create, update and delete workflows",
    "schedules:read": "View agent schedules and their runs",
    "schedules:write": "Create, update, run and delete agent schedules",
    "conversations:read": "View conversations and messages",
    "conversations:write": "Rename, delete and give feedback on conversations",
    "analytics:read": "View usage analytics and logs",
    "teams:read": "View teams, members and resource shares",
    "chat:run": "Ask agents and search sources (answer, stream, search); used for benchmarking",
}

#: Resource families whose tokens can be narrowed to specific ids.
FILTERABLE_FAMILIES = ("agents", "sources", "prompts", "tools", "workflows")
_MAX_FILTER_IDS = 200


def auth_type_supports_pats() -> bool:
    """PATs bind to a stable user id, which simple_jwt/session_jwt don't have."""
    return bool(settings.PAT_ENABLED) and settings.AUTH_TYPE in (None, "oidc")


def generate_token() -> tuple[str, str, str]:
    """Mint a token. Returns ``(plaintext, sha256_hex, display_prefix)``."""
    secret = secrets.token_urlsafe(32)
    token = TOKEN_PREFIX + secret
    return token, hash_token(token), TOKEN_PREFIX + secret[:_DISPLAY_CHARS]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def looks_like_pat(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(TOKEN_PREFIX)


def redact(value: Optional[str]) -> str:
    """Log-safe form of a credential: the display prefix only."""
    if not value:
        return ""
    if looks_like_pat(value):
        return value[: len(TOKEN_PREFIX) + _DISPLAY_CHARS] + "…"
    return value[:4] + "…"


def expand_scopes(scopes) -> set[str]:
    """Granted scopes plus what they imply (``x:write`` includes ``x:read``)."""
    granted = set(scopes or [])
    for scope in list(granted):
        family, _, action = scope.partition(":")
        if action == "write" and f"{family}:read" in SCOPES:
            granted.add(f"{family}:read")
    return granted


def normalize_scopes(raw: Any) -> list[str]:
    """Validate a requested scope list. Raises ``ValueError`` with a user-facing message."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("scopes must be a non-empty list")
    unknown = sorted({s for s in raw if not isinstance(s, str) or s not in SCOPES}, key=str)
    if unknown:
        raise ValueError(f"Unknown scopes: {', '.join(map(str, unknown))}")
    return sorted(set(raw))


def normalize_resource_filter(raw: Any, scopes: list[str]) -> dict[str, list[str]]:
    """Validate ``{"<family>": ["<uuid>", ...]}``. Raises ``ValueError`` with a user-facing message.

    A family may only be restricted when the token holds a scope in it;
    otherwise the restriction would be dead weight that reads as protection.
    """
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ValueError("resource_filter must be an object")
    families = {s.partition(":")[0] for s in scopes}
    # chat:run acts on agents and sources, so both may be restricted alongside it.
    if "chat" in families:
        families.update({"agents", "sources"})
    if "tools" in raw and "chat:run" in scopes:
        # Chat executes tools (an agent's own, or the user's defaults), which cannot be held to an allowlist.
        raise ValueError("resource_filter.tools cannot be combined with the chat:run scope")
    out: dict[str, list[str]] = {}
    for family, ids in raw.items():
        if family not in FILTERABLE_FAMILIES:
            raise ValueError(
                f"resource_filter supports only: {', '.join(FILTERABLE_FAMILIES)}"
            )
        if family not in families:
            raise ValueError(f"resource_filter.{family} needs a {family} scope on the token")
        if not isinstance(ids, list) or not ids:
            raise ValueError(f"resource_filter.{family} must be a non-empty list of ids")
        if len(ids) > _MAX_FILTER_IDS:
            raise ValueError(f"resource_filter.{family} allows at most {_MAX_FILTER_IDS} ids")
        normalized = []
        for value in ids:
            try:
                normalized.append(str(uuid.UUID(str(value))))
            except (ValueError, AttributeError, TypeError):
                raise ValueError(f"resource_filter.{family} contains an invalid id: {value!r}")
        out[family] = sorted(set(normalized))
    return out


def resolve_expiry(expires_in_days: Any) -> Optional[datetime]:
    """Map the requested lifetime to ``expires_at``. Raises ``ValueError`` with a user-facing message.

    ``None`` means "use the default"; ``0`` asks for a non-expiring token,
    which only an operator setting can allow.
    """
    if expires_in_days is None:
        days = settings.PAT_DEFAULT_LIFETIME_DAYS
    elif isinstance(expires_in_days, bool) or not isinstance(expires_in_days, int):
        raise ValueError("expires_in_days must be an integer")
    elif expires_in_days == 0:
        if not settings.PAT_ALLOW_NON_EXPIRING:
            raise ValueError("Non-expiring tokens are disabled on this server")
        return None
    elif expires_in_days < 0:
        raise ValueError("expires_in_days must be positive")
    else:
        days = expires_in_days
    if days > settings.PAT_MAX_LIFETIME_DAYS:
        raise ValueError(f"expires_in_days must not exceed {settings.PAT_MAX_LIFETIME_DAYS}")
    return datetime.now(timezone.utc) + timedelta(days=days)


def _parse_moment(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def renewal_lifetime_days(row: dict) -> Optional[int]:
    """The lifetime a token was last issued with, for renewing it on the same terms.

    ``0`` for a non-expiring token, ``None`` when it cannot be derived (the
    caller then falls back to the default). The result is clamped to today's
    maximum, since the policy may have tightened since the token was issued.
    """
    issued = _parse_moment(row.get("regenerated_at")) or _parse_moment(row.get("created_at"))
    expires = _parse_moment(row.get("expires_at"))
    if expires is None:
        return 0 if settings.PAT_ALLOW_NON_EXPIRING else None
    if issued is None:
        return None
    days = round((expires - issued).total_seconds() / 86400)
    return max(1, min(days, settings.PAT_MAX_LIFETIME_DAYS))


def _client_ip(request) -> Optional[str]:
    # Flask exposes remote_addr; Starlette exposes client.host.
    ip = getattr(request, "remote_addr", None)
    if ip:
        return ip
    client = getattr(request, "client", None)
    return getattr(client, "host", None)


_TOUCH_INTERVAL_SECONDS = 60


def _usage_is_stale(last_used_at: Any) -> bool:
    """True when ``last_used_at`` is old enough to be worth a write transaction."""
    if not last_used_at:
        return True
    try:
        seen = last_used_at if isinstance(last_used_at, datetime) else datetime.fromisoformat(str(last_used_at))
    except ValueError:
        return True
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - seen).total_seconds() >= _TOUCH_INTERVAL_SECONDS


_INVALID = {"message": "Authentication error: invalid token", "error": "invalid_token"}


def authenticate_pat(token: str, request) -> dict:
    """Resolve a PAT into the claims dict the rest of the app reads.

    Fails closed: an unknown, revoked or expired token, a disabled feature or
    a database error all yield the same ``invalid_token`` error.
    """
    if not auth_type_supports_pats():
        return dict(_INVALID)
    try:
        with db_readonly() as conn:
            row = PersonalAccessTokensRepository(conn).find_active_by_hash(hash_token(token))
    except Exception:
        logger.error("PAT lookup failed for %s", redact(token), exc_info=True)
        return dict(_INVALID)
    if not row:
        logger.warning("Rejected personal access token %s", redact(token))
        return dict(_INVALID)
    if _usage_is_stale(row.get("last_used_at")):
        try:
            with db_session() as conn:
                PersonalAccessTokensRepository(conn).touch_last_used(
                    str(row["id"]), _client_ip(request), min_interval_seconds=_TOUCH_INTERVAL_SECONDS
                )
        except Exception:
            # Usage telemetry must never fail a request.
            logger.debug("PAT last-used update failed", exc_info=True)
    return {
        "sub": row["user_id"],
        "auth_method": AUTH_METHOD_PAT,
        "pat_id": str(row["id"]),
        "pat_name": row["name"],
        "scopes": sorted(expand_scopes(row.get("scopes"))),
        "resource_filter": row.get("resource_filter") or {},
    }


def is_pat(decoded_token: Optional[dict]) -> bool:
    return bool(decoded_token) and decoded_token.get("auth_method") == AUTH_METHOD_PAT
