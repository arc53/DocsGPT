"""``/api/agents/folders/*``: the agent folder routes, kept as aliases of ``/api/folders`` with ``type=agent``.

Existing clients, tokens and docs call these. Folders are personal filing
(:mod:`docsgpt.api.user.folders.service`): the caller files any agent they can
see into their own agent folders.
"""

from flask import current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource, fields
from sqlalchemy import text as _sql_text

from docsgpt.api import api
from docsgpt.api.user.agents.starters import stored_starters
from docsgpt.api.user.folders.service import (
    FolderError,
    create_folder,
    delete_folder,
    file_items,
    list_folders,
    resolve_folder,
    serialize_folder,
    update_folder,
    visible_item_id,
)
from docsgpt.api.user.resource_access import payload_for, settings_many
from docsgpt.api.user.team_sharing import visible_with_access
from docsgpt.storage.db.repositories.folders import FoldersRepository
from docsgpt.storage.db.session import db_readonly, db_session


agents_folders_ns = Namespace(
    "agents_folders", description="Agent folder management (aliases of /api/folders?type=agent)",
    path="/api/agents/folders",
)


def _folder_error_response(message: str, err: Exception):
    current_app.logger.error(f"{message}: {err}", exc_info=True)
    return make_response(jsonify({"success": False, "message": message}), 400)


def _user():
    decoded_token = request.decoded_token
    return decoded_token.get("sub") if decoded_token else None


@agents_folders_ns.route("/")
class AgentFolders(Resource):
    @api.doc(description="The caller's agent folders, as GET /api/folders?type=agent")
    def get(self):
        user = _user()
        if not user:
            return make_response(jsonify({"success": False}), 401)
        try:
            with db_readonly() as conn:
                result = list_folders(conn, user, "agent")
            return make_response(jsonify({"folders": result}), 200)
        except Exception as err:
            return _folder_error_response("Failed to fetch folders", err)

    @api.doc(description="Create an agent folder, as POST /api/folders with type=agent")
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
        user = _user()
        if not user:
            return make_response(jsonify({"success": False}), 401)
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not data.get("name"):
            return make_response(
                jsonify({"success": False, "error": "invalid_folder_name", "message": "Folder name is required"}),
                400,
            )
        try:
            with db_session() as conn:
                folder = create_folder(
                    conn, user, "agent", data["name"], data.get("parent_id"), description=data.get("description"),
                )
        except FolderError as err:
            return err.response()
        except Exception as err:
            return _folder_error_response("Failed to create folder", err)
        return make_response(jsonify(serialize_folder(folder)), 201)


@agents_folders_ns.route("/<string:folder_id>")
class AgentFolder(Resource):
    @api.doc(description="An agent folder with the agents the caller filed in it and its subfolders")
    def get(self, folder_id):
        user = _user()
        if not user:
            return make_response(jsonify({"success": False}), 401)
        try:
            with db_readonly() as conn:
                folder = resolve_folder(conn, folder_id, user, "agent")
                pg_folder_id = str(folder["id"])
                team = visible_with_access(conn, user, "agent")
                agents_rows = conn.execute(
                    _sql_text(
                        "SELECT a.id, a.user_id, a.name, a.description, a.starters FROM agents a "
                        "JOIN folder_items fi ON fi.resource_id = a.id AND fi.resource_type = 'agent' "
                        "WHERE fi.user_id = :user_id AND fi.folder_id = CAST(:fid AS uuid) "
                        "AND (a.user_id = :user_id OR a.id = ANY(CAST(:team AS uuid[]))) "
                        "ORDER BY a.created_at DESC"
                    ),
                    {"user_id": user, "fid": pg_folder_id, "team": sorted(team)},
                ).fetchall()
                switches = settings_many(conn, "agent", [str(row._mapping["id"]) for row in agents_rows])
                agents_list = []
                for row in agents_rows:
                    agent = row._mapping
                    aid = str(agent["id"])
                    access = "owner" if agent["user_id"] == user else team.get(aid)
                    agents_list.append(
                        {
                            "id": aid,
                            "name": agent["name"],
                            "description": agent.get("description", "") or "",
                            "starters": stored_starters(agent),
                            **payload_for("agent", access, switches[aid]),
                        }
                    )
                subfolders = FoldersRepository(conn).list_children(pg_folder_id, user)
            return make_response(
                jsonify(
                    {
                        "id": pg_folder_id,
                        "name": folder["name"],
                        "parent_id": str(folder["parent_id"]) if folder.get("parent_id") else None,
                        "agents": agents_list,
                        "subfolders": [{"id": str(sf["id"]), "name": sf["name"]} for sf in subfolders],
                    }
                ),
                200,
            )
        except FolderError as err:
            return err.response()
        except Exception as err:
            return _folder_error_response("Failed to fetch folder", err)

    @api.doc(description="Rename or move an agent folder, as PUT /api/folders/<id>")
    def put(self, folder_id):
        user = _user()
        if not user:
            return make_response(jsonify({"success": False}), 401)
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not data:
            return make_response(jsonify({"success": False, "message": "No data provided"}), 400)
        try:
            with db_session() as conn:
                folder = resolve_folder(conn, folder_id, user, "agent")
                kwargs = {key: data[key] for key in ("name", "parent_id", "description") if key in data}
                update_folder(conn, user, folder, **kwargs)
            return make_response(jsonify({"success": True}), 200)
        except FolderError as err:
            return err.response()
        except Exception as err:
            return _folder_error_response("Failed to update folder", err)

    @api.doc(description="Delete an agent folder; its folders and agents move to its parent")
    def delete(self, folder_id):
        user = _user()
        if not user:
            return make_response(jsonify({"success": False}), 401)
        try:
            with db_session() as conn:
                folder = resolve_folder(conn, folder_id, user, "agent")
                moved = delete_folder(conn, folder)
            return make_response(jsonify({"success": True, **moved}), 200)
        except FolderError as err:
            return err.response()
        except Exception as err:
            return _folder_error_response("Failed to delete folder", err)


@agents_folders_ns.route("/move_agent")
class MoveAgentToFolder(Resource):
    @api.doc(description="File an agent the caller can see into one of their folders, or unfile it")
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
        user = _user()
        if not user:
            return make_response(jsonify({"success": False}), 401)
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not data.get("agent_id"):
            return make_response(jsonify({"success": False, "message": "Agent ID is required"}), 400)
        try:
            with db_session() as conn:
                if visible_item_id(conn, "agent", data["agent_id"], user) is None:
                    return make_response(jsonify({"success": False, "message": "Agent not found"}), 404)
                file_items(conn, user, "agent", data.get("folder_id"), [data["agent_id"]])
            return make_response(jsonify({"success": True}), 200)
        except FolderError as err:
            return err.response()
        except Exception as err:
            return _folder_error_response("Failed to move agent", err)


@agents_folders_ns.route("/bulk_move")
class BulkMoveAgents(Resource):
    @api.doc(description="File several agents into one of the caller's folders (null unfiles them)")
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
        user = _user()
        if not user:
            return make_response(jsonify({"success": False}), 401)
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("agent_ids"), list) or not data["agent_ids"]:
            return make_response(jsonify({"success": False, "message": "Agent IDs are required"}), 400)
        try:
            with db_session() as conn:
                moved, skipped = file_items(conn, user, "agent", data.get("folder_id"), data["agent_ids"])
            return make_response(jsonify({"success": True, "moved": moved, "skipped": skipped}), 200)
        except FolderError as err:
            return err.response()
        except Exception as err:
            return _folder_error_response("Failed to move agents", err)
