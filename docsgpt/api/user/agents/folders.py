"""``/api/agents/folders/*``: the agent folder routes, kept as aliases of ``/api/folders`` with ``type=agent``.

Existing clients, tokens and docs call these. They follow the same rules
(:mod:`docsgpt.api.user.folders.service`): a list or a create works in the
request's workspace (the team's one tree in a team), a route about one folder
goes by the folder's own tree, and in a team changing anything needs Editor.
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
    folder_by_id,
    list_folders,
    serialize_folder,
    update_folder,
    visible_item_id,
    workspace_tree,
)
from docsgpt.api.user.resource_access import payload_for, settings_many
from docsgpt.api.user.team_sharing import visible_with_access
from docsgpt.storage.db.repositories.folders import FoldersRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.workspaces.context import WorkspaceError, current_workspace


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
    @api.doc(description="The workspace's folder tree, as GET /api/folders?type=agent")
    def get(self):
        user = _user()
        if not user:
            return make_response(jsonify({"success": False}), 401)
        try:
            with db_readonly() as conn:
                tree = workspace_tree(current_workspace(conn))
                tree.require("list")
                result = list_folders(conn, user, "agent", tree=tree)
            return make_response(jsonify({"folders": result}), 200)
        except (FolderError, WorkspaceError) as err:
            return err.response()
        except Exception as err:
            return _folder_error_response("Failed to fetch folders", err)

    @api.doc(description="Create a folder in the workspace's tree, as POST /api/folders")
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
                tree = workspace_tree(current_workspace(conn))
                tree.require("create")
                folder = create_folder(
                    conn, tree.owner_id, "agent", data["name"], data.get("parent_id"),
                    description=data.get("description"), created_by=user,
                )
        except (FolderError, WorkspaceError) as err:
            return err.response()
        except Exception as err:
            return _folder_error_response("Failed to create folder", err)
        return make_response(jsonify(serialize_folder(folder)), 201)


@agents_folders_ns.route("/<string:folder_id>")
class AgentFolder(Resource):
    @api.doc(description="A folder with the agents filed in it and its subfolders")
    def get(self, folder_id):
        user = _user()
        if not user:
            return make_response(jsonify({"success": False}), 401)
        try:
            with db_readonly() as conn:
                folder, tree = folder_by_id(conn, folder_id, user)
                tree.require("list")
                pg_folder_id = str(folder["id"])
                # A team's tree holds the team's agents; a person's, their own and ones shared with them.
                team = {} if tree.is_team else visible_with_access(conn, user, "agent")
                agents_rows = conn.execute(
                    _sql_text(
                        "SELECT a.id, a.user_id, a.name, a.description, a.starters FROM agents a "
                        "JOIN folder_items fi ON fi.resource_id = a.id AND fi.resource_type = 'agent' "
                        "WHERE fi.user_id = :owner AND fi.folder_id = CAST(:fid AS uuid) "
                        "AND (a.user_id = :owner OR a.id = ANY(CAST(:team AS uuid[]))) "
                        "ORDER BY a.created_at DESC"
                    ),
                    {"owner": tree.owner_id, "fid": pg_folder_id, "team": sorted(team)},
                ).fetchall()
                switches = settings_many(conn, "agent", [str(row._mapping["id"]) for row in agents_rows])
                agents_list = []
                for row in agents_rows:
                    agent = row._mapping
                    aid = str(agent["id"])
                    if tree.is_team:
                        access = payload_for(
                            "agent", None, None, team_id=tree.team_id, team_role=tree.role, policy=tree.policy
                        )
                    else:
                        access = payload_for(
                            "agent", "owner" if agent["user_id"] == user else team.get(aid), switches[aid]
                        )
                    agents_list.append(
                        {
                            "id": aid,
                            "name": agent["name"],
                            "description": agent.get("description", "") or "",
                            "starters": stored_starters(agent),
                            **access,
                        }
                    )
                subfolders = FoldersRepository(conn).list_children(pg_folder_id, tree.owner_id)
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

    @api.doc(description="Rename or move a folder, as PUT /api/folders/<id>")
    def put(self, folder_id):
        user = _user()
        if not user:
            return make_response(jsonify({"success": False}), 401)
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not data:
            return make_response(jsonify({"success": False, "message": "No data provided"}), 400)
        try:
            with db_session() as conn:
                folder, tree = folder_by_id(conn, folder_id, user)
                if "name" in data or "description" in data:
                    tree.require("rename")
                if "parent_id" in data:
                    tree.require("move")
                kwargs = {key: data[key] for key in ("name", "parent_id", "description") if key in data}
                update_folder(conn, tree.owner_id, folder, **kwargs)
            return make_response(jsonify({"success": True}), 200)
        except FolderError as err:
            return err.response()
        except Exception as err:
            return _folder_error_response("Failed to update folder", err)

    @api.doc(description="Delete a folder; its folders and items move to its parent")
    def delete(self, folder_id):
        user = _user()
        if not user:
            return make_response(jsonify({"success": False}), 401)
        try:
            with db_session() as conn:
                folder, tree = folder_by_id(conn, folder_id, user)
                tree.require("delete")
                moved = delete_folder(conn, folder)
            return make_response(jsonify({"success": True, **moved}), 200)
        except FolderError as err:
            return err.response()
        except Exception as err:
            return _folder_error_response("Failed to delete folder", err)


@agents_folders_ns.route("/move_agent")
class MoveAgentToFolder(Resource):
    @api.doc(
        description="File an agent into a folder, or take it out of the workspace's tree (as POST /api/folders/items)"
    )
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
                tree = None if data.get("folder_id") else workspace_tree(current_workspace(conn))
                file_items(conn, user, "agent", data.get("folder_id"), [data["agent_id"]], tree=tree)
            return make_response(jsonify({"success": True}), 200)
        except (FolderError, WorkspaceError) as err:
            return err.response()
        except Exception as err:
            return _folder_error_response("Failed to move agent", err)


@agents_folders_ns.route("/bulk_move")
class BulkMoveAgents(Resource):
    @api.doc(description="File several agents into a folder (null takes them out of the workspace's tree)")
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
                tree = None if data.get("folder_id") else workspace_tree(current_workspace(conn))
                moved, skipped = file_items(conn, user, "agent", data.get("folder_id"), data["agent_ids"], tree=tree)
            return make_response(jsonify({"success": True, "moved": moved, "skipped": skipped}), 200)
        except (FolderError, WorkspaceError) as err:
            return err.response()
        except Exception as err:
            return _folder_error_response("Failed to move agents", err)
