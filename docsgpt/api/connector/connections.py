"""Connectors catalog and connections API.

``/api/connectors/catalog`` lists every service DocsGPT can connect to, with
whether the server is set up for it and the caller's connection summary.
``/api/connections`` lists and manages the caller's connections. Responses
never include tokens or secrets.
"""

from __future__ import annotations

from flask import current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource

from docsgpt.api import api
from docsgpt.api.user.authz import ROLE_ADMIN, has_role
from docsgpt.connectors import service
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.session import db_readonly, db_session

connections_ns = Namespace("connections", description="Connectors and connections", path="/api")
api.add_namespace(connections_ns)


def _user_id() -> str | None:
    token = getattr(request, "decoded_token", None)
    return token.get("sub") if isinstance(token, dict) else None


def _unauthorized():
    return make_response(jsonify({"success": False, "error": "Unauthorized"}), 401)


def _not_found():
    return make_response(jsonify({"success": False, "error": "Connection not found"}), 404)


@connections_ns.route("/connectors/catalog")
class ConnectorCatalog(Resource):
    @api.doc(description="Every connector with its availability and the caller's connection summary")
    def get(self):
        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        try:
            with db_readonly() as conn:
                entries = service.catalog_for_user(
                    conn, user_id, is_admin=has_role(request.decoded_token, ROLE_ADMIN),
                )
        except Exception as err:
            current_app.logger.error(f"Error building connector catalog: {err}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to load connectors"}), 500)
        return make_response(jsonify({"success": True, "connectors": entries}), 200)


@connections_ns.route("/connections")
class ConnectionsList(Resource):
    @api.doc(description="The caller's connections with status and linked resource counts")
    def get(self):
        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        try:
            with db_readonly() as conn:
                connections = service.list_connections(conn, user_id)
        except Exception as err:
            current_app.logger.error(f"Error listing connections: {err}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to load connections"}), 500)
        return make_response(jsonify({"success": True, "connections": connections}), 200)


@connections_ns.route("/connections/<string:connection_id>")
class ConnectionDetail(Resource):
    @api.doc(description="One connection with the sources it syncs and the tools it provides")
    def get(self, connection_id: str):
        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        try:
            with db_readonly() as conn:
                row = ConnectorSessionsRepository(conn).get_for_user(connection_id, user_id)
                if row is None:
                    return _not_found()
                detail = service.connection_detail(conn, row)
        except Exception as err:
            current_app.logger.error(f"Error loading connection: {err}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to load connection"}), 500)
        return make_response(jsonify({"success": True, "connection": detail}), 200)


@connections_ns.route("/connections/<string:connection_id>/disconnect")
class ConnectionDisconnect(Resource):
    @api.doc(description="Delete a connection's stored credentials; its sources and tools stay")
    def post(self, connection_id: str):
        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        try:
            with db_session() as conn:
                row = ConnectorSessionsRepository(conn).get_for_user(connection_id, user_id)
                if row is None:
                    return _not_found()
                connection = service.disconnect(conn, row)
        except Exception as err:
            current_app.logger.error(f"Error disconnecting connection: {err}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to disconnect"}), 500)
        return make_response(jsonify({"success": True, "connection": connection}), 200)
