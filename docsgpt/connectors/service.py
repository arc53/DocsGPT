"""Connection lifecycle: listing, status, and what each connection provides.

A connection is one ``connector_sessions`` row: a signed-in OAuth account, an
MCP server or a set of API credentials. Sources and tools point at it through
``connection_id``. Everything the API returns about a connection goes through
:func:`serialize_connection`, which never includes credentials.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from docsgpt.connectors import catalog
from docsgpt.connectors.catalog import ConnectorDefinition
from docsgpt.storage.db.repositories.connector_sessions import (
    ConnectorSessionsRepository,
    owns_connector_session,
)
from docsgpt.storage.db.session import db_readonly, db_session

STATUS_CONNECTED = "connected"
STATUS_RECONNECT = "reconnect_needed"
STATUS_DISCONNECTED = "disconnected"
STATUS_ERROR = "error"
STATUS_PENDING = "pending"

# Worst first: a card shows the worst status among the user's accounts.
_STATUS_SEVERITY = {
    STATUS_RECONNECT: 4,
    STATUS_ERROR: 3,
    STATUS_DISCONNECTED: 2,
    STATUS_CONNECTED: 1,
    STATUS_PENDING: 0,
}


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def has_credentials(row: dict) -> bool:
    """Whether a connection holds usable credentials (without decrypting them)."""
    if row.get("encrypted_credentials"):
        return True
    return _has_plaintext_tokens(row)


def _has_plaintext_tokens(row: dict) -> bool:
    """Legacy plaintext tokens on a row not yet converted by migration 0038."""
    token_info = _json(row.get("token_info")) or {}
    if isinstance(token_info, dict) and token_info.get("access_token"):
        return True
    session_data = _json(row.get("session_data")) or {}
    tokens = session_data.get("tokens") if isinstance(session_data, dict) else None
    return bool(isinstance(tokens, dict) and tokens.get("access_token"))


def normalize_status(row: dict) -> str:
    """Map a row's stored status onto the connection status set.

    Rows written before ``0038_connections`` use ``authorized`` for a
    finished OAuth sign-in, and MCP rows carry no status at all; both are
    read from whether the row holds credentials.
    """
    raw = (row.get("status") or "").lower()
    if raw in (STATUS_RECONNECT, STATUS_DISCONNECTED, STATUS_ERROR):
        return raw
    if raw in ("authorized", STATUS_CONNECTED, "active"):
        return STATUS_CONNECTED
    if raw == STATUS_PENDING:
        # A legacy row whose plaintext tokens landed after the pending mark.
        return STATUS_CONNECTED if _has_plaintext_tokens(row) else STATUS_PENDING
    return STATUS_CONNECTED if has_credentials(row) else STATUS_PENDING


def worst_status(statuses: Iterable[str]) -> Optional[str]:
    """The status that needs the most attention, or None for an empty list."""
    ranked = sorted(statuses, key=lambda s: _STATUS_SEVERITY.get(s, 0), reverse=True)
    return ranked[0] if ranked else None


def account_label(row: dict) -> str:
    """What identifies the account to its owner: an email, a workspace or a host."""
    return (
        row.get("account_label")
        or row.get("user_email")
        or row.get("display_name")
        or catalog.base_url(row.get("server_url")).split("://")[-1]
        or ""
    )


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else value


def serialize_connection(row: dict, counts: Optional[dict] = None) -> dict:
    """Public shape of a connection. Never includes tokens or secrets."""
    key = catalog.connector_key_for_row(row)
    definition = catalog.get_definition(key)
    counts = counts or {}
    return {
        "id": str(row["id"]),
        "connector_key": key,
        "name": (definition.name if definition and definition.publisher != "custom" else None)
        or row.get("display_name")
        or (definition.name if definition else key),
        "display_name": row.get("display_name"),
        "icon": definition.icon if definition else "tool_mcp_tool",
        "account_label": account_label(row),
        "auth_kind": row.get("auth_kind") or (definition.auth_kind if definition else None),
        "status": normalize_status(row),
        "server_url": row.get("server_url"),
        "last_error": row.get("last_error"),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        "last_used_at": _iso(row.get("last_used_at")),
        "source_count": counts.get("sources", 0),
        "tool_count": counts.get("tools", 0),
        "credential_mode": row.get("credential_mode"),
    }


def list_connections(conn, user_id: str) -> list[dict]:
    """The user's connections, finished sign-ins only, with resource counts."""
    repo = ConnectorSessionsRepository(conn)
    rows = [r for r in repo.list_for_user(user_id) if normalize_status(r) != STATUS_PENDING]
    counts = repo.resource_counts([str(r["id"]) for r in rows])
    return [serialize_connection(r, counts.get(str(r["id"]))) for r in rows]


def serialize_source(row: dict, connection_status: Optional[str] = None) -> dict:
    """A source linked to a connection, as the connection drawer lists it."""
    metadata = _json(row.get("metadata")) or {}
    sync_state = metadata.get("sync_state") if isinstance(metadata, dict) else None
    if connection_status in (STATUS_RECONNECT, STATUS_DISCONNECTED) and not sync_state:
        sync_state = "paused_reconnect"
    return {
        "id": str(row["id"]),
        "name": row.get("name"),
        "type": row.get("type"),
        "last_sync": _iso(row.get("date")),
        "sync_frequency": row.get("sync_frequency") or "never",
        "sync_state": sync_state or "active",
    }


def serialize_tool(row: dict) -> dict:
    """A tool linked to a connection, with its actions and their permissions."""
    from docsgpt.connectors.permissions import action_access, action_permission

    actions = []
    for action in _json(row.get("actions")) or []:
        if not isinstance(action, dict):
            continue
        access = action_access(row.get("name"), action)
        actions.append(
            {
                "name": action.get("name"),
                "description": action.get("description", ""),
                "access": access,
                "permission": action_permission(action),
            }
        )
    return {
        "id": str(row["id"]),
        "name": row.get("name"),
        "display_name": row.get("custom_name") or row.get("display_name") or row.get("name"),
        "status": bool(row.get("status")),
        "credential_mode": row.get("credential_mode") or "owner",
        "actions": actions,
    }


def connection_detail(conn, row: dict) -> dict:
    """A connection with the sources and tools it feeds."""
    repo = ConnectorSessionsRepository(conn)
    status = normalize_status(row)
    sources = [serialize_source(s, status) for s in repo.list_sources(str(row["id"]))]
    tools = [serialize_tool(t) for t in repo.list_tools(str(row["id"]))]
    detail = serialize_connection(row, {"sources": len(sources), "tools": len(tools)})
    detail["sources"] = sources
    detail["tools"] = tools
    return detail


def _card_state(definition: ConnectorDefinition, available: bool, disabled: bool, status: Optional[str]) -> str:
    if disabled:
        return "disabled"
    if status in (STATUS_RECONNECT, STATUS_ERROR):
        return "reconnect"
    if status == STATUS_CONNECTED:
        return "connected"
    if not available:
        return "needs_setup"
    if definition.publisher == "custom":
        return "custom"
    return "available"


def catalog_for_user(conn, user_id: str, *, is_admin: bool, policies: Optional[dict] = None) -> list[dict]:
    """Catalog entries with availability and the caller's connection summary.

    Args:
        conn: Open database connection.
        user_id: The caller.
        is_admin: Admins see the names of missing server settings; everyone
            else only learns that setup is needed.
        policies: ``connector_key`` to policy row, when admin policies exist.
    """
    if policies is None:
        policies = load_policies(conn)
    by_key: dict[str, list[str]] = {}
    for connection in list_connections(conn, user_id):
        by_key.setdefault(connection["connector_key"], []).append(connection["status"])

    entries = []
    for definition in catalog.all_definitions():
        policy = policies.get(definition.key) or {}
        disabled = not connector_is_enabled(policies, definition.key)
        missing = definition.missing_settings
        available = not missing and not disabled
        statuses = by_key.get(definition.key, [])
        if not available and not statuses:
            # Members only see what they can use, plus what they connected
            # before an admin turned it off (to manage or remove it).
            continue
        status = worst_status(statuses)
        entries.append(
            {
                **definition.to_dict(),
                "available": available,
                "disabled": disabled,
                "needs_setup": bool(missing),
                "missing_settings": missing if is_admin else [],
                "connected_count": sum(1 for s in statuses if s == STATUS_CONNECTED),
                "connection_count": len(statuses),
                "status": status,
                "state": _card_state(definition, available, disabled, status),
                "credential_policy": policy.get("credential_mode") or "choose",
            }
        )
    return entries


def disconnect(conn, row: dict) -> dict:
    """Forget a connection's credentials but keep the row and what it feeds.

    Revokes the grant at the provider where that is supported (Google);
    a failed revocation never blocks forgetting the tokens here. Sources keep
    their indexed content and pause syncing; tools stop working until the
    account is reconnected. An MCP server's client registration is kept so
    reconnecting skips dynamic client registration.

    Args:
        conn: Open database connection inside a transaction.
        row: The connection row, already authorised for the caller.

    Returns:
        The connection's public shape after the change.
    """
    from sqlalchemy import text

    from docsgpt.security.encryption import CredentialDecryptionError

    try:
        secrets = read_secrets(row)
    except CredentialDecryptionError:
        secrets = {}
    revoke_at_provider(row, secrets)
    kept = {"client_info": secrets["client_info"]} if secrets.get("client_info") else {}
    write_secrets(
        conn, row, kept, status=STATUS_DISCONNECTED, session_token=None, last_error=None,
    )
    conn.execute(
        text(
            "UPDATE sources SET metadata = metadata || '{\"sync_state\": \"paused_reconnect\"}'::jsonb "
            "WHERE connection_id = CAST(:id AS uuid)"
        ),
        {"id": str(row["id"])},
    )
    return serialize_connection(ConnectorSessionsRepository(conn).get(str(row["id"])))


def revoke_at_provider(row: dict, secrets: dict) -> bool:
    """Best-effort revocation of an OAuth grant. Returns whether it succeeded.

    Only Google offers a public revocation endpoint for these apps; Microsoft
    and Atlassian tokens are simply forgotten locally.
    """
    import logging

    import requests

    token_info = secrets.get("token_info") or {}
    token = token_info.get("refresh_token") or token_info.get("access_token")
    if row.get("provider") != "google_drive" or not token:
        return False
    try:
        response = requests.post(
            "https://oauth2.googleapis.com/revoke",
            data={"token": token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        return response.status_code == 200
    except requests.RequestException as exc:
        logging.getLogger(__name__).warning("Google token revocation failed: %s", type(exc).__name__)
        return False


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------
#
# A connection's secrets are one dict, encrypted as a whole into
# ``encrypted_credentials``:
#
#   token_info   OAuth tokens of an ingest provider (Drive, SharePoint, Confluence)
#   tokens       MCP OAuth tokens
#   client_info  MCP dynamic client registration (client_id / client_secret)
#   credentials  API keys and other pasted secrets, by credential field key
#
# This module is the only caller of encrypt_json / decrypt_json for
# connections, and get_valid_token_info the only reader of OAuth tokens.

DECRYPT_ERROR = "Stored credentials could not be decrypted. Reconnect to continue."
_SECRET_SESSION_KEYS = ("tokens", "client_info")


class ConnectionUnavailable(ValueError):
    """A connection cannot be used until its owner reconnects it.

    Attributes:
        connection_id: The connection, when known.
        status: ``reconnect_needed``, ``disconnected`` or ``missing``.
    """

    def __init__(self, message: str, *, connection_id: Optional[str] = None, status: str = STATUS_RECONNECT):
        super().__init__(message)
        self.connection_id = connection_id
        self.status = status


class TransientConnectionError(Exception):
    """The provider failed in a way worth retrying (5xx, rate limit, network)."""


class EncryptionKeyNotConfigured(Exception):
    """New credentials are refused while a multi-user install uses the public default key."""


def ensure_can_store_credentials() -> None:
    """Refuse to store new credentials under the public default encryption key.

    Only multi-user installs (any ``AUTH_TYPE``) are refused; a single-user
    local install keeps working and logs a warning at startup instead.

    Raises:
        EncryptionKeyNotConfigured: When the key is the default and auth is on.
    """
    from docsgpt.core.settings import settings
    from docsgpt.security.encryption import is_default_encryption_key

    if settings.AUTH_TYPE and is_default_encryption_key():
        raise EncryptionKeyNotConfigured("Set ENCRYPTION_SECRET_KEY before connecting services.")


def read_secrets(row: dict) -> dict:
    """Decrypt a connection's secrets.

    Rows not yet converted by migration 0038 (or written by an older process
    during a rolling deploy) still carry plaintext ``token_info`` and
    ``session_data`` tokens; those are read as they are.

    Raises:
        CredentialDecryptionError: The envelope cannot be decrypted.
    """
    from docsgpt.security.encryption import decrypt_json

    blob = row.get("encrypted_credentials")
    if blob:
        return decrypt_json(blob, row["user_id"])
    secrets: dict = {}
    token_info = _json(row.get("token_info"))
    if isinstance(token_info, dict) and token_info:
        secrets["token_info"] = token_info
    session_data = _json(row.get("session_data")) or {}
    if isinstance(session_data, dict):
        for key in _SECRET_SESSION_KEYS:
            if key in session_data:
                secrets[key] = session_data[key]
    return secrets


def _has_refresh(secrets: dict) -> bool:
    token_info = secrets.get("token_info") or {}
    tokens = secrets.get("tokens") or {}
    return bool(
        (isinstance(token_info, dict) and token_info.get("refresh_token"))
        or (isinstance(tokens, dict) and tokens.get("refresh_token"))
    )


def write_secrets(conn, row: dict, secrets: dict, **fields: Any) -> None:
    """Replace a connection's secrets and clear every plaintext copy.

    Args:
        conn: Open connection inside a transaction.
        row: The connection row (only ``id``, ``user_id`` and ``session_data``
            are read).
        secrets: The complete secrets dict; empty clears the credentials.
        **fields: Other columns to update in the same statement.
    """
    from docsgpt.security.encryption import encrypt_json

    session_data = _json(row.get("session_data")) or {}
    if isinstance(session_data, dict):
        session_data = {k: v for k, v in session_data.items() if k not in _SECRET_SESSION_KEYS}
    else:
        session_data = {}
    update = {
        "encrypted_credentials": encrypt_json(secrets, row["user_id"]) if secrets else None,
        "has_refresh_token": _has_refresh(secrets),
        "token_info": None,
        "session_data": session_data,
        **fields,
    }
    token_info = secrets.get("token_info")
    if isinstance(token_info, dict) and token_info.get("scopes") and "scopes" not in fields:
        scopes = token_info["scopes"]
        update["scopes"] = scopes.split() if isinstance(scopes, str) else list(scopes)
    ConnectorSessionsRepository(conn).update(str(row["id"]), update)


def credential_hint(credentials: dict) -> str:
    """``…abcd``: the last four characters of the first long secret, never more."""
    for value in credentials.values():
        if isinstance(value, str) and len(value) >= 8:
            return "…" + value[-4:]
    return "…"


def mark_reconnect_needed(connection_id: str, error: str) -> None:
    """Flag a connection whose credentials stopped working and tell its owner.

    Pauses syncing on every source the connection feeds (no retry storm) and
    publishes a ``connection.reconnect_needed`` user event, which the
    frontend shows as a toast with a Reconnect action. Runs in its own
    transaction so it sticks even when the caller's transaction rolls back.
    """
    from sqlalchemy import text

    from docsgpt.events.publisher import publish_user_event
    with db_session() as conn:
        repo = ConnectorSessionsRepository(conn)
        row = repo.get(connection_id)
        if row is None:
            return
        already = normalize_status(row) == STATUS_RECONNECT
        counts = repo.resource_counts([connection_id]).get(str(connection_id), {})
        repo.update(connection_id, {"status": STATUS_RECONNECT, "last_error": error[:500]})
        conn.execute(
            text(
                "UPDATE sources SET metadata = metadata || '{\"sync_state\": \"paused_reconnect\"}'::jsonb "
                "WHERE connection_id = CAST(:id AS uuid)"
            ),
            {"id": connection_id},
        )
    if not already:
        publish_user_event(
            row["user_id"],
            "connection.reconnect_needed",
            {
                "connection_id": connection_id,
                "connector_key": catalog.connector_key_for_row(row),
                "name": serialize_connection(row)["name"],
                "source_count": counts.get("sources", 0),
                "tool_count": counts.get("tools", 0),
            },
            scope={"kind": "connection", "id": connection_id},
        )


def resume_sources(conn, connection_id: str) -> None:
    """Lift the reconnect pause from a connection's sources."""
    from sqlalchemy import text

    conn.execute(
        text(
            "UPDATE sources SET metadata = metadata - 'sync_state' "
            "WHERE connection_id = CAST(:id AS uuid) AND metadata ? 'sync_state'"
        ),
        {"id": connection_id},
    )


def load_secrets(row: dict) -> Optional[dict]:
    """Decrypt a row's secrets; on failure flag it for reconnect and return None."""
    from docsgpt.security.encryption import CredentialDecryptionError

    try:
        return read_secrets(row)
    except CredentialDecryptionError:
        mark_reconnect_needed(str(row["id"]), DECRYPT_ERROR)
        return None


def _is_auth_failure(exc: BaseException) -> bool:
    """Whether a refresh failure means the grant is gone (vs. a retryable blip)."""
    import requests

    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(exc, requests.exceptions.HTTPError) and status is not None:
        return status in (400, 401, 403)
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return False
    message = str(exc).lower()
    if any(word in message for word in ("timed out", "temporarily", "rate limit", "503", "502", "504")):
        return False
    try:
        from google.auth.exceptions import RefreshError, TransportError

        if isinstance(exc, TransportError):
            return False
        if isinstance(exc, RefreshError):
            return True
    except ImportError:  # pragma: no cover - google libs are core deps
        pass
    return True


def connection_id_for_session_token(session_token: Optional[str]) -> str:
    """The connection behind a legacy browser session token.

    Raises:
        ConnectionUnavailable: No connection holds that token.
    """
    from docsgpt.parser.connectors._auth_utils import session_token_fingerprint
    row = None
    if session_token:
        with db_readonly() as conn:
            row = ConnectorSessionsRepository(conn).get_by_session_token(session_token)
    if row is None:
        raise ConnectionUnavailable(
            f"Invalid session token ({session_token_fingerprint(session_token or '')})", status="missing",
        )
    return str(row["id"])


def get_valid_token_info(connection_id: str, *, rejected_access_token: Optional[str] = None) -> dict:
    """An unexpired OAuth ``token_info`` for an ingest connection.

    Holds a row lock (``SELECT ... FOR UPDATE``) while it checks expiry and
    refreshes, and writes the rotated refresh token back in the same
    transaction, so two workers refreshing a rotating token (Microsoft,
    Atlassian) never spend the same one twice: the second waits and then
    reads the first one's fresh token.

    Args:
        connection_id: The connection to use.
        rejected_access_token: An access token the provider just answered
            with 401. The token is refreshed when it is still the stored one;
            when another worker already replaced it, the new one is returned.

    Returns:
        The decrypted token info, refreshed if it was about to expire.

    Raises:
        ConnectionUnavailable: The connection is missing, disconnected, cannot
            be decrypted, or its grant was revoked (it is then flagged
            ``reconnect_needed``).
        TransientConnectionError: The provider failed in a retryable way.
    """
    from docsgpt.parser.connectors.connector_creator import ConnectorCreator
    from docsgpt.security.encryption import CredentialDecryptionError
    failure: Optional[str] = None
    transient: Optional[BaseException] = None
    token_info: Optional[dict] = None
    with db_session() as conn:
        repo = ConnectorSessionsRepository(conn)
        row = repo.get_for_update(connection_id)
        if row is None:
            raise ConnectionUnavailable("Connection not found", connection_id=connection_id, status="missing")
        status = normalize_status(row)
        if status == STATUS_DISCONNECTED:
            raise ConnectionUnavailable(
                "Connection is disconnected", connection_id=connection_id, status=STATUS_DISCONNECTED
            )
        try:
            secrets = read_secrets(row)
        except CredentialDecryptionError:
            secrets, failure = {}, DECRYPT_ERROR
        token_info = secrets.get("token_info") if not failure else None
        if not failure and not token_info:
            failure = "No stored sign-in for this connection. Reconnect to continue."
        if not failure:
            auth = ConnectorCreator.create_auth(row["provider"])
            rejected = bool(rejected_access_token) and token_info.get("access_token") == rejected_access_token
            if rejected or auth.is_token_expired(token_info):
                refresh_token = token_info.get("refresh_token")
                if not refresh_token:
                    failure = "The sign-in expired and cannot be renewed. Reconnect to continue."
                else:
                    try:
                        refreshed = auth.refresh_access_token(refresh_token)
                    except Exception as exc:  # classified below
                        if _is_auth_failure(exc):
                            failure = f"The provider rejected the stored sign-in: {type(exc).__name__}"
                        else:
                            transient = exc
                    else:
                        merged = {**token_info, **{k: v for k, v in refreshed.items() if v is not None}}
                        token_info = auth.sanitize_token_info(merged)
                        write_secrets(
                            conn, row, {**secrets, "token_info": token_info},
                            status=STATUS_CONNECTED, last_error=None,
                        )
        if not failure and transient is None:
            repo.update(connection_id, {"last_used_at": _now()})
    if failure:
        mark_reconnect_needed(connection_id, failure)
        raise ConnectionUnavailable(failure, connection_id=connection_id)
    if transient is not None:
        raise TransientConnectionError(str(transient)) from transient
    return token_info


def _now():
    import datetime

    return datetime.datetime.now(datetime.timezone.utc)


def get_credentials(row: dict) -> dict:
    """The pasted credentials (API keys) of an ``api_key`` connection.

    Raises:
        ConnectionUnavailable: Disconnected, flagged, or undecryptable.
    """
    status = normalize_status(row)
    if status in (STATUS_DISCONNECTED, STATUS_RECONNECT):
        raise ConnectionUnavailable(f"Connection is {status}", connection_id=str(row["id"]), status=status)
    secrets = load_secrets(row)
    if secrets is None:
        raise ConnectionUnavailable(DECRYPT_ERROR, connection_id=str(row["id"]))
    return dict(secrets.get("credentials") or {})


def access_credentials(row: dict) -> dict:
    """What a loader or tool authenticates with through this connection.

    Pasted credentials for an ``api_key`` connection. An OAuth connection
    whose token a loader or tool sends itself (GitHub's App sign-in) gives
    its current access token as ``access_token``, refreshed first when it
    has expired.

    Raises:
        ConnectionUnavailable: Disconnected, flagged, undecryptable, or the
            refresh was refused (the connection is then flagged).
        TransientConnectionError: The provider failed in a retryable way.
    """
    if (row.get("auth_kind") or "") == "oauth":
        status = normalize_status(row)
        if status in (STATUS_DISCONNECTED, STATUS_RECONNECT):
            raise ConnectionUnavailable(f"Connection is {status}", connection_id=str(row["id"]), status=status)
        return {"access_token": get_valid_token_info(str(row["id"])).get("access_token")}
    return get_credentials(row)


def _api_key_account(
    repo: ConnectorSessionsRepository,
    user_id: str,
    connector_key: str,
    server_url: Optional[str],
    label: str,
    credentials: dict,
) -> tuple[Optional[dict], str]:
    """The connection holding exactly ``credentials``, or a free label for a new one.

    A label (a hint of the key, or what the user typed) is not an identity:
    two different keys can share it. A row under the label is reused only
    when it holds the same credentials; otherwise the label gets a
    ``(2)``, ``(3)`` suffix until it names a matching row or no row.

    Returns:
        ``(row, label)``: the row to reuse (None to create one) and its label.
    """
    from docsgpt.security.encryption import CredentialDecryptionError

    candidate, suffix = label, 1
    while True:
        existing = repo.find_account(user_id, connector_key, server_url=server_url, account_label=candidate)
        if existing is None:
            return None, candidate
        try:
            if (read_secrets(existing).get("credentials") or {}) == credentials:
                return existing, candidate
        except CredentialDecryptionError:
            pass
        suffix += 1
        candidate = f"{label} ({suffix})"


def create_api_key_connection(
    conn,
    user_id: str,
    definition,
    credentials: dict,
    *,
    label: Optional[str] = None,
    server_url: Optional[str] = None,
    display_name: Optional[str] = None,
) -> tuple[dict, bool]:
    """Store a connection for pasted credentials, or reuse the matching one.

    The same credentials for the same service map to one connection
    ("enter secrets once"): adding a second tool or bucket reuses it.

    Args:
        conn: Open connection inside a transaction.
        user_id: The owner.
        definition: The catalog entry (``api_key`` or ``custom_mcp``).
        credentials: Field key to value, as the user entered them.
        label: What the account is called; defaults to a hint of the key.
        server_url: Base URL, for custom MCP servers.
        display_name: Name shown for custom connectors.

    Returns:
        ``(row, created)``.

    Raises:
        ConnectorDisabled: An admin turned the connector off. Checked first,
            so callers that fall back to a legacy path on the other errors
            never do so for a disabled connector. A custom MCP server at a
            preset's address is that preset (see
            :func:`catalog.connector_key_for_row`), so its switch applies.
        ValueError: A required credential field is missing.
        EncryptionKeyNotConfigured: See :func:`ensure_can_store_credentials`.
    """
    preset = catalog.preset_for_url(server_url) if definition.key == "custom_mcp" else None
    ensure_connector_allowed(conn, preset.key if preset else definition.key)
    fields = {f.key: f for f in definition.credential_fields}
    if fields:
        missing = [f.label for f in fields.values() if f.required and not str(credentials.get(f.key) or "").strip()]
        if missing:
            raise ValueError(f"Missing credentials: {', '.join(missing)}")
        credentials = {k: v for k, v in credentials.items() if k in fields and v not in (None, "")}
    else:
        credentials = {k: v for k, v in credentials.items() if v not in (None, "")}
    ensure_can_store_credentials()
    secret_values = {k: v for k, v in credentials.items() if (fields.get(k).secret if fields.get(k) else True)}
    repo = ConnectorSessionsRepository(conn)
    existing, account_label = _api_key_account(
        repo, user_id, definition.key, server_url, label or credential_hint(secret_values or credentials), credentials,
    )
    if existing is not None:
        write_secrets(conn, existing, {"credentials": credentials}, status=STATUS_CONNECTED, last_error=None)
        resume_sources(conn, str(existing["id"]))
        return repo.get(str(existing["id"])), False
    from docsgpt.security.encryption import encrypt_json

    row = repo.create(
        user_id,
        definition.key,
        connector_key=definition.key,
        auth_kind="api_key",
        display_name=display_name or definition.name,
        account_label=account_label,
        server_url=server_url,
        encrypted_credentials=encrypt_json({"credentials": credentials}, user_id),
    )
    if row is None:  # lost a race with an identical insert
        row = repo.find_account(user_id, definition.key, server_url=server_url, account_label=account_label)
        return row, False
    return row, True


# ---------------------------------------------------------------------------
# OAuth sign-in
# ---------------------------------------------------------------------------


def begin_oauth(conn, user_id: str, provider: str, connection_id: Optional[str] = None) -> dict:
    """The row an OAuth sign-in writes into when it completes.

    Reconnecting passes the connection being reconnected. A new sign-in
    gets a pending row with no account label; the callback moves the tokens
    onto the existing row for that account if there is one.

    Raises:
        ConnectionUnavailable: ``connection_id`` is not the caller's
            connection for ``provider``.
    """
    from sqlalchemy import text

    repo = ConnectorSessionsRepository(conn)
    if connection_id:
        row = repo.get_for_user(connection_id, user_id)
        if row is None or row.get("provider") != provider:
            raise ConnectionUnavailable("Connection not found", connection_id=connection_id, status="missing")
        return row
    ensure_connector_allowed(conn, provider)
    definition = catalog.get_definition(provider)
    result = conn.execute(
        text(
            """
            INSERT INTO connector_sessions (user_id, provider, status, connector_key, auth_kind, display_name)
            VALUES (:user_id, :provider, 'pending', :provider, 'oauth', :display_name)
            ON CONFLICT (user_id, provider, COALESCE(server_url, ''), COALESCE(account_label, ''))
            DO UPDATE SET status = CASE
                WHEN connector_sessions.status IN ('connected', 'authorized') THEN connector_sessions.status
                ELSE 'pending' END
            RETURNING *
            """
        ),
        {"user_id": user_id, "provider": provider, "display_name": definition.name if definition else provider},
    )
    from docsgpt.storage.db.base_repository import row_to_dict

    return row_to_dict(result.fetchone())


def complete_oauth(conn, state_row: dict, provider: str, token_info: dict, account: str) -> dict:
    """Store a finished OAuth sign-in and return the connection it belongs to.

    Signing in to an account that already has a connection updates that
    connection (and drops the pending placeholder), so reconnecting from any
    entry point heals every source and tool of the account. Reconnecting a
    connection but signing in to a different account never rewrites it (its
    sources and tools would silently run as the new account): the new
    account gets its own connection and the original keeps its status.

    Args:
        conn: Open connection inside a transaction.
        state_row: The row named in the OAuth ``state``.
        provider: ``google_drive``, ``share_point`` or ``confluence``.
        token_info: Sanitised token info from the provider.
        account: The account's email or name, shown as "Connected as".

    Returns:
        The connection now holding the sign-in.
    """
    import uuid

    repo = ConnectorSessionsRepository(conn)
    target = state_row
    definition = catalog.get_definition(provider)
    display_name = definition.name if definition else provider
    existing = repo.find_account(state_row["user_id"], provider, server_url=None, account_label=account)
    if existing is not None and str(existing["id"]) != str(state_row["id"]):
        target = existing
        if not has_credentials(state_row) and normalize_status(state_row) == STATUS_PENDING:
            repo.delete_by_id(str(state_row["id"]))
    elif existing is None and state_row.get("account_label"):
        # The row belongs to another account (a reconnect that signed in as someone else).
        target = repo.create(
            state_row["user_id"], provider, connector_key=provider, auth_kind="oauth",
            display_name=display_name, account_label=account, status=STATUS_PENDING,
        ) or repo.find_account(state_row["user_id"], provider, server_url=None, account_label=account)
    write_secrets(
        conn,
        target,
        {"token_info": token_info},
        status=STATUS_CONNECTED,
        # Kept for frontends from before connections; new ones use the id.
        session_token=str(uuid.uuid4()),
        user_email=account,
        account_label=account,
        connector_key=provider,
        auth_kind="oauth",
        display_name=display_name,
        last_error=None,
    )
    resume_sources(conn, str(target["id"]))
    return repo.get(str(target["id"]))


def picker_token(connection_id: str) -> dict:
    """What a browser-side picker needs: a short-lived access token, never the refresh token."""
    token_info = get_valid_token_info(connection_id)
    return {
        "access_token": token_info.get("access_token"),
        "expiry": token_info.get("expiry"),
        "allows_shared_content": bool(token_info.get("allows_shared_content")),
    }


def claim_session_token(conn, user_id: str, provider: str, session_token: str) -> Optional[dict]:
    """Link a legacy browser session token to its connection, once.

    Returns the connection when the token belongs to ``user_id`` and
    ``provider``. The token itself keeps working for the session-token
    routes during this release, so an older tab does not break.
    """
    repo = ConnectorSessionsRepository(conn)
    row = repo.get_by_session_token(session_token)
    if not row or row.get("user_id") != user_id or (row.get("provider") or "").lower() != provider.lower():
        return None
    return row


def resolve_request_connection(user_id: str, provider: Optional[str], data: dict) -> Optional[dict]:
    """The caller's connection a request names, by ``connection_id`` or legacy ``session_token``.

    Returns None unless the caller owns the connection and it belongs to
    ``provider`` (when given).
    """
    connection_id = data.get("connection_id")
    session_token = data.get("session_token")
    if not connection_id and not session_token:
        return None
    with db_readonly() as conn:
        repo = ConnectorSessionsRepository(conn)
        if connection_id:
            row = repo.get_for_user(str(connection_id), user_id)
        else:
            row = repo.get_by_session_token(session_token)
            if not owns_connector_session(row, user_id, provider):
                return None
    if row is None:
        return None
    if provider and (row.get("provider") or "").lower() != provider.lower():
        return None
    return row


# ---------------------------------------------------------------------------
# MCP OAuth token storage
# ---------------------------------------------------------------------------


def mcp_provider(base_url: str) -> str:
    """``provider`` value MCP OAuth connections are stored under."""
    return f"mcp:{base_url}"


def _mcp_row(conn, user_id: str, base_url: str, connection_id: Optional[str], *, lock: bool = False):
    from sqlalchemy import text

    from docsgpt.storage.db.base_repository import row_to_dict

    repo = ConnectorSessionsRepository(conn)
    if connection_id:
        row = repo.get_for_update(connection_id) if lock else repo.get(connection_id)
        # A connection's tokens only ever go to its own server. Ownership is
        # checked where the id is chosen (the tool executor); clients cannot
        # supply one (see ``_sanitize_mcp_transport``).
        if row is None or row.get("provider") != mcp_provider(base_url):
            return None
        return row
    result = conn.execute(
        text(
            "SELECT * FROM connector_sessions WHERE user_id = :user_id AND provider = :provider "
            "ORDER BY updated_at DESC LIMIT 1" + (" FOR UPDATE" if lock else "")
        ),
        {"user_id": user_id, "provider": mcp_provider(base_url)},
    )
    row = result.fetchone()
    return row_to_dict(row) if row is not None else None


def read_mcp_secrets(user_id: str, base_url: str, connection_id: Optional[str] = None) -> dict:
    """The MCP OAuth ``tokens`` and ``client_info`` of a server connection."""
    with db_readonly() as conn:
        row = _mcp_row(conn, user_id, base_url, connection_id)
    if row is None:
        return {}
    return load_secrets(row) or {}


def update_mcp_secrets(
    user_id: str,
    base_url: str,
    patch: dict,
    *,
    connection_id: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    """Merge ``patch`` into an MCP connection's secrets (``None`` drops a key).

    Creates the connection on first use, named after the matching preset or
    the server's host.

    Returns:
        The connection row after the update.
    """
    from docsgpt.security.encryption import CredentialDecryptionError

    with db_session() as conn:
        repo = ConnectorSessionsRepository(conn)
        row = _mcp_row(conn, user_id, base_url, connection_id, lock=True)
        if row is None:
            row = repo.merge_session_data(user_id, mcp_provider(base_url), base_url, {})
        try:
            secrets = read_secrets(row)
        except CredentialDecryptionError:
            secrets = {}
        for key, value in patch.items():
            if value is None:
                secrets.pop(key, None)
            else:
                secrets[key] = value
        fields: dict = {}
        if status:
            fields["status"] = status
            if status == STATUS_CONNECTED:
                fields["last_error"] = None
        elif not row.get("status"):
            fields["status"] = STATUS_CONNECTED if secrets.get("tokens") else STATUS_PENDING
        if not row.get("connector_key"):
            preset = catalog.preset_for_url(base_url)
            fields["connector_key"] = preset.key if preset else "custom_mcp"
            fields["auth_kind"] = "mcp_oauth"
            fields["display_name"] = preset.name if preset else base_url.split("://")[-1]
        write_secrets(conn, row, secrets, **fields)
        if fields.get("status") == STATUS_CONNECTED:
            resume_sources(conn, str(row["id"]))
        return repo.get(str(row["id"]))


# ---------------------------------------------------------------------------
# Tools created from a connection
# ---------------------------------------------------------------------------


def _transform_actions(actions: list) -> list:
    """``transform_actions`` from the tools API: active, LLM-filled parameters."""
    transformed = []
    for action in actions:
        action = dict(action)
        action["active"] = True
        parameters = action.get("parameters")
        if isinstance(parameters, dict):
            for details in (parameters.get("properties") or {}).values():
                if isinstance(details, dict):
                    details["filled_by_llm"] = True
                    details["value"] = ""
        transformed.append(action)
    return transformed


def create_tool_for_connection(
    conn,
    user_id: str,
    connection: dict,
    *,
    template: Optional[str] = None,
    display_name: Optional[str] = None,
    config: Optional[dict] = None,
    actions: Optional[list] = None,
    permissions: Optional[dict] = None,
    status: bool = True,
) -> dict:
    """Create the tool a connection provides, with read / write defaults.

    Writes default to "Needs approval", reads to "Always allow"; the
    ``permissions`` map (action name to ``always`` / ``ask`` / ``off``)
    overrides them. Secrets are never copied onto the tool: the executor
    reads them from the connection at run time.

    Args:
        conn: Open connection inside a transaction.
        user_id: The owner of the connection and the new tool.
        connection: The connection row.
        template: ``user_tools`` name; defaults to the connector's first template.
        display_name: Name shown for the tool.
        config: Non-secret tool configuration (an MCP server URL, say).
        actions: Action metadata; defaults to the tool class's own.
        permissions: Per-action permission overrides.
        status: Whether the tool starts enabled.

    Returns:
        The new ``user_tools`` row.
    """
    from docsgpt.agents.tools.tool_manager import ToolManager
    from docsgpt.connectors.permissions import apply_default_permissions, apply_permission
    from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

    key = catalog.connector_key_for_row(connection)
    definition = catalog.get_definition(key)
    template = template or (definition.tool_templates[0] if definition and definition.tool_templates else None)
    if not template:
        raise ValueError(f"Connector {key} provides no tool")
    tool = ToolManager(config={}).tools.get(template)
    if tool is None:
        raise ValueError(f"Unknown tool template: {template}")
    doc = (tool.__doc__ or template).strip().split("\n", 1)
    if actions is None:
        actions = tool.get_actions_metadata()
    actions = apply_default_permissions(template, _transform_actions(actions))
    for index, action in enumerate(actions):
        permission = (permissions or {}).get(action.get("name"))
        if permission:
            actions[index] = apply_permission(action, permission)
    name = display_name or (serialize_connection(connection)["name"] if connection else doc[0].strip())
    return UserToolsRepository(conn).create(
        user_id,
        template,
        config=dict(config or {}),
        custom_name=name,
        display_name=name,
        description=doc[1].strip() if len(doc) > 1 else "",
        config_requirements=tool.get_config_requirements(),
        actions=actions,
        status=status,
        connection_id=str(connection["id"]),
    )


def split_secrets(config: dict, config_requirements: dict) -> tuple[dict, dict]:
    """``(public, secrets)``: a tool config split by its secret requirements."""
    secret_keys = {k for k, spec in (config_requirements or {}).items() if spec.get("secret")}
    public = {k: v for k, v in config.items() if k not in secret_keys}
    secrets = {k: v for k, v in config.items() if k in secret_keys and v not in (None, "")}
    return public, secrets


def ensure_connection_tools(conn, user_id: str, connection: dict, permissions: Optional[dict] = None) -> list[dict]:
    """Create the connector's tools once; later calls return the existing ones.

    This is what makes the setup step idempotent for tools: a retried or
    repeated setup never creates a second Telegram tool for the same bot.
    """
    repo = ConnectorSessionsRepository(conn)
    existing = repo.list_tools(str(connection["id"]))
    key = catalog.connector_key_for_row(connection)
    definition = catalog.get_definition(key)
    if not definition or not definition.tool_templates:
        return existing
    have = {tool.get("name") for tool in existing}
    created = []
    for template in definition.tool_templates:
        if template in have or template in ("mcp_tool", "api_tool"):
            # MCP tools are created by the MCP save flow, which has the
            # discovered actions; OpenAPI tools come from an imported spec.
            continue
        created.append(
            create_tool_for_connection(conn, user_id, connection, template=template, permissions=permissions)
        )
    return existing + created


def remove_connection(conn, row: dict, *, sources: str = "keep", tools: str = "delete") -> list[dict]:
    """Delete a connection, choosing what happens to what it feeds.

    Args:
        conn: Open connection inside a transaction.
        row: The connection, already authorised for its owner.
        sources: ``keep`` (content stays, syncing stops) or ``delete``.
        tools: ``delete`` (the default: they cannot work without it) or ``keep``.

    Returns:
        The source rows the caller must delete with their indexes (empty
        when ``sources`` is ``keep``). Index files live outside the database,
        so the caller deletes them after this transaction commits.
    """
    from sqlalchemy import text

    from docsgpt.security.encryption import CredentialDecryptionError

    repo = ConnectorSessionsRepository(conn)
    connection_id = str(row["id"])
    linked_sources = repo.list_sources(connection_id)
    try:
        revoke_at_provider(row, read_secrets(row))
    except CredentialDecryptionError:
        pass
    if tools == "delete":
        conn.execute(
            text("DELETE FROM user_tools WHERE connection_id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": connection_id, "user_id": row["user_id"]},
        )
    else:
        conn.execute(
            text("UPDATE user_tools SET status = false WHERE connection_id = CAST(:id AS uuid)"),
            {"id": connection_id},
        )
    conn.execute(
        text(
            "UPDATE sources SET sync_frequency = 'never', metadata = metadata - 'sync_state' "
            "WHERE connection_id = CAST(:id AS uuid)"
        ),
        {"id": connection_id},
    )
    repo.delete_by_id(connection_id)
    return linked_sources if sources == "delete" else []


def set_tool_permissions(
    conn, user_id: str, connection_id: str, tool_id: str, permissions: dict,
) -> Optional[dict]:
    """Apply ``{action: always | ask | off}`` to a tool the user owns.

    Args:
        conn: Open database connection.
        user_id: The caller, who must own the tool.
        connection_id: The connection the tool must belong to.
        tool_id: The tool to update.
        permissions: Action name to ``always``, ``ask`` or ``off``.

    Returns:
        The updated tool, or None (nothing written) when the tool is not the
        user's or belongs to another connection.
    """
    from docsgpt.connectors.permissions import apply_permission
    from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

    tools = UserToolsRepository(conn)
    tool = tools.get_any(tool_id, user_id)
    if tool is None or tool.get("user_id") != user_id or str(tool.get("connection_id")) != connection_id:
        return None
    actions = [
        apply_permission(action, permissions[action.get("name")]) if action.get("name") in permissions else action
        for action in (_json(tool.get("actions")) or [])
    ]
    tools.update(str(tool["id"]), user_id, {"actions": actions})
    return tools.get_any(str(tool["id"]), user_id)


def reencrypt_all(batch_size: int = 500) -> dict:
    """Rewrite every connection's credentials with the current key.

    Run after rotating ENCRYPTION_SECRET_KEY with the old value in
    ENCRYPTION_SECRET_KEY_PREVIOUS; afterwards the previous key can go.

    Returns:
        ``{"rewritten": n, "current": n, "failed": n}``; failed rows (neither
        key opens them) are flagged ``reconnect_needed``.
    """
    from sqlalchemy import text

    from docsgpt.security.encryption import CredentialDecryptionError, current_key_id, envelope_key_id

    key_id = current_key_id()
    counts = {"rewritten": 0, "current": 0, "failed": 0}
    failed_ids: list[str] = []
    last_id = "00000000-0000-0000-0000-000000000000"
    while True:
        with db_session() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM connector_sessions WHERE encrypted_credentials IS NOT NULL "
                    "AND id > CAST(:last AS uuid) ORDER BY id LIMIT :batch FOR UPDATE"
                ),
                {"last": last_id, "batch": batch_size},
            ).fetchall()
            if not rows:
                break
            from docsgpt.storage.db.base_repository import row_to_dict

            for raw in rows:
                row = row_to_dict(raw)
                last_id = str(row["id"])
                if envelope_key_id(row["encrypted_credentials"]) == key_id:
                    counts["current"] += 1
                    continue
                try:
                    secrets = read_secrets(row)
                except CredentialDecryptionError:
                    counts["failed"] += 1
                    failed_ids.append(last_id)
                    continue
                write_secrets(conn, row, secrets)
                counts["rewritten"] += 1
    for connection_id in failed_ids:
        mark_reconnect_needed(connection_id, DECRYPT_ERROR)
    return counts


# ---------------------------------------------------------------------------
# Admin policy
# ---------------------------------------------------------------------------


class ConnectorDisabled(Exception):
    """An admin turned this connector (or custom MCP servers) off."""


def custom_mcp_allowed(conn) -> bool:
    """The instance-wide "Allow custom MCP servers" switch (on unless turned off)."""
    from docsgpt.storage.db.repositories.app_metadata import AppMetadataRepository
    from docsgpt.storage.db.repositories.connector_policies import ALLOW_CUSTOM_MCP_KEY

    return AppMetadataRepository(conn).get(ALLOW_CUSTOM_MCP_KEY) != "false"


def connector_is_enabled(policies: dict, connector_key: Optional[str]) -> bool:
    """Whether a connector is switched on.

    An admin's explicit switch wins. Without one, a connector is on when it
    has the server settings it needs, so one that still needs admin setup
    starts off and members never see it.

    Args:
        policies: ``connector_key`` to policy row, from :func:`load_policies`.
        connector_key: The catalog key.
    """
    explicit = (policies.get(connector_key) or {}).get("enabled") if connector_key else None
    if explicit is not None:
        return bool(explicit)
    definition = catalog.get_definition(connector_key) if connector_key else None
    return definition is None or definition.configured


def load_policies(conn) -> dict[str, dict]:
    """Every connector's policy, with custom MCP folded in from its switch."""
    from docsgpt.storage.db.repositories.connector_policies import ConnectorPoliciesRepository

    policies = dict(ConnectorPoliciesRepository(conn).all())
    if not custom_mcp_allowed(conn):
        policies["custom_mcp"] = {**policies.get("custom_mcp", {}), "enabled": False}
    return policies


def connector_enabled(conn, row: dict) -> bool:
    """Whether an admin left on the connector a connection row belongs to.

    Args:
        conn: Open database connection.
        row: A ``connector_sessions`` row.

    Returns:
        False when the connector (or custom MCP servers) is turned off.
    """
    return connector_is_enabled(load_policies(conn), catalog.connector_key_for_row(row))


def ensure_connector_allowed(conn, connector_key: Optional[str]) -> None:
    """Refuse a new connection to a connector an admin turned off.

    Raises:
        ConnectorDisabled: The connector, or custom MCP servers, are off.
    """
    if not connector_key:
        return
    if not connector_is_enabled(load_policies(conn), connector_key):
        raise ConnectorDisabled(f"{connector_key} is turned off by an admin")


def forced_credential_mode(conn, connector_key: Optional[str]) -> Optional[str]:
    """``owner`` or ``member`` when an admin forces one for this connector."""
    if not connector_key:
        return None
    mode = (load_policies(conn).get(connector_key) or {}).get("credential_mode")
    return mode if mode in ("owner", "member") else None
