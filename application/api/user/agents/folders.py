"""
Agent folders management routes.
Provides virtual folder organization for agents (Google Drive-like structure).
"""

from flask import current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource, fields
from sqlalchemy import text as _sql_text

from application.api import api
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.agent_folders import AgentFoldersRepository
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.session import db_readonly, db_session


agents_folders_ns = Namespace(
    "agents_folders", description="Agent folder management", path="/api/agents/folders"
)


def _resolve_folder_id(repo: AgentFoldersRepository, folder_id: str, user: str):
    """Resolve a folder id that may be either a UUID or legacy Mongo ObjectId."""
    if not folder_id:
        return None
    if looks_like_uuid(folder_id):
        row = repo.get(folder_id, user)
        if row is not None:
            return row
    return repo.get_by_legacy_id(folder_id, user)


def _folder_error_response(message: str, err: Exception):
    current_app.logger.error(f"{message}: {err}", exc_info=True)
    return make_response(jsonify({"success": False, "message": message}), 400)


def _serialize_folder(f: dict) -> dict:
    created_at = f.get("created_at")
    updated_at = f.get("updated_at")
    return {
        "id": str(f["id"]),
        "name": f.get("name"),
        "parent_id": str(f["parent_id"]) if f.get("parent_id") else None,
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
    }


@agents_folders_ns.route("/")
class AgentFolders(Resource):
    @api.doc(description="Get all folders for the user")
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            with db_readonly() as conn:
                folders = AgentFoldersRepository(conn).list_for_user(user)
            result = [_serialize_folder(f) for f in folders]
            return make_response(jsonify({"folders": result}), 200)
        except Exception as err:
            return _folder_error_response("Failed to fetch folders", err)

    @api.doc(description="Create a new folder")
    @api.expect(
        api.model(
            "CreateFolder",
            {
                "name": fields.String(required=True, description="Folder name"),
                "parent_id": fields.String(required=False, description="Parent folder ID"),
            },
        )
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        if not data or not data.get("name"):
            return make_response(jsonify({"success": False, "message": "Folder name is required"}), 400)

        parent_id_input = data.get("parent_id")
        description = data.get("description")

        try:
            with db_session() as conn:
                repo = AgentFoldersRepository(conn)
                pg_parent_id = None
                if parent_id_input:
                    parent = _resolve_folder_id(repo, parent_id_input, user)
                    if not parent:
                        return make_response(
                            jsonify({"success": False, "message": "Parent folder not found"}),
                            404,
                        )
                    pg_parent_id = str(parent["id"])
                folder = repo.create(
                    user, data["name"],
                    description=description,
                    parent_id=pg_parent_id,
                )
            return make_response(
                jsonify(
                    {
                        "id": str(folder["id"]),
                        "name": folder["name"],
                        "parent_id": pg_parent_id,
                    }
                ),
                201,
            )
        except Exception as err:
            return _folder_error_response("Failed to create folder", err)


@agents_folders_ns.route("/<string:folder_id>")
class AgentFolder(Resource):
    @api.doc(description="Get a specific folder with its agents")
    def get(self, folder_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            with db_readonly() as conn:
                folders_repo = AgentFoldersRepository(conn)
                folder = _resolve_folder_id(folders_repo, folder_id, user)
                if not folder:
                    return make_response(
                        jsonify({"success": False, "message": "Folder not found"}),
                        404,
                    )
                pg_folder_id = str(folder["id"])

                agents_rows = conn.execute(
                    _sql_text(
                        "SELECT id, name, description FROM agents "
                        "WHERE user_id = :user_id AND folder_id = CAST(:fid AS uuid) "
                        "ORDER BY created_at DESC"
                    ),
                    {"user_id": user, "fid": pg_folder_id},
                ).fetchall()
                agents_list = [
                    {
                        "id": str(row._mapping["id"]),
                        "name": row._mapping["name"],
                        "description": row._mapping.get("description", "") or "",
                    }
                    for row in agents_rows
                ]

                subfolders = folders_repo.list_children(pg_folder_id, user)
                subfolders_list = [
                    {"id": str(sf["id"]), "name": sf["name"]}
                    for sf in subfolders
                ]

            return make_response(
                jsonify(
                    {
                        "id": pg_folder_id,
                        "name": folder["name"],
                        "parent_id": (
                            str(folder["parent_id"]) if folder.get("parent_id") else None
                        ),
                        "agents": agents_list,
                        "subfolders": subfolders_list,
                    }
                ),
                200,
            )
        except Exception as err:
            return _folder_error_response("Failed to fetch folder", err)

    @api.doc(description="Update a folder")
    def put(self, folder_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        if not data:
            return make_response(jsonify({"success": False, "message": "No data provided"}), 400)

        try:
            with db_session() as conn:
                repo = AgentFoldersRepository(conn)
                folder = _resolve_folder_id(repo, folder_id, user)
                if not folder:
                    return make_response(
                        jsonify({"success": False, "message": "Folder not found"}),
                        404,
                    )
                pg_folder_id = str(folder["id"])

                update_fields: dict = {}
                if "name" in data:
                    update_fields["name"] = data["name"]
                if "description" in data:
                    update_fields["description"] = data["description"]
                if "parent_id" in data:
                    parent_input = data.get("parent_id")
                    if parent_input:
                        if parent_input == folder_id or parent_input == pg_folder_id:
                            return make_response(
                                jsonify(
                                    {
                                        "success": False,
                                        "message": "Cannot set folder as its own parent",
                                    }
                                ),
                                400,
                            )
                        parent = _resolve_folder_id(repo, parent_input, user)
                        if not parent:
                            return make_response(
                                jsonify({"success": False, "message": "Parent folder not found"}),
                                404,
                            )
                        if str(parent["id"]) == pg_folder_id:
                            return make_response(
                                jsonify(
                                    {
                                        "success": False,
                                        "message": "Cannot set folder as its own parent",
                                    }
                                ),
                                400,
                            )
                        update_fields["parent_id"] = str(parent["id"])
                    else:
                        update_fields["parent_id"] = None

                if update_fields:
                    repo.update(pg_folder_id, user, update_fields)

            return make_response(jsonify({"success": True}), 200)
        except Exception as err:
            return _folder_error_response("Failed to update folder", err)

    @api.doc(description="Delete a folder")
    def delete(self, folder_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            with db_session() as conn:
                repo = AgentFoldersRepository(conn)
                folder = _resolve_folder_id(repo, folder_id, user)
                if not folder:
                    return make_response(
                        jsonify({"success": False, "message": "Folder not found"}),
                        404,
                    )
                pg_folder_id = str(folder["id"])
                # Clear folder assignments from agents; self-FK
                # ``ON DELETE SET NULL`` handles child folders.
                AgentsRepository(conn).clear_folder_for_all(pg_folder_id, user)
                deleted = repo.delete(pg_folder_id, user)
            if not deleted:
                return make_response(
                    jsonify({"success": False, "message": "Folder not found"}),
                    404,
                )
            return make_response(jsonify({"success": True}), 200)
        except Exception as err:
            return _folder_error_response("Failed to delete folder", err)


@agents_folders_ns.route("/move_agent")
class MoveAgentToFolder(Resource):
    @api.doc(description="Move an agent to a folder or remove from folder")
    @api.expect(
        api.model(
            "MoveAgent",
            {
                "agent_id": fields.String(required=True, description="Agent ID to move"),
                "folder_id": fields.String(required=False, description="Target folder ID (null to remove from folder)"),
            },
        )
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        if not data or not data.get("agent_id"):
            return make_response(jsonify({"success": False, "message": "Agent ID is required"}), 400)

        agent_id_input = data["agent_id"]
        folder_id_input = data.get("folder_id")

        try:
            with db_session() as conn:
                agents_repo = AgentsRepository(conn)
                agent = agents_repo.get_any(agent_id_input, user)
                if not agent:
                    return make_response(
                        jsonify({"success": False, "message": "Agent not found"}),
                        404,
                    )
                pg_folder_id = None
                if folder_id_input:
                    folders_repo = AgentFoldersRepository(conn)
                    folder = _resolve_folder_id(folders_repo, folder_id_input, user)
                    if not folder:
                        return make_response(
                            jsonify({"success": False, "message": "Folder not found"}),
                            404,
                        )
                    pg_folder_id = str(folder["id"])
                agents_repo.set_folder(str(agent["id"]), user, pg_folder_id)
            return make_response(jsonify({"success": True}), 200)
        except Exception as err:
            return _folder_error_response("Failed to move agent", err)


@agents_folders_ns.route("/bulk_move")
class BulkMoveAgents(Resource):
    @api.doc(description="Move multiple agents to a folder")
    @api.expect(
        api.model(
            "BulkMoveAgents",
            {
                "agent_ids": fields.List(fields.String, required=True, description="List of agent IDs"),
                "folder_id": fields.String(required=False, description="Target folder ID"),
            },
        )
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        if not data or not data.get("agent_ids"):
            return make_response(jsonify({"success": False, "message": "Agent IDs are required"}), 400)

        agent_ids = data["agent_ids"]
        folder_id_input = data.get("folder_id")

        try:
            with db_session() as conn:
                agents_repo = AgentsRepository(conn)
                pg_folder_id = None
                if folder_id_input:
                    folders_repo = AgentFoldersRepository(conn)
                    folder = _resolve_folder_id(folders_repo, folder_id_input, user)
                    if not folder:
                        return make_response(
                            jsonify({"success": False, "message": "Folder not found"}),
                            404,
                        )
                    pg_folder_id = str(folder["id"])
                for agent_id_input in agent_ids:
                    agent = agents_repo.get_any(agent_id_input, user)
                    if agent is not None:
                        agents_repo.set_folder(str(agent["id"]), user, pg_folder_id)
            return make_response(jsonify({"success": True}), 200)
        except Exception as err:
            return _folder_error_response("Failed to move agents", err)
