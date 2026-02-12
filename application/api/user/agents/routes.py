"""Agent management routes."""

import datetime
import json
import uuid

from bson.dbref import DBRef
from bson.objectid import ObjectId
from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource

from application.api import api
from application.api.user.base import (
    agent_folders_collection,
    agents_collection,
    db,
    ensure_user_doc,
    handle_image_upload,
    resolve_tool_details,
    storage,
    users_collection,
    workflow_edges_collection,
    workflow_nodes_collection,
    workflows_collection,
)
from application.core.settings import settings
from application.utils import (
    check_required_fields,
    generate_image_url,
    validate_required_fields,
)


agents_ns = Namespace("agents", description="Agent management operations", path="/api")


AGENT_TYPE_SCHEMAS = {
    "classic": {
        "required_published": [
            "name",
            "description",
            "chunks",
            "retriever",
            "prompt_id",
        ],
        "required_draft": ["name"],
        "validate_published": ["name", "description", "prompt_id"],
        "validate_draft": [],
        "require_source": True,
        "fields": [
            "user",
            "name",
            "description",
            "agent_type",
            "status",
            "key",
            "image",
            "source",
            "sources",
            "chunks",
            "retriever",
            "prompt_id",
            "tools",
            "json_schema",
            "models",
            "default_model_id",
            "folder_id",
            "limited_token_mode",
            "token_limit",
            "limited_request_mode",
            "request_limit",
            "createdAt",
            "updatedAt",
            "lastUsedAt",
        ],
    },
    "workflow": {
        "required_published": ["name", "workflow"],
        "required_draft": ["name"],
        "validate_published": ["name", "workflow"],
        "validate_draft": [],
        "fields": [
            "user",
            "name",
            "description",
            "agent_type",
            "status",
            "key",
            "workflow",
            "folder_id",
            "limited_token_mode",
            "token_limit",
            "limited_request_mode",
            "request_limit",
            "createdAt",
            "updatedAt",
            "lastUsedAt",
        ],
    },
}

AGENT_TYPE_SCHEMAS["react"] = AGENT_TYPE_SCHEMAS["classic"]
AGENT_TYPE_SCHEMAS["openai"] = AGENT_TYPE_SCHEMAS["classic"]


def normalize_workflow_reference(workflow_value):
    """Normalize workflow references from form/json payloads."""
    if workflow_value is None:
        return None
    if isinstance(workflow_value, dict):
        return (
            workflow_value.get("id")
            or workflow_value.get("_id")
            or workflow_value.get("workflow_id")
        )
    if isinstance(workflow_value, str):
        value = workflow_value.strip()
        if not value:
            return ""
        try:
            parsed = json.loads(value)
            if isinstance(parsed, str):
                return parsed.strip()
            if isinstance(parsed, dict):
                return (
                    parsed.get("id") or parsed.get("_id") or parsed.get("workflow_id")
                )
        except json.JSONDecodeError:
            pass
        return value
    return str(workflow_value)


def validate_workflow_access(workflow_value, user, required=False):
    """Validate workflow reference and ensure ownership."""
    workflow_id = normalize_workflow_reference(workflow_value)
    if not workflow_id:
        if required:
            return None, make_response(
                jsonify({"success": False, "message": "Workflow is required"}), 400
            )
        return None, None
    if not ObjectId.is_valid(workflow_id):
        return None, make_response(
            jsonify({"success": False, "message": "Invalid workflow ID format"}), 400
        )
    workflow = workflows_collection.find_one({"_id": ObjectId(workflow_id), "user": user})
    if not workflow:
        return None, make_response(
            jsonify({"success": False, "message": "Workflow not found"}), 404
        )
    return workflow_id, None


def build_agent_document(
    data, user, key, agent_type, image_url=None, source_field=None, sources_list=None
):
    """Build agent document based on agent type schema."""

    if not agent_type or agent_type not in AGENT_TYPE_SCHEMAS:
        agent_type = "classic"
    schema = AGENT_TYPE_SCHEMAS.get(agent_type, AGENT_TYPE_SCHEMAS["classic"])
    allowed_fields = set(schema["fields"])

    now = datetime.datetime.now(datetime.timezone.utc)
    base_doc = {
        "user": user,
        "name": data.get("name"),
        "description": data.get("description", ""),
        "agent_type": agent_type,
        "status": data.get("status"),
        "key": key,
        "createdAt": now,
        "updatedAt": now,
        "lastUsedAt": None,
    }

    if agent_type == "workflow":
        base_doc["workflow"] = data.get("workflow")
        base_doc["folder_id"] = data.get("folder_id")
    else:
        base_doc.update(
            {
                "image": image_url or "",
                "source": source_field or "",
                "sources": sources_list or [],
                "chunks": data.get("chunks", ""),
                "retriever": data.get("retriever", ""),
                "prompt_id": data.get("prompt_id", ""),
                "tools": data.get("tools", []),
                "json_schema": data.get("json_schema"),
                "models": data.get("models", []),
                "default_model_id": data.get("default_model_id", ""),
                "folder_id": data.get("folder_id"),
            }
        )
    if "limited_token_mode" in allowed_fields:
        base_doc["limited_token_mode"] = (
            data.get("limited_token_mode") == "True"
            if isinstance(data.get("limited_token_mode"), str)
            else bool(data.get("limited_token_mode", False))
        )
    if "token_limit" in allowed_fields:
        base_doc["token_limit"] = int(
            data.get("token_limit", settings.DEFAULT_AGENT_LIMITS["token_limit"])
        )
    if "limited_request_mode" in allowed_fields:
        base_doc["limited_request_mode"] = (
            data.get("limited_request_mode") == "True"
            if isinstance(data.get("limited_request_mode"), str)
            else bool(data.get("limited_request_mode", False))
        )
    if "request_limit" in allowed_fields:
        base_doc["request_limit"] = int(
            data.get("request_limit", settings.DEFAULT_AGENT_LIMITS["request_limit"])
        )
    return {k: v for k, v in base_doc.items() if k in allowed_fields}


@agents_ns.route("/get_agent")
class GetAgent(Resource):
    @api.doc(params={"id": "Agent ID"}, description="Get agent by ID")
    def get(self):
        if not (decoded_token := request.decoded_token):
            return {"success": False}, 401
        if not (agent_id := request.args.get("id")):
            return {"success": False, "message": "ID required"}, 400
        try:
            agent = agents_collection.find_one(
                {"_id": ObjectId(agent_id), "user": decoded_token["sub"]}
            )
            if not agent:
                return {"status": "Not found"}, 404
            data = {
                "id": str(agent["_id"]),
                "name": agent["name"],
                "description": agent.get("description", ""),
                "image": (
                    generate_image_url(agent["image"]) if agent.get("image") else ""
                ),
                "source": (
                    str(source_doc["_id"])
                    if isinstance(agent.get("source"), DBRef)
                    and (source_doc := db.dereference(agent.get("source")))
                    else ""
                ),
                "sources": [
                    (
                        str(db.dereference(source_ref)["_id"])
                        if isinstance(source_ref, DBRef) and db.dereference(source_ref)
                        else source_ref
                    )
                    for source_ref in agent.get("sources", [])
                    if (isinstance(source_ref, DBRef) and db.dereference(source_ref))
                    or source_ref == "default"
                ],
                "chunks": agent.get("chunks", "2"),
                "retriever": agent.get("retriever", ""),
                "prompt_id": agent.get("prompt_id", ""),
                "tools": agent.get("tools", []),
                "tool_details": resolve_tool_details(agent.get("tools", [])),
                "agent_type": agent.get("agent_type", ""),
                "status": agent.get("status", ""),
                "json_schema": agent.get("json_schema"),
                "limited_token_mode": agent.get("limited_token_mode", False),
                "token_limit": agent.get(
                    "token_limit", settings.DEFAULT_AGENT_LIMITS["token_limit"]
                ),
                "limited_request_mode": agent.get("limited_request_mode", False),
                "request_limit": agent.get(
                    "request_limit", settings.DEFAULT_AGENT_LIMITS["request_limit"]
                ),
                "created_at": agent.get("createdAt", ""),
                "updated_at": agent.get("updatedAt", ""),
                "last_used_at": agent.get("lastUsedAt", ""),
                "key": (
                    f"{agent['key'][:4]}...{agent['key'][-4:]}"
                    if "key" in agent
                    else ""
                ),
                "pinned": agent.get("pinned", False),
                "shared": agent.get("shared_publicly", False),
                "shared_metadata": agent.get("shared_metadata", {}),
                "shared_token": agent.get("shared_token", ""),
                "models": agent.get("models", []),
                "default_model_id": agent.get("default_model_id", ""),
                "folder_id": agent.get("folder_id"),
                "workflow": agent.get("workflow"),
            }
            return make_response(jsonify(data), 200)
        except Exception as e:
            current_app.logger.error(f"Agent fetch error: {e}", exc_info=True)
            return {"success": False}, 400


@agents_ns.route("/get_agents")
class GetAgents(Resource):
    @api.doc(description="Retrieve agents for the user")
    def get(self):
        if not (decoded_token := request.decoded_token):
            return {"success": False}, 401
        user = decoded_token.get("sub")
        try:
            user_doc = ensure_user_doc(user)
            pinned_ids = set(user_doc.get("agent_preferences", {}).get("pinned", []))

            agents = agents_collection.find({"user": user})
            list_agents = [
                {
                    "id": str(agent["_id"]),
                    "name": agent["name"],
                    "description": agent.get("description", ""),
                    "image": (
                        generate_image_url(agent["image"]) if agent.get("image") else ""
                    ),
                    "source": (
                        str(source_doc["_id"])
                        if isinstance(agent.get("source"), DBRef)
                        and (source_doc := db.dereference(agent.get("source")))
                        else (
                            agent.get("source", "")
                            if agent.get("source") == "default"
                            else ""
                        )
                    ),
                    "sources": [
                        (
                            source_ref
                            if source_ref == "default"
                            else str(db.dereference(source_ref)["_id"])
                        )
                        for source_ref in agent.get("sources", [])
                        if source_ref == "default"
                        or (
                            isinstance(source_ref, DBRef) and db.dereference(source_ref)
                        )
                    ],
                    "chunks": agent.get("chunks", "2"),
                    "retriever": agent.get("retriever", ""),
                    "prompt_id": agent.get("prompt_id", ""),
                    "tools": agent.get("tools", []),
                    "tool_details": resolve_tool_details(agent.get("tools", [])),
                    "agent_type": agent.get("agent_type", ""),
                    "status": agent.get("status", ""),
                    "json_schema": agent.get("json_schema"),
                    "limited_token_mode": agent.get("limited_token_mode", False),
                    "token_limit": agent.get(
                        "token_limit", settings.DEFAULT_AGENT_LIMITS["token_limit"]
                    ),
                    "limited_request_mode": agent.get("limited_request_mode", False),
                    "request_limit": agent.get(
                        "request_limit", settings.DEFAULT_AGENT_LIMITS["request_limit"]
                    ),
                    "created_at": agent.get("createdAt", ""),
                    "updated_at": agent.get("updatedAt", ""),
                    "last_used_at": agent.get("lastUsedAt", ""),
                    "key": (
                        f"{agent['key'][:4]}...{agent['key'][-4:]}"
                        if "key" in agent
                        else ""
                    ),
                    "pinned": str(agent["_id"]) in pinned_ids,
                    "shared": agent.get("shared_publicly", False),
                    "shared_metadata": agent.get("shared_metadata", {}),
                    "shared_token": agent.get("shared_token", ""),
                    "models": agent.get("models", []),
                    "default_model_id": agent.get("default_model_id", ""),
                    "folder_id": agent.get("folder_id"),
                    "workflow": agent.get("workflow"),
                }
                for agent in agents
                if "source" in agent
                or "retriever" in agent
                or agent.get("agent_type") == "workflow"
            ]
        except Exception as err:
            current_app.logger.error(f"Error retrieving agents: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(list_agents), 200)


@agents_ns.route("/create_agent")
class CreateAgent(Resource):
    create_agent_model = api.model(
        "CreateAgentModel",
        {
            "name": fields.String(required=True, description="Name of the agent"),
            "description": fields.String(
                required=True, description="Description of the agent"
            ),
            "image": fields.Raw(
                required=False, description="Image file upload", type="file"
            ),
            "source": fields.String(
                required=False, description="Source ID (legacy single source)"
            ),
            "sources": fields.List(
                fields.String,
                required=False,
                description="List of source identifiers for multiple sources",
            ),
            "chunks": fields.Integer(required=False, description="Chunks count"),
            "retriever": fields.String(required=False, description="Retriever ID"),
            "prompt_id": fields.String(required=False, description="Prompt ID"),
            "tools": fields.List(
                fields.String, required=False, description="List of tool identifiers"
            ),
            "agent_type": fields.String(
                required=False,
                description="Type of the agent (classic, react, workflow). Defaults to 'classic' for backwards compatibility.",
            ),
            "status": fields.String(
                required=True, description="Status of the agent (draft or published)"
            ),
            "workflow": fields.String(
                required=False, description="Workflow ID for workflow-type agents"
            ),
            "json_schema": fields.Raw(
                required=False,
                description="JSON schema for enforcing structured output format",
            ),
            "limited_token_mode": fields.Boolean(
                required=False, description="Whether the agent is in limited token mode"
            ),
            "token_limit": fields.Integer(
                required=False, description="Token limit for the agent in limited mode"
            ),
            "limited_request_mode": fields.Boolean(
                required=False,
                description="Whether the agent is in limited request mode",
            ),
            "request_limit": fields.Integer(
                required=False,
                description="Request limit for the agent in limited mode",
            ),
            "models": fields.List(
                fields.String,
                required=False,
                description="List of available model IDs for this agent",
            ),
            "default_model_id": fields.String(
                required=False, description="Default model ID for this agent"
            ),
            "folder_id": fields.String(
                required=False, description="Folder ID to organize the agent"
            ),
        },
    )

    @api.expect(create_agent_model)
    @api.doc(description="Create a new agent")
    def post(self):
        if not (decoded_token := request.decoded_token):
            return {"success": False}, 401
        user = decoded_token.get("sub")
        if request.content_type == "application/json":
            data = request.get_json()
        else:
            data = request.form.to_dict()
            if "tools" in data:
                try:
                    data["tools"] = json.loads(data["tools"])
                except json.JSONDecodeError:
                    data["tools"] = []
            if "sources" in data:
                try:
                    data["sources"] = json.loads(data["sources"])
                except json.JSONDecodeError:
                    data["sources"] = []
            if "json_schema" in data:
                try:
                    data["json_schema"] = json.loads(data["json_schema"])
                except json.JSONDecodeError:
                    data["json_schema"] = None
            if "models" in data:
                try:
                    data["models"] = json.loads(data["models"])
                except json.JSONDecodeError:
                    data["models"] = []
        print(f"Received data: {data}")

        # Validate JSON schema if provided

        if data.get("json_schema"):
            try:
                # Basic validation - ensure it's a valid JSON structure

                json_schema = data.get("json_schema")
                if not isinstance(json_schema, dict):
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "JSON schema must be a valid JSON object",
                            }
                        ),
                        400,
                    )
                # Validate that it has either a 'schema' property or is itself a schema

                if "schema" not in json_schema and "type" not in json_schema:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "JSON schema must contain either a 'schema' property or be a valid JSON schema with 'type' property",
                            }
                        ),
                        400,
                    )
            except Exception as e:
                current_app.logger.error(f"Invalid JSON schema: {e}")
                return make_response(
                    jsonify(
                        {"success": False, "message": "Invalid JSON schema format"}
                    ),
                    400,
                )
        if data.get("status") not in ["draft", "published"]:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Status must be either 'draft' or 'published'",
                    }
                ),
                400,
            )
        agent_type = data.get("agent_type", "")
        # Default to classic schema for empty or unknown agent types

        if not agent_type or agent_type not in AGENT_TYPE_SCHEMAS:
            schema = AGENT_TYPE_SCHEMAS["classic"]
            # Set agent_type to classic if it was empty

            if not agent_type:
                agent_type = "classic"
        else:
            schema = AGENT_TYPE_SCHEMAS[agent_type]
        is_published = data.get("status") == "published"
        if agent_type == "workflow":
            workflow_id, workflow_error = validate_workflow_access(
                data.get("workflow"), user, required=is_published
            )
            if workflow_error:
                return workflow_error
            data["workflow"] = workflow_id
        if data.get("status") == "published":
            required_fields = schema["required_published"]
            validate_fields = schema["validate_published"]

            if (
                schema.get("require_source")
                and not data.get("source")
                and not data.get("sources")
            ):
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "message": "Either 'source' or 'sources' field is required for published agents",
                        }
                    ),
                    400,
                )
        else:
            required_fields = schema["required_draft"]
            validate_fields = schema["validate_draft"]
        missing_fields = check_required_fields(data, required_fields)
        invalid_fields = validate_required_fields(data, validate_fields)
        if missing_fields:
            return missing_fields
        if invalid_fields:
            return invalid_fields
        image_url, error = handle_image_upload(request, "", user, storage)
        if error:
            return make_response(
                jsonify({"success": False, "message": "Image upload failed"}), 400
            )
        folder_id = data.get("folder_id")
        if folder_id:
            if not ObjectId.is_valid(folder_id):
                return make_response(
                    jsonify({"success": False, "message": "Invalid folder ID format"}),
                    400,
                )
            folder = agent_folders_collection.find_one(
                {"_id": ObjectId(folder_id), "user": user}
            )
            if not folder:
                return make_response(
                    jsonify({"success": False, "message": "Folder not found"}), 404
                )
        try:
            key = str(uuid.uuid4()) if data.get("status") == "published" else ""

            sources_list = []
            source_field = ""
            if data.get("sources") and len(data.get("sources", [])) > 0:
                for source_id in data.get("sources", []):
                    if source_id == "default":
                        sources_list.append("default")
                    elif ObjectId.is_valid(source_id):
                        sources_list.append(DBRef("sources", ObjectId(source_id)))
            else:
                source_value = data.get("source", "")
                if source_value == "default":
                    source_field = "default"
                elif ObjectId.is_valid(source_value):
                    source_field = DBRef("sources", ObjectId(source_value))
            new_agent = build_agent_document(
                data, user, key, agent_type, image_url, source_field, sources_list
            )

            if agent_type != "workflow":
                if new_agent.get("chunks") == "":
                    new_agent["chunks"] = "2"
                if (
                    new_agent.get("source") == ""
                    and new_agent.get("retriever") == ""
                    and not new_agent.get("sources")
                ):
                    new_agent["retriever"] = "classic"
            resp = agents_collection.insert_one(new_agent)
            new_id = str(resp.inserted_id)
        except Exception as err:
            current_app.logger.error(f"Error creating agent: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"id": new_id, "key": key}), 201)


@agents_ns.route("/update_agent/<string:agent_id>")
class UpdateAgent(Resource):
    update_agent_model = api.model(
        "UpdateAgentModel",
        {
            "name": fields.String(required=True, description="New name of the agent"),
            "description": fields.String(
                required=True, description="New description of the agent"
            ),
            "image": fields.String(
                required=False, description="New image URL or identifier"
            ),
            "source": fields.String(
                required=False, description="Source ID (legacy single source)"
            ),
            "sources": fields.List(
                fields.String,
                required=False,
                description="List of source identifiers for multiple sources",
            ),
            "chunks": fields.Integer(required=False, description="Chunks count"),
            "retriever": fields.String(required=False, description="Retriever ID"),
            "prompt_id": fields.String(required=False, description="Prompt ID"),
            "tools": fields.List(
                fields.String, required=False, description="List of tool identifiers"
            ),
            "agent_type": fields.String(
                required=False,
                description="Type of the agent (classic, react, workflow). Defaults to 'classic' for backwards compatibility.",
            ),
            "status": fields.String(
                required=True, description="Status of the agent (draft or published)"
            ),
            "workflow": fields.String(
                required=False, description="Workflow ID for workflow-type agents"
            ),
            "json_schema": fields.Raw(
                required=False,
                description="JSON schema for enforcing structured output format",
            ),
            "limited_token_mode": fields.Boolean(
                required=False, description="Whether the agent is in limited token mode"
            ),
            "token_limit": fields.Integer(
                required=False, description="Token limit for the agent in limited mode"
            ),
            "limited_request_mode": fields.Boolean(
                require=False,
                description="Whether the agent is in limited request mode",
            ),
            "request_limit": fields.Integer(
                required=False,
                description="Request limit for the agent in limited mode",
            ),
            "models": fields.List(
                fields.String,
                required=False,
                description="List of available model IDs for this agent",
            ),
            "default_model_id": fields.String(
                required=False, description="Default model ID for this agent"
            ),
            "folder_id": fields.String(
                required=False, description="Folder ID to organize the agent"
            ),
        },
    )

    @api.expect(update_agent_model)
    @api.doc(description="Update an existing agent")
    def put(self, agent_id):
        if not (decoded_token := request.decoded_token):
            return make_response(
                jsonify({"success": False, "message": "Unauthorized"}), 401
            )
        user = decoded_token.get("sub")

        if not ObjectId.is_valid(agent_id):
            return make_response(
                jsonify({"success": False, "message": "Invalid agent ID format"}), 400
            )
        oid = ObjectId(agent_id)

        try:
            if request.content_type and "application/json" in request.content_type:
                data = request.get_json()
            else:
                data = request.form.to_dict()
                json_fields = ["tools", "sources", "json_schema", "models"]
                for field in json_fields:
                    if field in data and data[field]:
                        try:
                            data[field] = json.loads(data[field])
                        except json.JSONDecodeError:
                            return make_response(
                                jsonify(
                                    {
                                        "success": False,
                                        "message": f"Invalid JSON format for field: {field}",
                                    }
                                ),
                                400,
                            )
        except Exception as err:
            current_app.logger.error(
                f"Error parsing request data: {err}", exc_info=True
            )
            return make_response(
                jsonify({"success": False, "message": "Invalid request data"}), 400
            )
        try:
            existing_agent = agents_collection.find_one({"_id": oid, "user": user})
        except Exception as err:
            current_app.logger.error(
                f"Error finding agent {agent_id}: {err}", exc_info=True
            )
            return make_response(
                jsonify({"success": False, "message": "Database error finding agent"}),
                500,
            )
        if not existing_agent:
            return make_response(
                jsonify(
                    {"success": False, "message": "Agent not found or not authorized"}
                ),
                404,
            )
        image_url, error = handle_image_upload(
            request, existing_agent.get("image", ""), user, storage
        )
        if error:
            current_app.logger.error(
                f"Image upload error for agent {agent_id}: {error}"
            )
            return make_response(
                jsonify({"success": False, "message": f"Image upload failed: {error}"}),
                400,
            )
        update_fields = {}
        allowed_fields = [
            "name",
            "description",
            "image",
            "source",
            "sources",
            "chunks",
            "retriever",
            "prompt_id",
            "tools",
            "agent_type",
            "status",
            "json_schema",
            "limited_token_mode",
            "token_limit",
            "limited_request_mode",
            "request_limit",
            "models",
            "default_model_id",
            "folder_id",
            "workflow",
        ]

        for field in allowed_fields:
            if field not in data:
                continue
            if field == "status":
                new_status = data.get("status")
                if new_status not in ["draft", "published"]:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "Invalid status value. Must be 'draft' or 'published'",
                            }
                        ),
                        400,
                    )
                update_fields[field] = new_status
            elif field == "source":
                source_id = data.get("source")
                if source_id == "default":
                    update_fields[field] = "default"
                elif source_id and ObjectId.is_valid(source_id):
                    update_fields[field] = DBRef("sources", ObjectId(source_id))
                elif source_id:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": f"Invalid source ID format: {source_id}",
                            }
                        ),
                        400,
                    )
                else:
                    update_fields[field] = ""
            elif field == "sources":
                sources_list = data.get("sources", [])
                if sources_list and isinstance(sources_list, list):
                    valid_sources = []
                    for source_id in sources_list:
                        if source_id == "default":
                            valid_sources.append("default")
                        elif ObjectId.is_valid(source_id):
                            valid_sources.append(DBRef("sources", ObjectId(source_id)))
                        else:
                            return make_response(
                                jsonify(
                                    {
                                        "success": False,
                                        "message": f"Invalid source ID in list: {source_id}",
                                    }
                                ),
                                400,
                            )
                    update_fields[field] = valid_sources
                else:
                    update_fields[field] = []
            elif field == "chunks":
                chunks_value = data.get("chunks")
                if chunks_value == "" or chunks_value is None:
                    update_fields[field] = "2"
                else:
                    try:
                        chunks_int = int(chunks_value)
                        if chunks_int < 0:
                            return make_response(
                                jsonify(
                                    {
                                        "success": False,
                                        "message": "Chunks value must be a non-negative integer",
                                    }
                                ),
                                400,
                            )
                        update_fields[field] = str(chunks_int)
                    except (ValueError, TypeError):
                        return make_response(
                            jsonify(
                                {
                                    "success": False,
                                    "message": f"Invalid chunks value: {chunks_value}",
                                }
                            ),
                            400,
                        )
            elif field == "tools":
                tools_list = data.get("tools", [])
                if isinstance(tools_list, list):
                    update_fields[field] = tools_list
                else:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "Tools must be a list",
                            }
                        ),
                        400,
                    )
            elif field == "json_schema":
                json_schema = data.get("json_schema")
                if json_schema is not None:
                    if not isinstance(json_schema, dict):
                        return make_response(
                            jsonify(
                                {
                                    "success": False,
                                    "message": "JSON schema must be a valid object",
                                }
                            ),
                            400,
                        )
                    update_fields[field] = json_schema
                else:
                    update_fields[field] = None
            elif field == "limited_token_mode":
                raw_value = data.get("limited_token_mode", False)
                bool_value = (
                    raw_value == "True"
                    if isinstance(raw_value, str)
                    else bool(raw_value)
                )
                update_fields[field] = bool_value

                if bool_value and data.get("token_limit") is None:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "Token limit must be provided when limited token mode is enabled",
                            }
                        ),
                        400,
                    )
            elif field == "limited_request_mode":
                raw_value = data.get("limited_request_mode", False)
                bool_value = (
                    raw_value == "True"
                    if isinstance(raw_value, str)
                    else bool(raw_value)
                )
                update_fields[field] = bool_value

                if bool_value and data.get("request_limit") is None:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "Request limit must be provided when limited request mode is enabled",
                            }
                        ),
                        400,
                    )
            elif field == "token_limit":
                token_limit = data.get("token_limit")
                update_fields[field] = int(token_limit) if token_limit else 0

                # Validate consistency with mode

                if update_fields[field] > 0 and not data.get("limited_token_mode"):
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "Token limit cannot be set when limited token mode is disabled",
                            }
                        ),
                        400,
                    )
            elif field == "request_limit":
                request_limit = data.get("request_limit")
                update_fields[field] = int(request_limit) if request_limit else 0

                if update_fields[field] > 0 and not data.get("limited_request_mode"):
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "Request limit cannot be set when limited request mode is disabled",
                            }
                        ),
                        400,
                    )
            elif field == "folder_id":
                folder_id = data.get("folder_id")
                if folder_id:
                    if not ObjectId.is_valid(folder_id):
                        return make_response(
                            jsonify(
                                {
                                    "success": False,
                                    "message": "Invalid folder ID format",
                                }
                            ),
                            400,
                        )
                    folder = agent_folders_collection.find_one(
                        {"_id": ObjectId(folder_id), "user": user}
                    )
                    if not folder:
                        return make_response(
                            jsonify({"success": False, "message": "Folder not found"}),
                            404,
                        )
                    update_fields[field] = folder_id
                else:
                    update_fields[field] = None
            elif field == "workflow":
                workflow_required = (
                    data.get("status", existing_agent.get("status")) == "published"
                    and data.get("agent_type", existing_agent.get("agent_type"))
                    == "workflow"
                )
                workflow_id, workflow_error = validate_workflow_access(
                    data.get("workflow"), user, required=workflow_required
                )
                if workflow_error:
                    return workflow_error
                update_fields[field] = workflow_id
            else:
                value = data[field]
                if field in ["name", "description", "prompt_id", "agent_type"]:
                    if not value or not str(value).strip():
                        return make_response(
                            jsonify(
                                {
                                    "success": False,
                                    "message": f"Field '{field}' cannot be empty",
                                }
                            ),
                            400,
                        )
                update_fields[field] = value
        if image_url:
            update_fields["image"] = image_url
        if not update_fields:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "No valid update data provided",
                    }
                ),
                400,
            )
        newly_generated_key = None
        final_status = update_fields.get("status", existing_agent.get("status"))
        agent_type = update_fields.get("agent_type", existing_agent.get("agent_type"))

        if final_status == "published":
            if agent_type == "workflow":
                required_published_fields = {
                    "name": "Agent name",
                }
                missing_published_fields = []
                for req_field, field_label in required_published_fields.items():
                    final_value = update_fields.get(
                        req_field, existing_agent.get(req_field)
                    )
                    if not final_value:
                        missing_published_fields.append(field_label)

                workflow_id = update_fields.get("workflow", existing_agent.get("workflow"))
                if not workflow_id:
                    missing_published_fields.append("Workflow")
                elif not ObjectId.is_valid(workflow_id):
                    missing_published_fields.append("Valid workflow")
                else:
                    workflow = workflows_collection.find_one(
                        {"_id": ObjectId(workflow_id), "user": user}
                    )
                    if not workflow:
                        missing_published_fields.append("Workflow access")

                if missing_published_fields:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": f"Cannot publish workflow agent. Missing required fields: {', '.join(missing_published_fields)}",
                            }
                        ),
                        400,
                    )
            else:
                required_published_fields = {
                    "name": "Agent name",
                    "description": "Agent description",
                    "chunks": "Chunks count",
                    "prompt_id": "Prompt",
                    "agent_type": "Agent type",
                }

                missing_published_fields = []
                for req_field, field_label in required_published_fields.items():
                    final_value = update_fields.get(
                        req_field, existing_agent.get(req_field)
                    )
                    if not final_value:
                        missing_published_fields.append(field_label)
                source_val = update_fields.get("source", existing_agent.get("source"))
                sources_val = update_fields.get(
                    "sources", existing_agent.get("sources", [])
                )

                has_valid_source = (
                    isinstance(source_val, DBRef)
                    or source_val == "default"
                    or (isinstance(sources_val, list) and len(sources_val) > 0)
                )

                if not has_valid_source:
                    missing_published_fields.append("Source")
                if missing_published_fields:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": f"Cannot publish agent. Missing or invalid required fields: {', '.join(missing_published_fields)}",
                            }
                        ),
                        400,
                    )
            if not existing_agent.get("key"):
                newly_generated_key = str(uuid.uuid4())
                update_fields["key"] = newly_generated_key
        update_fields["updatedAt"] = datetime.datetime.now(datetime.timezone.utc)

        try:
            result = agents_collection.update_one(
                {"_id": oid, "user": user}, {"$set": update_fields}
            )

            if result.matched_count == 0:
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "message": "Agent not found or update failed",
                        }
                    ),
                    404,
                )
            if result.modified_count == 0 and result.matched_count == 1:
                return make_response(
                    jsonify(
                        {
                            "success": True,
                            "message": "No changes detected",
                            "id": agent_id,
                        }
                    ),
                    200,
                )
        except Exception as err:
            current_app.logger.error(
                f"Error updating agent {agent_id}: {err}", exc_info=True
            )
            return make_response(
                jsonify({"success": False, "message": "Database error during update"}),
                500,
            )
        response_data = {
            "success": True,
            "id": agent_id,
            "message": "Agent updated successfully",
        }
        if newly_generated_key:
            response_data["key"] = newly_generated_key
        return make_response(jsonify(response_data), 200)


@agents_ns.route("/delete_agent")
class DeleteAgent(Resource):
    @api.doc(params={"id": "ID of the agent"}, description="Delete an agent by ID")
    def delete(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        agent_id = request.args.get("id")
        if not agent_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )
        try:
            deleted_agent = agents_collection.find_one_and_delete(
                {"_id": ObjectId(agent_id), "user": user}
            )
            if not deleted_agent:
                return make_response(
                    jsonify({"success": False, "message": "Agent not found"}), 404
                )
            deleted_id = str(deleted_agent["_id"])

            if deleted_agent.get("agent_type") == "workflow" and deleted_agent.get(
                "workflow"
            ):
                workflow_id = normalize_workflow_reference(deleted_agent.get("workflow"))
                if workflow_id and ObjectId.is_valid(workflow_id):
                    workflow_oid = ObjectId(workflow_id)
                    owned_workflow = workflows_collection.find_one(
                        {"_id": workflow_oid, "user": user}, {"_id": 1}
                    )
                    if owned_workflow:
                        workflow_nodes_collection.delete_many({"workflow_id": workflow_id})
                        workflow_edges_collection.delete_many({"workflow_id": workflow_id})
                        workflows_collection.delete_one({"_id": workflow_oid, "user": user})
                    else:
                        current_app.logger.warning(
                            f"Skipping workflow cleanup for non-owned workflow {workflow_id}"
                        )
                elif workflow_id:
                    current_app.logger.warning(
                        f"Skipping workflow cleanup for invalid workflow id {workflow_id}"
                    )

        except Exception as err:
            current_app.logger.error(f"Error deleting agent: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"id": deleted_id}), 200)


@agents_ns.route("/pinned_agents")
class PinnedAgents(Resource):
    @api.doc(description="Get pinned agents for the user")
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user_id = decoded_token.get("sub")

        try:
            user_doc = ensure_user_doc(user_id)
            pinned_ids = user_doc.get("agent_preferences", {}).get("pinned", [])

            if not pinned_ids:
                return make_response(jsonify([]), 200)
            pinned_object_ids = [ObjectId(agent_id) for agent_id in pinned_ids]

            pinned_agents_cursor = agents_collection.find(
                {"_id": {"$in": pinned_object_ids}}
            )
            pinned_agents = list(pinned_agents_cursor)
            existing_ids = {str(agent["_id"]) for agent in pinned_agents}

            # Clean up any stale pinned IDs

            stale_ids = [
                agent_id for agent_id in pinned_ids if agent_id not in existing_ids
            ]
            if stale_ids:
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$pullAll": {"agent_preferences.pinned": stale_ids}},
                )
            list_pinned_agents = [
                {
                    "id": str(agent["_id"]),
                    "name": agent.get("name", ""),
                    "description": agent.get("description", ""),
                    "image": (
                        generate_image_url(agent["image"]) if agent.get("image") else ""
                    ),
                    "source": (
                        str(db.dereference(agent["source"])["_id"])
                        if "source" in agent
                        and agent["source"]
                        and isinstance(agent["source"], DBRef)
                        and db.dereference(agent["source"]) is not None
                        else ""
                    ),
                    "chunks": agent.get("chunks", ""),
                    "retriever": agent.get("retriever", ""),
                    "prompt_id": agent.get("prompt_id", ""),
                    "tools": agent.get("tools", []),
                    "tool_details": resolve_tool_details(agent.get("tools", [])),
                    "agent_type": agent.get("agent_type", ""),
                    "status": agent.get("status", ""),
                    "created_at": agent.get("createdAt", ""),
                    "updated_at": agent.get("updatedAt", ""),
                    "last_used_at": agent.get("lastUsedAt", ""),
                    "key": (
                        f"{agent['key'][:4]}...{agent['key'][-4:]}"
                        if "key" in agent
                        else ""
                    ),
                    "pinned": True,
                }
                for agent in pinned_agents
                if "source" in agent or "retriever" in agent
            ]
        except Exception as err:
            current_app.logger.error(f"Error retrieving pinned agents: {err}")
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(list_pinned_agents), 200)


@agents_ns.route("/template_agents")
class GetTemplateAgents(Resource):
    @api.doc(description="Get template/premade agents")
    def get(self):
        try:
            template_agents = agents_collection.find({"user": "system"})
            template_agents = [
                {
                    "id": str(agent["_id"]),
                    "name": agent["name"],
                    "description": agent["description"],
                    "image": agent.get("image", ""),
                }
                for agent in template_agents
            ]
            return make_response(jsonify(template_agents), 200)
        except Exception as e:
            current_app.logger.error(f"Template agents fetch error: {e}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)


@agents_ns.route("/adopt_agent")
class AdoptAgent(Resource):
    @api.doc(params={"id": "Agent ID"}, description="Adopt an agent by ID")
    def post(self):
        if not (decoded_token := request.decoded_token):
            return make_response(jsonify({"success": False}), 401)
        if not (agent_id := request.args.get("id")):
            return make_response(
                jsonify({"success": False, "message": "ID required"}), 400
            )
        try:
            agent = agents_collection.find_one(
                {"_id": ObjectId(agent_id), "user": "system"}
            )
            if not agent:
                return make_response(jsonify({"status": "Not found"}), 404)
            new_agent = agent.copy()
            new_agent.pop("_id", None)
            new_agent["user"] = decoded_token["sub"]
            new_agent["status"] = "published"
            new_agent["lastUsedAt"] = datetime.datetime.now(datetime.timezone.utc)
            new_agent["key"] = str(uuid.uuid4())
            insert_result = agents_collection.insert_one(new_agent)

            response_agent = new_agent.copy()
            response_agent.pop("_id", None)
            response_agent["id"] = str(insert_result.inserted_id)
            response_agent["tool_details"] = resolve_tool_details(
                response_agent.get("tools", [])
            )
            if isinstance(response_agent.get("source"), DBRef):
                response_agent["source"] = str(response_agent["source"].id)
            return make_response(
                jsonify({"success": True, "agent": response_agent}), 200
            )
        except Exception as e:
            current_app.logger.error(f"Agent adopt error: {e}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)


@agents_ns.route("/pin_agent")
class PinAgent(Resource):
    @api.doc(params={"id": "ID of the agent"}, description="Pin or unpin an agent")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user_id = decoded_token.get("sub")
        agent_id = request.args.get("id")

        if not agent_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )
        try:
            agent = agents_collection.find_one({"_id": ObjectId(agent_id)})
            if not agent:
                return make_response(
                    jsonify({"success": False, "message": "Agent not found"}), 404
                )
            user_doc = ensure_user_doc(user_id)
            pinned_list = user_doc.get("agent_preferences", {}).get("pinned", [])

            if agent_id in pinned_list:
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$pull": {"agent_preferences.pinned": agent_id}},
                )
                action = "unpinned"
            else:
                users_collection.update_one(
                    {"user_id": user_id},
                    {"$addToSet": {"agent_preferences.pinned": agent_id}},
                )
                action = "pinned"
        except Exception as err:
            current_app.logger.error(f"Error pinning/unpinning agent: {err}")
            return make_response(
                jsonify({"success": False, "message": "Server error"}), 500
            )
        return make_response(jsonify({"success": True, "action": action}), 200)


@agents_ns.route("/remove_shared_agent")
class RemoveSharedAgent(Resource):
    @api.doc(
        params={"id": "ID of the shared agent"},
        description="Remove a shared agent from the current user's shared list",
    )
    def delete(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user_id = decoded_token.get("sub")
        agent_id = request.args.get("id")

        if not agent_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )
        try:
            agent = agents_collection.find_one(
                {"_id": ObjectId(agent_id), "shared_publicly": True}
            )
            if not agent:
                return make_response(
                    jsonify({"success": False, "message": "Shared agent not found"}),
                    404,
                )
            ensure_user_doc(user_id)
            users_collection.update_one(
                {"user_id": user_id},
                {
                    "$pull": {
                        "agent_preferences.shared_with_me": agent_id,
                        "agent_preferences.pinned": agent_id,
                    }
                },
            )

            return make_response(jsonify({"success": True, "action": "removed"}), 200)
        except Exception as err:
            current_app.logger.error(f"Error removing shared agent: {err}")
            return make_response(
                jsonify({"success": False, "message": "Server error"}), 500
            )
