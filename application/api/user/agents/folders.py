"""
Agent folders management routes.
Provides virtual folder organization for agents (Google Drive-like structure).
"""

import datetime
from bson.objectid import ObjectId
from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource, fields

from application.api import api
from application.api.user.base import (
    agent_folders_collection,
    agents_collection,
)

agents_folders_ns = Namespace(
    "agents_folders", description="Agent folder management", path="/api/agents/folders"
)


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
        except Exception as e:
            return make_response(jsonify({"success": False, "message": str(e)}), 400)

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
            return make_response(
                jsonify({"id": str(result.inserted_id), "name": data["name"], "parent_id": parent_id}),
                201,
            )
        except Exception as e:
            return make_response(jsonify({"success": False, "message": str(e)}), 400)


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
        except Exception as e:
            return make_response(jsonify({"success": False, "message": str(e)}), 400)

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
            return make_response(jsonify({"success": True}), 200)
        except Exception as e:
            return make_response(jsonify({"success": False, "message": str(e)}), 400)

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
            agent_folders_collection.update_many(
                {"user": user, "parent_id": folder_id}, {"$unset": {"parent_id": ""}}
            )
            result = agent_folders_collection.delete_one({"_id": ObjectId(folder_id), "user": user})
            if result.deleted_count == 0:
                return make_response(jsonify({"success": False, "message": "Folder not found"}), 404)
            return make_response(jsonify({"success": True}), 200)
        except Exception as e:
            return make_response(jsonify({"success": False, "message": str(e)}), 400)


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

            return make_response(jsonify({"success": True}), 200)
        except Exception as e:
            return make_response(jsonify({"success": False, "message": str(e)}), 400)


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
            return make_response(jsonify({"success": True}), 200)
        except Exception as e:
            return make_response(jsonify({"success": False, "message": str(e)}), 400)
