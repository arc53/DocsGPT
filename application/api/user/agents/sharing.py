"""Agent management sharing functionality."""

import datetime, secrets

from bson import DBRef
from bson.objectid import ObjectId
from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource

from application.api import api
from application.api.user.base import (
    agents_collection,
    db,
    ensure_user_doc,
    resolve_tool_details,
    user_tools_collection,
    users_collection,
)
from application.utils import generate_image_url

agents_sharing_ns = Namespace(
    "agents", description="Agent management operations", path="/api"
)


@agents_sharing_ns.route("/shared_agent")
class SharedAgent(Resource):
    @api.doc(
        params={
            "token": "Shared token of the agent",
        },
        description="Get a shared agent by token or ID",
    )
    def get(self):
        shared_token = request.args.get("token")

        if not shared_token:
            return make_response(
                jsonify({"success": False, "message": "Token or ID is required"}), 400
            )
        try:
            query = {
                "shared_publicly": True,
                "shared_token": shared_token,
            }
            shared_agent = agents_collection.find_one(query)
            if not shared_agent:
                return make_response(
                    jsonify({"success": False, "message": "Shared agent not found"}),
                    404,
                )
            agent_id = str(shared_agent["_id"])
            data = {
                "id": agent_id,
                "user": shared_agent.get("user", ""),
                "name": shared_agent.get("name", ""),
                "image": (
                    generate_image_url(shared_agent["image"])
                    if shared_agent.get("image")
                    else ""
                ),
                "description": shared_agent.get("description", ""),
                "source": (
                    str(source_doc["_id"])
                    if isinstance(shared_agent.get("source"), DBRef)
                    and (source_doc := db.dereference(shared_agent.get("source")))
                    else ""
                ),
                "chunks": shared_agent.get("chunks", "0"),
                "retriever": shared_agent.get("retriever", "classic"),
                "prompt_id": shared_agent.get("prompt_id", "default"),
                "tools": shared_agent.get("tools", []),
                "tool_details": resolve_tool_details(shared_agent.get("tools", [])),
                "agent_type": shared_agent.get("agent_type", ""),
                "status": shared_agent.get("status", ""),
                "json_schema": shared_agent.get("json_schema"),
                "created_at": shared_agent.get("createdAt", ""),
                "updated_at": shared_agent.get("updatedAt", ""),
                "shared": shared_agent.get("shared_publicly", False),
                "shared_token": shared_agent.get("shared_token", ""),
                "shared_metadata": shared_agent.get("shared_metadata", {}),
            }

            if data["tools"]:
                enriched_tools = []
                for tool in data["tools"]:
                    tool_data = user_tools_collection.find_one({"_id": ObjectId(tool)})
                    if tool_data:
                        enriched_tools.append(tool_data.get("name", ""))
                data["tools"] = enriched_tools
            decoded_token = getattr(request, "decoded_token", None)
            if decoded_token:
                user_id = decoded_token.get("sub")
                owner_id = shared_agent.get("user")

                if user_id != owner_id:
                    ensure_user_doc(user_id)
                    users_collection.update_one(
                        {"user_id": user_id},
                        {"$addToSet": {"agent_preferences.shared_with_me": agent_id}},
                    )
            return make_response(jsonify(data), 200)
        except Exception as err:
            current_app.logger.error(f"Error retrieving shared agent: {err}")
            return make_response(jsonify({"success": False}), 400)


@agents_sharing_ns.route("/shared_agents")
class SharedAgents(Resource):
    @api.doc(description="Get shared agents explicitly shared with the user")
    def get(self):
        try:
            decoded_token = request.decoded_token
            if not decoded_token:
                return make_response(jsonify({"success": False}), 401)
            user_id = decoded_token.get("sub")

            user_doc = ensure_user_doc(user_id)
            shared_with_ids = user_doc.get("agent_preferences", {}).get(
                "shared_with_me", []
            )
            shared_object_ids = [ObjectId(id) for id in shared_with_ids]

            shared_agents_cursor = agents_collection.find(
                {"_id": {"$in": shared_object_ids}, "shared_publicly": True}
            )
            shared_agents = list(shared_agents_cursor)

            found_ids_set = {str(agent["_id"]) for agent in shared_agents}
            stale_ids = [id for id in shared_with_ids if id not in found_ids_set]
            if stale_ids:
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$pullAll": {"agent_preferences.shared_with_me": stale_ids}},
                )
            pinned_ids = set(user_doc.get("agent_preferences", {}).get("pinned", []))

            list_shared_agents = [
                {
                    "id": str(agent["_id"]),
                    "name": agent.get("name", ""),
                    "description": agent.get("description", ""),
                    "image": (
                        generate_image_url(agent["image"]) if agent.get("image") else ""
                    ),
                    "tools": agent.get("tools", []),
                    "tool_details": resolve_tool_details(agent.get("tools", [])),
                    "agent_type": agent.get("agent_type", ""),
                    "status": agent.get("status", ""),
                    "json_schema": agent.get("json_schema"),
                    "created_at": agent.get("createdAt", ""),
                    "updated_at": agent.get("updatedAt", ""),
                    "pinned": str(agent["_id"]) in pinned_ids,
                    "shared": agent.get("shared_publicly", False),
                    "shared_token": agent.get("shared_token", ""),
                    "shared_metadata": agent.get("shared_metadata", {}),
                }
                for agent in shared_agents
            ]

            return make_response(jsonify(list_shared_agents), 200)
        except Exception as err:
            current_app.logger.error(f"Error retrieving shared agents: {err}")
            return make_response(jsonify({"success": False}), 400)


@agents_sharing_ns.route("/share_agent")
class ShareAgent(Resource):
    @api.expect(
        api.model(
            "ShareAgentModel",
            {
                "id": fields.String(required=True, description="ID of the agent"),
                "shared": fields.Boolean(
                    required=True, description="Share or unshare the agent"
                ),
                "username": fields.String(
                    required=False, description="Name of the user"
                ),
            },
        )
    )
    @api.doc(description="Share or unshare an agent")
    def put(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")

        data = request.get_json()
        if not data:
            return make_response(
                jsonify({"success": False, "message": "Missing JSON body"}), 400
            )
        agent_id = data.get("id")
        shared = data.get("shared")
        username = data.get("username", "")

        if not agent_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )
        if shared is None:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Shared parameter is required and must be true or false",
                    }
                ),
                400,
            )
        try:
            try:
                agent_oid = ObjectId(agent_id)
            except Exception:
                return make_response(
                    jsonify({"success": False, "message": "Invalid agent ID"}), 400
                )
            agent = agents_collection.find_one({"_id": agent_oid, "user": user})
            if not agent:
                return make_response(
                    jsonify({"success": False, "message": "Agent not found"}), 404
                )
            if shared:
                shared_metadata = {
                    "shared_by": username,
                    "shared_at": datetime.datetime.now(datetime.timezone.utc),
                }
                shared_token = secrets.token_urlsafe(32)
                agents_collection.update_one(
                    {"_id": agent_oid, "user": user},
                    {
                        "$set": {
                            "shared_publicly": shared,
                            "shared_metadata": shared_metadata,
                            "shared_token": shared_token,
                        }
                    },
                )
            else:
                agents_collection.update_one(
                    {"_id": agent_oid, "user": user},
                    {"$set": {"shared_publicly": shared, "shared_token": None}},
                    {"$unset": {"shared_metadata": ""}},
                )
        except Exception as err:
            current_app.logger.error(f"Error sharing/unsharing agent: {err}")
            return make_response(jsonify({"success": False, "error": str(err)}), 400)
        shared_token = shared_token if shared else None
        return make_response(
            jsonify({"success": True, "shared_token": shared_token}), 200
        )
