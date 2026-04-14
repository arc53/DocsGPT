"""Agent management sharing functionality."""

import datetime
import secrets

from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource
from sqlalchemy import text as _sql_text

from application.api import api
from application.core.settings import settings
from application.api.user.base import resolve_tool_details
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.users import UsersRepository
from application.storage.db.session import db_readonly, db_session
from application.utils import generate_image_url

agents_sharing_ns = Namespace(
    "agents", description="Agent management operations", path="/api"
)


def _serialize_agent_basic(agent: dict) -> dict:
    """Shape a PG agent row into the API response dict."""
    source_id = agent.get("source_id")
    return {
        "id": str(agent["id"]),
        "user": agent.get("user_id", ""),
        "name": agent.get("name", ""),
        "image": (
            generate_image_url(agent["image"]) if agent.get("image") else ""
        ),
        "description": agent.get("description", ""),
        "source": str(source_id) if source_id else "",
        "chunks": agent.get("chunks", 0) if agent.get("chunks") is not None else "0",
        "retriever": agent.get("retriever", "classic") or "classic",
        "prompt_id": str(agent["prompt_id"]) if agent.get("prompt_id") else "default",
        "tools": agent.get("tools", []) or [],
        "tool_details": resolve_tool_details(agent.get("tools", []) or []),
        "agent_type": agent.get("agent_type", "") or "",
        "status": agent.get("status", "") or "",
        "json_schema": agent.get("json_schema"),
        "limited_token_mode": agent.get("limited_token_mode", False),
        "token_limit": agent.get("token_limit") or settings.DEFAULT_AGENT_LIMITS["token_limit"],
        "limited_request_mode": agent.get("limited_request_mode", False),
        "request_limit": agent.get("request_limit") or settings.DEFAULT_AGENT_LIMITS["request_limit"],
        "created_at": agent.get("created_at", ""),
        "updated_at": agent.get("updated_at", ""),
        "shared": bool(agent.get("shared", False)),
        "shared_token": agent.get("shared_token", "") or "",
        "shared_metadata": agent.get("shared_metadata", {}) or {},
    }


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
            with db_readonly() as conn:
                shared_agent = AgentsRepository(conn).find_by_shared_token(
                    shared_token,
                )
            if not shared_agent:
                return make_response(
                    jsonify({"success": False, "message": "Shared agent not found"}),
                    404,
                )
            agent_id = str(shared_agent["id"])
            data = _serialize_agent_basic(shared_agent)

            if data["tools"]:
                enriched_tools = []
                for detail in data["tool_details"]:
                    enriched_tools.append(detail.get("name", ""))
                data["tools"] = enriched_tools
            decoded_token = getattr(request, "decoded_token", None)
            if decoded_token:
                user_id = decoded_token.get("sub")
                owner_id = shared_agent.get("user_id")

                if user_id != owner_id:
                    with db_session() as conn:
                        users_repo = UsersRepository(conn)
                        users_repo.upsert(user_id)
                        users_repo.add_shared(user_id, agent_id)
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

            with db_session() as conn:
                users_repo = UsersRepository(conn)
                user_doc = users_repo.upsert(user_id)
                shared_with_ids = (
                    user_doc.get("agent_preferences", {}).get("shared_with_me", [])
                    if isinstance(user_doc.get("agent_preferences"), dict)
                    else []
                )
                # Keep only UUID-shaped ids; ObjectId leftovers are stripped below.
                uuid_ids = [sid for sid in shared_with_ids if looks_like_uuid(sid)]
                non_uuid_ids = [sid for sid in shared_with_ids if not looks_like_uuid(sid)]

                if uuid_ids:
                    result = conn.execute(
                        _sql_text(
                            "SELECT * FROM agents "
                            "WHERE id = ANY(CAST(:ids AS uuid[])) "
                            "AND shared = true"
                        ),
                        {"ids": uuid_ids},
                    )
                    shared_agents = [dict(row._mapping) for row in result.fetchall()]
                else:
                    shared_agents = []

                found_ids_set = {str(agent["id"]) for agent in shared_agents}
                stale_ids = [sid for sid in uuid_ids if sid not in found_ids_set]
                stale_ids.extend(non_uuid_ids)
                if stale_ids:
                    users_repo.remove_shared_bulk(user_id, stale_ids)

                pinned_ids = set(
                    user_doc.get("agent_preferences", {}).get("pinned", [])
                    if isinstance(user_doc.get("agent_preferences"), dict)
                    else []
                )

            list_shared_agents = []
            for agent in shared_agents:
                agent_id_str = str(agent["id"])
                list_shared_agents.append(
                    {
                        "id": agent_id_str,
                        "name": agent.get("name", ""),
                        "description": agent.get("description", ""),
                        "image": (
                            generate_image_url(agent["image"]) if agent.get("image") else ""
                        ),
                        "tools": agent.get("tools", []) or [],
                        "tool_details": resolve_tool_details(
                            agent.get("tools", []) or []
                        ),
                        "agent_type": agent.get("agent_type", "") or "",
                        "status": agent.get("status", "") or "",
                        "json_schema": agent.get("json_schema"),
                        "limited_token_mode": agent.get("limited_token_mode", False),
                        "token_limit": agent.get("token_limit") or settings.DEFAULT_AGENT_LIMITS["token_limit"],
                        "limited_request_mode": agent.get("limited_request_mode", False),
                        "request_limit": agent.get("request_limit") or settings.DEFAULT_AGENT_LIMITS["request_limit"],
                        "created_at": agent.get("created_at", ""),
                        "updated_at": agent.get("updated_at", ""),
                        "pinned": agent_id_str in pinned_ids,
                        "shared": bool(agent.get("shared", False)),
                        "shared_token": agent.get("shared_token", "") or "",
                        "shared_metadata": agent.get("shared_metadata", {}) or {},
                    }
                )

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
        shared_token = None
        try:
            with db_session() as conn:
                repo = AgentsRepository(conn)
                agent = repo.get_any(agent_id, user)
                if not agent:
                    return make_response(
                        jsonify({"success": False, "message": "Agent not found"}), 404
                    )
                if shared:
                    shared_metadata = {
                        "shared_by": username,
                        "shared_at": datetime.datetime.now(
                            datetime.timezone.utc
                        ).isoformat(),
                    }
                    shared_token = secrets.token_urlsafe(32)
                    repo.update(
                        str(agent["id"]), user,
                        {
                            "shared": True,
                            "shared_token": shared_token,
                            "shared_metadata": shared_metadata,
                        },
                    )
                else:
                    repo.update(
                        str(agent["id"]), user,
                        {
                            "shared": False,
                            "shared_token": None,
                            "shared_metadata": None,
                        },
                    )
        except Exception as err:
            current_app.logger.error(f"Error sharing/unsharing agent: {err}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to update agent sharing status"}), 400)
        return make_response(
            jsonify({"success": True, "shared_token": shared_token}), 200
        )
