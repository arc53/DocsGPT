"""Agent management routes."""

import datetime
import json
import uuid

from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource

from application.api import api
from application.api.user.base import (
    handle_image_upload,
    resolve_tool_details,
    storage,
)
from application.core.json_schema_utils import (
    JsonSchemaValidationError,
    normalize_json_schema_payload,
)
from application.core.settings import settings
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.agent_folders import AgentFoldersRepository
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.users import UsersRepository
from application.storage.db.repositories.workflow_edges import WorkflowEdgesRepository
from application.storage.db.repositories.workflow_nodes import WorkflowNodesRepository
from application.storage.db.repositories.workflows import WorkflowsRepository
from application.storage.db.session import db_readonly, db_session
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
            "name",
            "description",
            "agent_type",
            "status",
            "key",
            "image",
            "source_id",
            "extra_source_ids",
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
            "allow_system_prompt_override",
        ],
    },
    "workflow": {
        "required_published": ["name", "workflow"],
        "required_draft": ["name"],
        "validate_published": ["name", "workflow"],
        "validate_draft": [],
        "fields": [
            "name",
            "description",
            "agent_type",
            "status",
            "key",
            "workflow_id",
            "folder_id",
            "limited_token_mode",
            "token_limit",
            "limited_request_mode",
            "request_limit",
            "allow_system_prompt_override",
        ],
    },
}

AGENT_TYPE_SCHEMAS["react"] = AGENT_TYPE_SCHEMAS["classic"]
AGENT_TYPE_SCHEMAS["agentic"] = AGENT_TYPE_SCHEMAS["classic"]
AGENT_TYPE_SCHEMAS["research"] = AGENT_TYPE_SCHEMAS["classic"]
AGENT_TYPE_SCHEMAS["openai"] = AGENT_TYPE_SCHEMAS["classic"]


def normalize_workflow_reference(workflow_value):
    """Normalize workflow references from form/json payloads into a string id."""
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


def _resolve_workflow_for_user(conn, workflow_value, user):
    """Resolve and ownership-check a workflow value, returning its PG UUID."""
    workflow_id = normalize_workflow_reference(workflow_value)
    if not workflow_id:
        return None, None
    repo = WorkflowsRepository(conn)
    if looks_like_uuid(workflow_id):
        workflow = repo.get(workflow_id, user)
    else:
        workflow = repo.get_by_legacy_id(workflow_id, user)
    if workflow is None:
        return None, make_response(
            jsonify({"success": False, "message": "Workflow not found"}), 404
        )
    return str(workflow["id"]), None


def _resolve_folder_id(conn, folder_id, user):
    """Resolve a folder id (UUID or legacy) to its PG UUID; error response otherwise."""
    if not folder_id:
        return None, None
    repo = AgentFoldersRepository(conn)
    folder = None
    if looks_like_uuid(folder_id):
        folder = repo.get(folder_id, user)
    if folder is None:
        folder = repo.get_by_legacy_id(folder_id, user)
    if folder is None:
        return None, make_response(
            jsonify({"success": False, "message": "Folder not found"}), 404
        )
    return str(folder["id"]), None


def _format_agent_output(agent: dict, *, pinned: bool = False, include_key_masked: bool = True) -> dict:
    """Shape a PG agent row into the outward API response dict.

    Translates PG snake_case columns to the camelCase/frontend keys that
    the React client expects, preserving ``source``/``sources`` naming on
    the response even though storage uses ``source_id`` /
    ``extra_source_ids``.
    """
    source_id = agent.get("source_id")
    extra_source_ids = agent.get("extra_source_ids") or []
    source_value = str(source_id) if source_id else ""
    sources_list = [str(s) for s in extra_source_ids if s]

    out = {
        "id": str(agent["id"]),
        "name": agent.get("name", ""),
        "description": agent.get("description", "") or "",
        "image": (
            generate_image_url(agent["image"]) if agent.get("image") else ""
        ),
        "source": source_value,
        "sources": sources_list,
        "chunks": agent.get("chunks") if agent.get("chunks") is not None else "2",
        "retriever": agent.get("retriever", "") or "",
        "prompt_id": str(agent["prompt_id"]) if agent.get("prompt_id") else "",
        "tools": agent.get("tools", []) or [],
        "tool_details": resolve_tool_details(agent.get("tools", []) or []),
        "agent_type": agent.get("agent_type", "") or "",
        "status": agent.get("status", "") or "",
        "json_schema": agent.get("json_schema"),
        "limited_token_mode": bool(agent.get("limited_token_mode", False)),
        "token_limit": agent.get("token_limit") or settings.DEFAULT_AGENT_LIMITS["token_limit"],
        "limited_request_mode": bool(agent.get("limited_request_mode", False)),
        "request_limit": agent.get("request_limit") or settings.DEFAULT_AGENT_LIMITS["request_limit"],
        "created_at": agent.get("created_at", ""),
        "updated_at": agent.get("updated_at", ""),
        "last_used_at": agent.get("last_used_at", ""),
        "pinned": pinned,
        "shared": bool(agent.get("shared", False)),
        "shared_metadata": agent.get("shared_metadata", {}) or {},
        "shared_token": agent.get("shared_token", "") or "",
        "models": agent.get("models", []) or [],
        "default_model_id": agent.get("default_model_id", "") or "",
        "folder_id": str(agent["folder_id"]) if agent.get("folder_id") else None,
        "workflow": str(agent["workflow_id"]) if agent.get("workflow_id") else None,
        "allow_system_prompt_override": bool(
            agent.get("allow_system_prompt_override", False)
        ),
    }
    if include_key_masked:
        key_val = agent.get("key") or ""
        out["key"] = (
            f"{key_val[:4]}...{key_val[-4:]}" if key_val else ""
        )
    return out


def _build_create_kwargs(data: dict, *, image_url: str, agent_type: str) -> dict:
    """Translate request data + resolved references into AgentsRepository.create kwargs."""
    kwargs: dict = {}

    schema = AGENT_TYPE_SCHEMAS.get(agent_type, AGENT_TYPE_SCHEMAS["classic"])
    allowed_fields = set(schema["fields"])

    for key in (
        "description", "agent_type", "key", "image", "retriever",
        "default_model_id",
    ):
        if key in allowed_fields and data.get(key) not in (None, ""):
            kwargs[key] = data[key]

    if image_url and "image" in allowed_fields:
        kwargs["image"] = image_url

    if "source_id" in allowed_fields and data.get("source_id"):
        kwargs["source_id"] = data["source_id"]
    if "extra_source_ids" in allowed_fields and data.get("extra_source_ids"):
        kwargs["extra_source_ids"] = data["extra_source_ids"]

    if "prompt_id" in allowed_fields:
        prompt_val = data.get("prompt_id")
        if prompt_val and prompt_val != "default" and looks_like_uuid(prompt_val):
            kwargs["prompt_id"] = prompt_val

    if "folder_id" in allowed_fields and data.get("folder_id"):
        kwargs["folder_id"] = data["folder_id"]

    if "workflow_id" in allowed_fields and data.get("workflow_id"):
        kwargs["workflow_id"] = data["workflow_id"]

    if "chunks" in allowed_fields:
        chunks_val = data.get("chunks")
        if chunks_val not in (None, ""):
            try:
                kwargs["chunks"] = int(chunks_val)
            except (TypeError, ValueError):
                pass

    for key in ("limited_token_mode", "limited_request_mode", "allow_system_prompt_override"):
        if key in allowed_fields and key in data:
            raw = data[key]
            kwargs[key] = raw == "True" if isinstance(raw, str) else bool(raw)

    for key in ("token_limit", "request_limit"):
        if key in allowed_fields and data.get(key) not in (None, ""):
            try:
                kwargs[key] = int(data[key])
            except (TypeError, ValueError):
                pass

    if "tools" in allowed_fields and data.get("tools") is not None:
        kwargs["tools"] = data["tools"]
    if "json_schema" in allowed_fields and data.get("json_schema") is not None:
        kwargs["json_schema"] = data["json_schema"]
    if "models" in allowed_fields and data.get("models") is not None:
        kwargs["models"] = data["models"]

    return kwargs


@agents_ns.route("/get_agent")
class GetAgent(Resource):
    @api.doc(params={"id": "Agent ID"}, description="Get agent by ID")
    def get(self):
        if not (decoded_token := request.decoded_token):
            return {"success": False}, 401
        if not (agent_id := request.args.get("id")):
            return {"success": False, "message": "ID required"}, 400
        try:
            user = decoded_token["sub"]
            with db_readonly() as conn:
                agent = AgentsRepository(conn).get_any(agent_id, user)
            if not agent:
                return {"status": "Not found"}, 404
            data = _format_agent_output(agent)
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
            with db_session() as conn:
                users_repo = UsersRepository(conn)
                user_doc = users_repo.upsert(user)
                pinned_ids = set(
                    user_doc.get("agent_preferences", {}).get("pinned", [])
                    if isinstance(user_doc.get("agent_preferences"), dict)
                    else []
                )
                agents = AgentsRepository(conn).list_for_user(user)
            list_agents = [
                _format_agent_output(
                    agent, pinned=str(agent["id"]) in pinned_ids,
                )
                for agent in agents
                if agent.get("source_id")
                or (agent.get("extra_source_ids") or [])
                or agent.get("retriever")
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
            "allow_system_prompt_override": fields.Boolean(
                required=False,
                description="Allow API callers to override the system prompt via the v1 endpoint",
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

        if "json_schema" in data:
            try:
                data["json_schema"] = normalize_json_schema_payload(
                    data.get("json_schema")
                )
            except JsonSchemaValidationError:
                return make_response(
                    jsonify({"success": False, "message": "Invalid JSON schema"}),
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
        if not agent_type or agent_type not in AGENT_TYPE_SCHEMAS:
            schema = AGENT_TYPE_SCHEMAS["classic"]
            if not agent_type:
                agent_type = "classic"
        else:
            schema = AGENT_TYPE_SCHEMAS[agent_type]
        is_published = data.get("status") == "published"
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

        try:
            key = str(uuid.uuid4()) if is_published else ""
            with db_session() as conn:
                # Resolve folder.
                pg_folder_id = None
                if data.get("folder_id"):
                    pg_folder_id, err = _resolve_folder_id(
                        conn, data["folder_id"], user,
                    )
                    if err:
                        return err

                # Resolve workflow for workflow-type agents.
                pg_workflow_id = None
                if agent_type == "workflow":
                    pg_workflow_id, err = _resolve_workflow_for_user(
                        conn, data.get("workflow"), user,
                    )
                    if err and is_published:
                        return err
                    if pg_workflow_id is None and is_published:
                        return make_response(
                            jsonify({"success": False, "message": "Workflow is required"}),
                            400,
                        )

                # Resolve sources — only UUIDs accepted post-cutover.
                source_id_resolved = None
                extra_source_ids: list[str] = []
                if data.get("sources"):
                    for src in data["sources"]:
                        if src == "default":
                            continue
                        if looks_like_uuid(src):
                            extra_source_ids.append(src)
                else:
                    source_value = data.get("source", "")
                    if source_value and source_value != "default" and looks_like_uuid(source_value):
                        source_id_resolved = source_value

                build_data = dict(data)
                build_data["folder_id"] = pg_folder_id
                build_data["workflow_id"] = pg_workflow_id
                build_data["source_id"] = source_id_resolved
                build_data["extra_source_ids"] = extra_source_ids
                build_data["key"] = key
                build_data["agent_type"] = agent_type

                # For classic agents: default chunks/retriever if nothing else supplied.
                if agent_type != "workflow":
                    if build_data.get("chunks") in (None, ""):
                        build_data["chunks"] = 2
                    if (
                        not source_id_resolved
                        and not extra_source_ids
                        and not build_data.get("retriever")
                    ):
                        build_data["retriever"] = "classic"

                kwargs = _build_create_kwargs(
                    build_data, image_url=image_url, agent_type=agent_type,
                )
                agent_row = AgentsRepository(conn).create(
                    user,
                    data["name"],
                    data["status"],
                    **kwargs,
                )
                new_id = str(agent_row["id"])
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
            "allow_system_prompt_override": fields.Boolean(
                required=False,
                description="Allow API callers to override the system prompt via the v1 endpoint",
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
                if data.get("json_schema") == "":
                    data["json_schema"] = None
        except Exception as err:
            current_app.logger.error(
                f"Error parsing request data: {err}", exc_info=True
            )
            return make_response(
                jsonify({"success": False, "message": "Invalid request data"}), 400
            )

        try:
            with db_session() as conn:
                agents_repo = AgentsRepository(conn)
                existing_agent = agents_repo.get_any(agent_id, user)
                if not existing_agent:
                    return make_response(
                        jsonify(
                            {"success": False, "message": "Agent not found or not authorized"}
                        ),
                        404,
                    )
                pg_agent_id = str(existing_agent["id"])
                image_url, image_error = handle_image_upload(
                    request, existing_agent.get("image", "") or "", user, storage,
                )
                if image_error:
                    return image_error

                update_fields: dict = {}
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
                    "allow_system_prompt_override",
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
                        update_fields["status"] = new_status
                    elif field == "source":
                        source_id = data.get("source")
                        if not source_id or source_id == "default":
                            update_fields["source_id"] = None
                        elif looks_like_uuid(source_id):
                            update_fields["source_id"] = source_id
                        else:
                            return make_response(
                                jsonify(
                                    {
                                        "success": False,
                                        "message": f"Invalid source ID format: {source_id}",
                                    }
                                ),
                                400,
                            )
                    elif field == "sources":
                        sources_list = data.get("sources", []) or []
                        if not isinstance(sources_list, list):
                            update_fields["extra_source_ids"] = []
                            continue
                        valid: list[str] = []
                        for src in sources_list:
                            if src == "default":
                                continue
                            if looks_like_uuid(src):
                                valid.append(src)
                            else:
                                return make_response(
                                    jsonify(
                                        {
                                            "success": False,
                                            "message": f"Invalid source ID in list: {src}",
                                        }
                                    ),
                                    400,
                                )
                        update_fields["extra_source_ids"] = valid
                    elif field == "chunks":
                        chunks_value = data.get("chunks")
                        if chunks_value in ("", None):
                            update_fields["chunks"] = 2
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
                                update_fields["chunks"] = chunks_int
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
                        if not isinstance(tools_list, list):
                            return make_response(
                                jsonify({"success": False, "message": "Tools must be a list"}),
                                400,
                            )
                        update_fields["tools"] = tools_list
                    elif field == "json_schema":
                        json_schema = data.get("json_schema")
                        if json_schema is not None:
                            try:
                                update_fields["json_schema"] = normalize_json_schema_payload(
                                    json_schema
                                )
                            except JsonSchemaValidationError:
                                return make_response(
                                    jsonify({"success": False, "message": "Invalid JSON schema"}),
                                    400,
                                )
                        else:
                            update_fields["json_schema"] = None
                    elif field == "limited_token_mode":
                        raw_value = data.get("limited_token_mode", False)
                        bool_value = (
                            raw_value == "True"
                            if isinstance(raw_value, str)
                            else bool(raw_value)
                        )
                        update_fields["limited_token_mode"] = bool_value
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
                        update_fields["limited_request_mode"] = bool_value
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
                        update_fields["token_limit"] = int(token_limit) if token_limit else 0
                        if update_fields["token_limit"] > 0 and not data.get("limited_token_mode"):
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
                        update_fields["request_limit"] = int(request_limit) if request_limit else 0
                        if update_fields["request_limit"] > 0 and not data.get("limited_request_mode"):
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
                        folder_input = data.get("folder_id")
                        if folder_input:
                            pg_folder_id, folder_err = _resolve_folder_id(
                                conn, folder_input, user,
                            )
                            if folder_err:
                                return folder_err
                            update_fields["folder_id"] = pg_folder_id
                        else:
                            update_fields["folder_id"] = None
                    elif field == "workflow":
                        workflow_required = (
                            data.get("status", existing_agent.get("status")) == "published"
                            and data.get("agent_type", existing_agent.get("agent_type"))
                            == "workflow"
                        )
                        workflow_input = data.get("workflow")
                        normalized = normalize_workflow_reference(workflow_input)
                        if not normalized:
                            if workflow_required:
                                return make_response(
                                    jsonify({"success": False, "message": "Workflow is required"}),
                                    400,
                                )
                            update_fields["workflow_id"] = None
                        else:
                            pg_workflow_id, wf_err = _resolve_workflow_for_user(
                                conn, workflow_input, user,
                            )
                            if wf_err:
                                return wf_err
                            update_fields["workflow_id"] = pg_workflow_id
                    elif field == "prompt_id":
                        value = data["prompt_id"]
                        if not value or value == "default":
                            update_fields["prompt_id"] = None
                        elif looks_like_uuid(value):
                            update_fields["prompt_id"] = value
                        else:
                            return make_response(
                                jsonify(
                                    {"success": False, "message": f"Invalid prompt_id: {value}"}
                                ),
                                400,
                            )
                    elif field == "allow_system_prompt_override":
                        raw_value = data.get("allow_system_prompt_override", False)
                        update_fields["allow_system_prompt_override"] = (
                            raw_value == "True"
                            if isinstance(raw_value, str)
                            else bool(raw_value)
                        )
                    else:
                        value = data[field]
                        if field in ["name", "description", "agent_type"]:
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
                final_agent_type = update_fields.get(
                    "agent_type", existing_agent.get("agent_type")
                )

                if final_status == "published":
                    if final_agent_type == "workflow":
                        missing_published_fields = []
                        if not update_fields.get("name", existing_agent.get("name")):
                            missing_published_fields.append("Agent name")
                        workflow_final = update_fields.get(
                            "workflow_id", existing_agent.get("workflow_id"),
                        )
                        if not workflow_final:
                            missing_published_fields.append("Workflow")
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
                        missing_published_fields = []
                        for req_field, field_label in (
                            ("name", "Agent name"),
                            ("description", "Agent description"),
                            ("chunks", "Chunks count"),
                            ("prompt_id", "Prompt"),
                            ("agent_type", "Agent type"),
                        ):
                            final_value = update_fields.get(
                                req_field, existing_agent.get(req_field)
                            )
                            if not final_value:
                                missing_published_fields.append(field_label)
                        source_final = update_fields.get(
                            "source_id", existing_agent.get("source_id"),
                        )
                        extra_final = update_fields.get(
                            "extra_source_ids", existing_agent.get("extra_source_ids") or [],
                        )
                        if not source_final and not extra_final:
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

                # Apply update.
                updated = agents_repo.update(pg_agent_id, user, update_fields)
                if not updated:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "Agent not found or update failed",
                            }
                        ),
                        404,
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
            "id": pg_agent_id,
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
            with db_session() as conn:
                agents_repo = AgentsRepository(conn)
                agent = agents_repo.get_any(agent_id, user)
                if not agent:
                    return make_response(
                        jsonify({"success": False, "message": "Agent not found"}), 404
                    )
                pg_agent_id = str(agent["id"])
                workflow_id = agent.get("workflow_id")
                # For workflow-type agents, delete the owned workflow in the
                # same transaction. workflow_nodes/workflow_edges cascade
                # via ON DELETE CASCADE so a single workflow delete suffices.
                if agent.get("agent_type") == "workflow" and workflow_id:
                    try:
                        WorkflowNodesRepository(conn).delete_by_workflow(
                            str(workflow_id),
                        )
                        WorkflowEdgesRepository(conn).delete_by_workflow(
                            str(workflow_id),
                        )
                        WorkflowsRepository(conn).delete(str(workflow_id), user)
                    except Exception as wf_err:
                        current_app.logger.warning(
                            f"Workflow cleanup failed for agent {pg_agent_id}: {wf_err}"
                        )
                agents_repo.delete(pg_agent_id, user)
                # Strip pinned/shared entries for this agent from the owner's prefs.
                UsersRepository(conn).remove_agent_from_all(user, pg_agent_id)
        except Exception as err:
            current_app.logger.error(f"Error deleting agent: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"id": pg_agent_id}), 200)


@agents_ns.route("/pinned_agents")
class PinnedAgents(Resource):
    @api.doc(description="Get pinned agents for the user")
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user_id = decoded_token.get("sub")

        try:
            with db_session() as conn:
                users_repo = UsersRepository(conn)
                user_doc = users_repo.upsert(user_id)
                pinned_ids = (
                    user_doc.get("agent_preferences", {}).get("pinned", [])
                    if isinstance(user_doc.get("agent_preferences"), dict)
                    else []
                )
                if not pinned_ids:
                    return make_response(jsonify([]), 200)

                uuid_pinned = [pid for pid in pinned_ids if looks_like_uuid(pid)]
                non_uuid = [pid for pid in pinned_ids if not looks_like_uuid(pid)]

                if uuid_pinned:
                    from sqlalchemy import text as _sql_text

                    result = conn.execute(
                        _sql_text(
                            "SELECT * FROM agents "
                            "WHERE id = ANY(CAST(:ids AS uuid[]))"
                        ),
                        {"ids": uuid_pinned},
                    )
                    pinned_agents = [dict(row._mapping) for row in result.fetchall()]
                else:
                    pinned_agents = []

                existing_ids = {str(a["id"]) for a in pinned_agents}
                stale = [pid for pid in uuid_pinned if pid not in existing_ids]
                stale.extend(non_uuid)
                if stale:
                    users_repo.remove_pinned_bulk(user_id, stale)

            list_pinned_agents = []
            for agent in pinned_agents:
                source_id = agent.get("source_id")
                if not source_id and not agent.get("retriever"):
                    continue
                list_pinned_agents.append(
                    {
                        "id": str(agent["id"]),
                        "name": agent.get("name", ""),
                        "description": agent.get("description", ""),
                        "image": (
                            generate_image_url(agent["image"]) if agent.get("image") else ""
                        ),
                        "source": str(source_id) if source_id else "",
                        "chunks": agent.get("chunks", ""),
                        "retriever": agent.get("retriever", "") or "",
                        "prompt_id": str(agent["prompt_id"]) if agent.get("prompt_id") else "",
                        "tools": agent.get("tools", []) or [],
                        "tool_details": resolve_tool_details(agent.get("tools", []) or []),
                        "agent_type": agent.get("agent_type", "") or "",
                        "status": agent.get("status", "") or "",
                        "created_at": agent.get("created_at", ""),
                        "updated_at": agent.get("updated_at", ""),
                        "last_used_at": agent.get("last_used_at", ""),
                        "key": (
                            f"{agent['key'][:4]}...{agent['key'][-4:]}"
                            if agent.get("key")
                            else ""
                        ),
                        "pinned": True,
                    }
                )
        except Exception as err:
            current_app.logger.error(f"Error retrieving pinned agents: {err}")
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(list_pinned_agents), 200)


@agents_ns.route("/template_agents")
class GetTemplateAgents(Resource):
    @api.doc(description="Get template/premade agents")
    def get(self):
        try:
            from sqlalchemy import text as _sql_text

            with db_readonly() as conn:
                result = conn.execute(
                    _sql_text(
                        "SELECT * FROM agents "
                        "WHERE user_id IN ('system', '__system__') "
                        "ORDER BY name"
                    ),
                )
                template_rows = [dict(row._mapping) for row in result.fetchall()]
            template_agents = [
                {
                    "id": str(agent["id"]),
                    "name": agent.get("name"),
                    "description": agent.get("description") or "",
                    "image": agent.get("image") or "",
                }
                for agent in template_rows
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
            user = decoded_token["sub"]
            from sqlalchemy import text as _sql_text

            with db_session() as conn:
                # Template lookup: user_id must be 'system' or '__system__'.
                if looks_like_uuid(agent_id):
                    template_row = conn.execute(
                        _sql_text(
                            "SELECT * FROM agents "
                            "WHERE id = CAST(:id AS uuid) "
                            "AND user_id IN ('system', '__system__')"
                        ),
                        {"id": agent_id},
                    ).fetchone()
                else:
                    template_row = conn.execute(
                        _sql_text(
                            "SELECT * FROM agents "
                            "WHERE legacy_mongo_id = :id "
                            "AND user_id IN ('system', '__system__')"
                        ),
                        {"id": agent_id},
                    ).fetchone()
                if template_row is None:
                    return make_response(jsonify({"status": "Not found"}), 404)
                template = dict(template_row._mapping)

                now = datetime.datetime.now(datetime.timezone.utc)
                new_key = str(uuid.uuid4())
                create_kwargs: dict = {}
                for col in (
                    "description", "agent_type", "image", "retriever",
                    "default_model_id",
                    "source_id", "prompt_id", "folder_id", "workflow_id",
                    "extra_source_ids",
                ):
                    val = template.get(col)
                    if val not in (None, ""):
                        create_kwargs[col] = val
                for col in ("tools", "json_schema", "models", "shared_metadata"):
                    if template.get(col) is not None:
                        create_kwargs[col] = template[col]
                for col in ("chunks", "token_limit", "request_limit"):
                    if template.get(col) is not None:
                        create_kwargs[col] = template[col]
                for col in (
                    "limited_token_mode", "limited_request_mode",
                    "allow_system_prompt_override",
                ):
                    if template.get(col) is not None:
                        create_kwargs[col] = bool(template[col])

                create_kwargs["key"] = new_key
                create_kwargs["last_used_at"] = now

                new_agent = AgentsRepository(conn).create(
                    user,
                    template.get("name") or "",
                    "published",
                    **create_kwargs,
                )

            response_agent = _format_agent_output(new_agent, include_key_masked=False)
            response_agent["key"] = new_key
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
            with db_session() as conn:
                # Any user can pin any agent they can see — including
                # shared ones. Use the non-user-scoped lookup so pins
                # aren't restricted to owner-only.
                from sqlalchemy import text as _sql_text

                if looks_like_uuid(agent_id):
                    agent_row = conn.execute(
                        _sql_text("SELECT id FROM agents WHERE id = CAST(:id AS uuid)"),
                        {"id": agent_id},
                    ).fetchone()
                else:
                    agent_row = conn.execute(
                        _sql_text(
                            "SELECT id FROM agents WHERE legacy_mongo_id = :id"
                        ),
                        {"id": agent_id},
                    ).fetchone()
                if agent_row is None:
                    return make_response(
                        jsonify({"success": False, "message": "Agent not found"}),
                        404,
                    )
                pg_agent_id = str(agent_row._mapping["id"])

                users_repo = UsersRepository(conn)
                user_doc = users_repo.upsert(user_id)
                pinned_list = (
                    user_doc.get("agent_preferences", {}).get("pinned", [])
                    if isinstance(user_doc.get("agent_preferences"), dict)
                    else []
                )
                if pg_agent_id in pinned_list:
                    users_repo.remove_pinned(user_id, pg_agent_id)
                    action = "unpinned"
                else:
                    users_repo.add_pinned(user_id, pg_agent_id)
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
            with db_session() as conn:
                from sqlalchemy import text as _sql_text

                if looks_like_uuid(agent_id):
                    agent_row = conn.execute(
                        _sql_text(
                            "SELECT id FROM agents "
                            "WHERE id = CAST(:id AS uuid) AND shared = true"
                        ),
                        {"id": agent_id},
                    ).fetchone()
                else:
                    agent_row = conn.execute(
                        _sql_text(
                            "SELECT id FROM agents "
                            "WHERE legacy_mongo_id = :id AND shared = true"
                        ),
                        {"id": agent_id},
                    ).fetchone()
                if agent_row is None:
                    return make_response(
                        jsonify({"success": False, "message": "Shared agent not found"}),
                        404,
                    )
                pg_agent_id = str(agent_row._mapping["id"])

                users_repo = UsersRepository(conn)
                users_repo.upsert(user_id)
                users_repo.remove_agent_from_all(user_id, pg_agent_id)

            return make_response(jsonify({"success": True, "action": "removed"}), 200)
        except Exception as err:
            current_app.logger.error(f"Error removing shared agent: {err}")
            return make_response(
                jsonify({"success": False, "message": "Server error"}), 500
            )
