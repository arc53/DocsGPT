"""
Agent folders management routes.
Provides virtual folder organization for agents (Google Drive-like structure).
"""

import datetime
from bson.objectid import ObjectId
from flask import current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource, fields

from application.api import api
from application.api.user.base import (
    agent_folders_collection,
    agents_collection,
)
from sqlalchemy import text as _sql_text

from application.storage.db.dual_write import dual_write
from application.storage.db.repositories.agent_folders import AgentFoldersRepository
from application.storage.db.repositories.agents import AgentsRepository


def _resolve_folder_pg_uuid(conn, folder_mongo_id: str, user_id: str) -> str | None:
    """Best-effort Mongo folder ObjectId → Postgres UUID resolver.

    The ``agent_folders`` table has no ``legacy_mongo_id`` column in the
    current schema, so this currently always returns None. Kept as a
    single resolution point for when the column lands — dual_write call
    sites don't have to change then.
    """
    if not folder_mongo_id:
        return None
    try:
        row = conn.execute(
            _sql_text(
                "SELECT id FROM agent_folders "
                "WHERE legacy_mongo_id = :legacy_id AND user_id = :user_id"
            ),
            {"legacy_id": str(folder_mongo_id), "user_id": user_id},
        ).fetchone()
    except Exception:
        return None
    return str(row[0]) if row else None

agents_folders_ns = Namespace(
    "agents_folders", description="Agent folder management", path="/api/agents/folders"
)


def _folder_error_response(message: str, err: Exception):
    current_app.logger.error(f"{message}: {err}", exc_info=True)
    return make_response(jsonify({"success": False, "message": message}), 400)


@agents_folders_ns.route("/")
class AgentFolders(Resource):
    @api.doc(description="Get all folders for the user")
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            folders = list(agent_folders_collection.find({"user": user}))
            result = [
                {
                    "id": str(f["_id"]),
                    "name": f["name"],
                    "parent_id": f.get("parent_id"),
                    "created_at": f.get("created_at", "").isoformat() if f.get("created_at") else None,
                    "updated_at": f.get("updated_at", "").isoformat() if f.get("updated_at") else None,
                }
                for f in folders
            ]
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

        parent_id = data.get("parent_id")
        if parent_id:
            parent = agent_folders_collection.find_one({"_id": ObjectId(parent_id), "user": user})
            if not parent:
                return make_response(jsonify({"success": False, "message": "Parent folder not found"}), 404)

        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            folder = {
                "user": user,
                "name": data["name"],
                "parent_id": parent_id,
                "created_at": now,
                "updated_at": now,
            }
            result = agent_folders_collection.insert_one(folder)
            mongo_id = str(result.inserted_id)
            description_value = data.get("description")

            def _mirror_create_folder(
                repo,
                u=user,
                n=data["name"],
                desc=description_value,
                pid_legacy=parent_id,
                mid=mongo_id,
            ):
                # Resolve the Mongo parent ObjectId to a PG UUID via
                # legacy_mongo_id; fall back to None if the parent
                # row hasn't been backfilled yet.
                pg_parent_id = None
                if pid_legacy:
                    parent_row = repo.get_by_legacy_id(pid_legacy, u)
                    if parent_row is not None:
                        pg_parent_id = parent_row["id"]
                repo.create(
                    u, n,
                    description=desc,
                    parent_id=pg_parent_id,
                    legacy_mongo_id=mid,
                )

            dual_write(AgentFoldersRepository, _mirror_create_folder)
            return make_response(
                jsonify({"id": str(result.inserted_id), "name": data["name"], "parent_id": parent_id}),
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
            folder = agent_folders_collection.find_one({"_id": ObjectId(folder_id), "user": user})
            if not folder:
                return make_response(jsonify({"success": False, "message": "Folder not found"}), 404)
            
            agents = list(agents_collection.find({"user": user, "folder_id": folder_id}))
            agents_list = [
                {"id": str(a["_id"]), "name": a["name"], "description": a.get("description", "")}
                for a in agents
            ]
            subfolders = list(agent_folders_collection.find({"user": user, "parent_id": folder_id}))
            subfolders_list = [{"id": str(sf["_id"]), "name": sf["name"]} for sf in subfolders]

            return make_response(
                jsonify({
                    "id": str(folder["_id"]),
                    "name": folder["name"],
                    "parent_id": folder.get("parent_id"),
                    "agents": agents_list,
                    "subfolders": subfolders_list,
                }),
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
            update_fields = {"updated_at": datetime.datetime.now(datetime.timezone.utc)}
            if "name" in data:
                update_fields["name"] = data["name"]
            if "parent_id" in data:
                if data["parent_id"] == folder_id:
                    return make_response(jsonify({"success": False, "message": "Cannot set folder as its own parent"}), 400)
                update_fields["parent_id"] = data["parent_id"]

            result = agent_folders_collection.update_one(
                {"_id": ObjectId(folder_id), "user": user}, {"$set": update_fields}
            )
            if result.matched_count == 0:
                return make_response(jsonify({"success": False, "message": "Folder not found"}), 404)

            # Mirror the update into Postgres. ``parent_id`` arrives as
            # a Mongo ObjectId; resolve via ``legacy_mongo_id`` to a PG
            # UUID before writing. Pass through ``name``/``description``
            # as-is (the repo's update whitelist enforces the column set).
            mirror_fields: dict = {}
            if "name" in data:
                mirror_fields["name"] = data["name"]
            if "description" in data:
                mirror_fields["description"] = data["description"]
            parent_legacy = data.get("parent_id") if "parent_id" in data else None

            def _mirror_folder_update(
                repo,
                u=user,
                fid_legacy=folder_id,
                mfields=mirror_fields,
                pid_legacy=parent_legacy,
                has_parent_key="parent_id" in data,
            ):
                folder_row = repo.get_by_legacy_id(fid_legacy, u)
                if folder_row is None:
                    return
                update_payload = dict(mfields)
                if has_parent_key:
                    if pid_legacy:
                        parent_row = repo.get_by_legacy_id(pid_legacy, u)
                        update_payload["parent_id"] = (
                            parent_row["id"] if parent_row else None
                        )
                    else:
                        update_payload["parent_id"] = None
                if update_payload:
                    repo.update(folder_row["id"], u, update_payload)

            dual_write(AgentFoldersRepository, _mirror_folder_update)

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
            agents_collection.update_many(
                {"user": user, "folder_id": folder_id}, {"$unset": {"folder_id": ""}}
            )
            # Postgres mirror: clear the folder assignment from every
            # agent owned by this user whose folder matches. The folder
            # ObjectId → PG UUID lookup is best-effort and is silently
            # skipped when the folder hasn't been backfilled yet.
            def _clear_folder(repo: AgentsRepository, fid=folder_id, u=user) -> None:
                pg_folder_id = _resolve_folder_pg_uuid(repo._conn, fid, u)
                if pg_folder_id:
                    repo.clear_folder_for_all(pg_folder_id, u)
            dual_write(AgentsRepository, _clear_folder)
            agent_folders_collection.update_many(
                {"user": user, "parent_id": folder_id}, {"$unset": {"parent_id": ""}}
            )
            result = agent_folders_collection.delete_one({"_id": ObjectId(folder_id), "user": user})
            dual_write(
                AgentFoldersRepository,
                lambda repo, fid=folder_id, u=user: repo.delete(fid, u),
            )
            if result.deleted_count == 0:
                return make_response(jsonify({"success": False, "message": "Folder not found"}), 404)
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

        agent_id = data["agent_id"]
        folder_id = data.get("folder_id")

        try:
            agent = agents_collection.find_one({"_id": ObjectId(agent_id), "user": user})
            if not agent:
                return make_response(jsonify({"success": False, "message": "Agent not found"}), 404)

            if folder_id:
                folder = agent_folders_collection.find_one({"_id": ObjectId(folder_id), "user": user})
                if not folder:
                    return make_response(jsonify({"success": False, "message": "Folder not found"}), 404)
                agents_collection.update_one(
                    {"_id": ObjectId(agent_id)}, {"$set": {"folder_id": folder_id}}
                )
            else:
                agents_collection.update_one(
                    {"_id": ObjectId(agent_id)}, {"$unset": {"folder_id": ""}}
                )

            # Postgres mirror. We need the PG agent UUID (looked up by
            # legacy_mongo_id) and, if setting a folder, the PG folder
            # UUID (also looked up by legacy). Either lookup missing
            # falls back to a no-op.
            def _mirror_move(
                repo: AgentsRepository, aid=agent_id, fid=folder_id, u=user,
            ) -> None:
                agent_row = repo.get_by_legacy_id(aid, u)
                if agent_row is None:
                    return
                pg_folder_id = (
                    _resolve_folder_pg_uuid(repo._conn, fid, u) if fid else None
                )
                if fid and pg_folder_id is None:
                    # Target folder isn't backfilled yet — skip.
                    return
                repo.set_folder(agent_row["id"], u, pg_folder_id)

            dual_write(AgentsRepository, _mirror_move)
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
        folder_id = data.get("folder_id")

        try:
            if folder_id:
                folder = agent_folders_collection.find_one({"_id": ObjectId(folder_id), "user": user})
                if not folder:
                    return make_response(jsonify({"success": False, "message": "Folder not found"}), 404)

            object_ids = [ObjectId(aid) for aid in agent_ids]
            if folder_id:
                agents_collection.update_many(
                    {"_id": {"$in": object_ids}, "user": user},
                    {"$set": {"folder_id": folder_id}},
                )
            else:
                agents_collection.update_many(
                    {"_id": {"$in": object_ids}, "user": user},
                    {"$unset": {"folder_id": ""}},
                )

            def _mirror_bulk_move(
                repo: AgentsRepository, aids=agent_ids, fid=folder_id, u=user,
            ) -> None:
                pg_folder_id = (
                    _resolve_folder_pg_uuid(repo._conn, fid, u) if fid else None
                )
                if fid and pg_folder_id is None:
                    return
                for mongo_aid in aids:
                    agent_row = repo.get_by_legacy_id(mongo_aid, u)
                    if agent_row is not None:
                        repo.set_folder(agent_row["id"], u, pg_folder_id)

            dual_write(AgentsRepository, _mirror_bulk_move)
            return make_response(jsonify({"success": True}), 200)
        except Exception as err:
            return _folder_error_response("Failed to move agents", err)
