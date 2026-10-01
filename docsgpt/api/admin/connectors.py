"""Admin > Connectors: turn connectors on or off and set sharing policy.

Every resource here is behind ``@admin_required`` (the frontend guard is
cosmetic). The page also shows what each OAuth connector still needs from
the server (settings and the redirect URI to register), never their values.
"""

from __future__ import annotations

import logging

from flask import jsonify, make_response, request
from flask_restx import Resource
from sqlalchemy import text

from docsgpt.api.admin.routes import _actor, admin_ns
from docsgpt.api.user.authz import admin_required
from docsgpt.connectors import catalog, service
from docsgpt.core.settings import settings
from docsgpt.security.encryption import is_default_encryption_key
from docsgpt.storage.db.repositories.app_metadata import AppMetadataRepository
from docsgpt.storage.db.repositories.auth_events import AuthEventsRepository
from docsgpt.storage.db.repositories.connector_policies import (
    ALLOW_CUSTOM_MCP_KEY,
    CREDENTIAL_POLICIES,
    ConnectorPoliciesRepository,
    allow_writes_key,
)
from docsgpt.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)


def _connection_counts(conn) -> dict[str, int]:
    rows = conn.execute(
        text(
            "SELECT connector_key, provider, server_url, count(*) AS n FROM connector_sessions "
            "WHERE COALESCE(status, '') <> 'pending' GROUP BY connector_key, provider, server_url"
        )
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        key = catalog.connector_key_for_row(dict(row._mapping))
        if key:
            counts[key] = counts.get(key, 0) + int(row.n)
    return counts


def _policy_state(conn, keys) -> dict:
    """The effective policy of each connector in ``keys``, plus the custom MCP switch.

    Args:
        conn: Database connection.
        keys: Connector keys to read.

    Returns:
        ``{key: {"enabled", "credential_mode", "allow_writes"}, "allow_custom_mcp": bool}``.
    """
    policies = ConnectorPoliciesRepository(conn).all()
    loaded = service.load_policies(conn)
    state: dict = {}
    for key in keys:
        definition = catalog.get_definition(key)
        policy = policies.get(key) or {}
        state[key] = {
            "enabled": service.connector_is_enabled(policies, key),
            "credential_mode": policy.get("credential_mode", "choose"),
            "allow_writes": service.writes_allowed(loaded, key) if definition.mcp_write_url else None,
        }
    state["allow_custom_mcp"] = service.custom_mcp_allowed(conn)
    return state


def _policy_changes(before: dict, after: dict) -> dict:
    """What a PUT changed, as ``[old, new]`` pairs; empty when it changed nothing.

    Args:
        before: The connector policy state before the change, keyed by connector (plus
            top-level switches such as ``allow_custom_mcp``).
        after: The same state after the change, with the same keys.

    Returns:
        For a top-level value that changed, ``[old, new]``; for a connector, a dict of
        its changed fields to ``[old, new]``. Unchanged keys are left out.
    """
    changes: dict = {}
    for key, old in before.items():
        new = after[key]
        if not isinstance(old, dict):
            if old != new:
                changes[key] = [old, new]
            continue
        fields = {field: [old[field], new[field]] for field in old if old[field] != new[field]}
        if fields:
            changes[key] = fields
    return changes


def _connections_blocked() -> bool:
    """Whether every new connection is refused (multi-user install on the default key).

    Returns:
        bool: True when ``service.ensure_can_store_credentials`` refuses.
    """
    try:
        service.ensure_can_store_credentials()
    except service.EncryptionKeyNotConfigured:
        return True
    return False


def _mcp_redirect_uri() -> str:
    from docsgpt.agents.tools.mcp_tool import MCPTool

    return MCPTool._resolve_redirect_uri(MCPTool.__new__(MCPTool), None)


@admin_ns.route("/admin/connectors")
class AdminConnectorsResource(Resource):
    @admin_required
    def get(self):
        """Every connector with its policy, setup state and connection count."""
        with db_readonly() as conn:
            policies = ConnectorPoliciesRepository(conn).all()
            loaded = service.load_policies(conn)
            allow_custom = service.custom_mcp_allowed(conn)
            counts = _connection_counts(conn)
        connectors = []
        for definition in catalog.all_definitions():
            policy = policies.get(definition.key) or {}
            connectors.append(
                {
                    "key": definition.key,
                    "name": definition.name,
                    "icon": definition.icon,
                    "category": definition.category,
                    "publisher": definition.publisher,
                    "auth_kind": definition.auth_kind,
                    "capabilities": list(definition.capabilities),
                    "enabled": service.connector_is_enabled(policies, definition.key),
                    "credential_mode": policy.get("credential_mode", "choose"),
                    "configured": definition.configured,
                    "required_settings": [
                        {"name": name, "set": bool(getattr(settings, name, None))}
                        for name in definition.required_settings
                    ],
                    # Optional: they add a second sign-in (GitHub's App) to a
                    # connector that already works without them.
                    "oauth_settings": [
                        {"name": name, "set": bool(getattr(settings, name, None))}
                        for name in definition.oauth_settings
                    ],
                    "oauth_configured": definition.oauth_configured,
                    "connection_count": counts.get(definition.key, 0),
                    "docs_url": definition.docs_url,
                    "mcp_url": definition.mcp_url,
                    # Whether members may let agents make changes (GitHub);
                    # None where the connector offers no such choice.
                    "allow_writes": (
                        service.writes_allowed(loaded, definition.key) if definition.mcp_write_url else None
                    ),
                }
            )
        return make_response(
            jsonify(
                {
                    "success": True,
                    "connectors": connectors,
                    "allow_custom_mcp": allow_custom,
                    "default_encryption_key": is_default_encryption_key(),
                    # Members' connects are refused, so the rows say "Blocked".
                    "connections_blocked": _connections_blocked(),
                    "oauth_redirect_uri": settings.CONNECTOR_REDIRECT_BASE_URI,
                    "mcp_redirect_uri": _mcp_redirect_uri(),
                }
            ),
            200,
        )

    @admin_required
    def put(self):
        """Update policies: {policies: {key: {enabled?, credential_mode?, allow_writes?}}, allow_custom_mcp?}."""
        body = request.get_json(silent=True) or {}
        updates = body.get("policies") or {}
        if not isinstance(updates, dict):
            return make_response(jsonify({"success": False, "message": "policies must be an object"}), 400)
        for key, change in updates.items():
            if catalog.get_definition(key) is None or not isinstance(change, dict):
                return make_response(jsonify({"success": False, "message": f"Unknown connector: {key}"}), 400)
            mode = change.get("credential_mode")
            if mode is not None and mode not in CREDENTIAL_POLICIES:
                return make_response(jsonify({"success": False, "message": "Unknown credential mode"}), 400)
            if "enabled" in change and not isinstance(change["enabled"], bool):
                return make_response(jsonify({"success": False, "message": "enabled must be true or false"}), 400)
            if "allow_writes" in change:
                if not catalog.get_definition(key).mcp_write_url:
                    return make_response(
                        jsonify({"success": False, "message": f"{key} has no write access to allow"}), 400,
                    )
                if not isinstance(change["allow_writes"], bool):
                    return make_response(
                        jsonify({"success": False, "message": "allow_writes must be true or false"}), 400,
                    )
        allow_custom = body.get("allow_custom_mcp")
        if allow_custom is not None and not isinstance(allow_custom, bool):
            return make_response(jsonify({"success": False, "message": "allow_custom_mcp must be a boolean"}), 400)
        actor = _actor()
        with db_session() as conn:
            before = _policy_state(conn, updates)
            repo = ConnectorPoliciesRepository(conn)
            for key, change in updates.items():
                if "allow_writes" in change:
                    value = "true" if change["allow_writes"] else "false"
                    AppMetadataRepository(conn).set(allow_writes_key(key), value)
                if set(change) == {"allow_writes"}:
                    continue
                repo.upsert(
                    key,
                    enabled=change.get("enabled"),
                    credential_mode=change.get("credential_mode"),
                    updated_by=actor,
                )
            if allow_custom is not None:
                AppMetadataRepository(conn).set(ALLOW_CUSTOM_MCP_KEY, "true" if allow_custom else "false")
            changes = _policy_changes(before, _policy_state(conn, updates))
            if changes:
                metadata = {"by": actor, "via": "admin_api", "policies": updates, "changes": changes}
                if allow_custom is not None:
                    metadata["allow_custom_mcp"] = allow_custom
                AuthEventsRepository(conn).insert(
                    # Instance configuration, not an account: filed under the acting admin, with no target.
                    actor or "unknown",
                    "connector_policy_set",
                    ip=request.remote_addr,
                    user_agent=request.headers.get("User-Agent"),
                    metadata=metadata,
                    actor_id=actor or "unknown",
                    target_id=None,
                )
        logger.info("connector_policies_updated", extra={"admin": actor, "connectors": sorted(updates)})
        return self.get()
