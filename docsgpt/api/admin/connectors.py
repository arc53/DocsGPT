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
from docsgpt.storage.db.repositories.connector_policies import (
    ALLOW_CUSTOM_MCP_KEY,
    CREDENTIAL_POLICIES,
    ConnectorPoliciesRepository,
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
                    "enabled": service.connector_is_enabled(policies, definition.key),
                    "credential_mode": policy.get("credential_mode", "choose"),
                    "configured": definition.configured,
                    "required_settings": [
                        {"name": name, "set": bool(getattr(settings, name, None))}
                        for name in definition.required_settings
                    ],
                    "connection_count": counts.get(definition.key, 0),
                    "docs_url": definition.docs_url,
                    "mcp_url": definition.mcp_url,
                }
            )
        return make_response(
            jsonify(
                {
                    "success": True,
                    "connectors": connectors,
                    "allow_custom_mcp": allow_custom,
                    "default_encryption_key": is_default_encryption_key(),
                    "oauth_redirect_uri": settings.CONNECTOR_REDIRECT_BASE_URI,
                    "mcp_redirect_uri": _mcp_redirect_uri(),
                }
            ),
            200,
        )

    @admin_required
    def put(self):
        """Update policies: {policies: {key: {enabled?, credential_mode?}}, allow_custom_mcp?}."""
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
        allow_custom = body.get("allow_custom_mcp")
        if allow_custom is not None and not isinstance(allow_custom, bool):
            return make_response(jsonify({"success": False, "message": "allow_custom_mcp must be a boolean"}), 400)
        actor = _actor()
        with db_session() as conn:
            repo = ConnectorPoliciesRepository(conn)
            for key, change in updates.items():
                repo.upsert(
                    key,
                    enabled=change.get("enabled"),
                    credential_mode=change.get("credential_mode"),
                    updated_by=actor,
                )
            if allow_custom is not None:
                AppMetadataRepository(conn).set(ALLOW_CUSTOM_MCP_KEY, "true" if allow_custom else "false")
        logger.info("connector_policies_updated", extra={"admin": actor, "connectors": sorted(updates)})
        return self.get()
