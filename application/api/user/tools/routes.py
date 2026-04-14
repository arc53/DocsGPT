"""Tool management routes."""

from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource

from application.agents.tools.spec_parser import parse_spec
from application.agents.tools.tool_manager import ToolManager
from application.api import api
from application.core.url_validation import SSRFError, validate_url
from application.security.encryption import decrypt_credentials, encrypt_credentials
from application.storage.db.repositories.notes import NotesRepository
from application.storage.db.repositories.todos import TodosRepository
from application.storage.db.repositories.user_tools import UserToolsRepository
from application.storage.db.session import db_readonly, db_session
from application.utils import check_required_fields, validate_function_name

tool_config = {}
tool_manager = ToolManager(config=tool_config)


# ---------------------------------------------------------------------------
# Shape translation helpers
# ---------------------------------------------------------------------------
# The frontend speaks camelCase (``displayName`` / ``customName`` /
# ``configRequirements``). The PG ``user_tools`` table stores snake_case
# (``display_name`` / ``custom_name`` / ``config_requirements``). Keep the
# translation localized to this module so repositories stay pure.

_CAMEL_TO_SNAKE = {
    "displayName": "display_name",
    "customName": "custom_name",
    "configRequirements": "config_requirements",
}
_SNAKE_TO_CAMEL = {v: k for k, v in _CAMEL_TO_SNAKE.items()}


def _row_to_api(row: dict) -> dict:
    """Rename DB-native snake_case keys to the camelCase shape the frontend expects."""
    out = dict(row)
    for snake, camel in _SNAKE_TO_CAMEL.items():
        if snake in out:
            out[camel] = out.pop(snake)
    # ``user_id`` is exposed as ``user`` in the legacy API shape.
    if "user_id" in out:
        out["user"] = out.pop("user_id")
    return out


def _api_to_update_fields(data: dict) -> dict:
    """Rename incoming camelCase update keys to the repo's snake_case columns."""
    fields_out: dict = {}
    for key, value in data.items():
        fields_out[_CAMEL_TO_SNAKE.get(key, key)] = value
    return fields_out


def _encrypt_secret_fields(config, config_requirements, user_id):
    secret_keys = [
        key for key, spec in config_requirements.items()
        if spec.get("secret") and key in config and config[key]
    ]
    if not secret_keys:
        return config

    storage_config = config.copy()
    secret_values = {k: config[k] for k in secret_keys}
    storage_config["encrypted_credentials"] = encrypt_credentials(secret_values, user_id)
    for key in secret_keys:
        storage_config.pop(key, None)
    return storage_config


def _validate_config(config, config_requirements, has_existing_secrets=False):
    errors = {}
    for key, spec in config_requirements.items():
        depends_on = spec.get("depends_on")
        if depends_on:
            if not all(config.get(dk) == dv for dk, dv in depends_on.items()):
                continue
        if spec.get("required") and not config.get(key):
            if has_existing_secrets and spec.get("secret"):
                continue
            errors[key] = f"{spec.get('label', key)} is required"
        value = config.get(key)
        if value is not None and value != "":
            if spec.get("type") == "number":
                try:
                    num = float(value)
                    if key == "timeout" and (num < 1 or num > 300):
                        errors[key] = "Timeout must be between 1 and 300"
                except (ValueError, TypeError):
                    errors[key] = f"{spec.get('label', key)} must be a number"
            if spec.get("enum") and value not in spec["enum"]:
                errors[key] = f"Invalid value for {spec.get('label', key)}"
    return errors


def _merge_secrets_on_update(new_config, existing_config, config_requirements, user_id):
    """Merge incoming config with existing encrypted secrets and re-encrypt.

    For updates, the client may omit unchanged secret values.  This helper
    decrypts any previously stored secrets, overlays whatever the client *did*
    send, strips plain-text secrets from the stored config, and re-encrypts
    the merged result.

    Returns the final ``config`` dict ready for persistence.
    """
    secret_keys = [
        key for key, spec in config_requirements.items()
        if spec.get("secret")
    ]

    if not secret_keys:
        return new_config

    existing_secrets = {}
    if "encrypted_credentials" in existing_config:
        existing_secrets = decrypt_credentials(
            existing_config["encrypted_credentials"], user_id
        )

    merged_secrets = existing_secrets.copy()
    for key in secret_keys:
        if key in new_config and new_config[key]:
            merged_secrets[key] = new_config[key]

    # Start from existing non-secret values, then overlay incoming non-secrets
    storage_config = {
        k: v for k, v in existing_config.items()
        if k not in secret_keys and k != "encrypted_credentials"
    }
    storage_config.update(
        {k: v for k, v in new_config.items() if k not in secret_keys}
    )

    if merged_secrets:
        storage_config["encrypted_credentials"] = encrypt_credentials(
            merged_secrets, user_id
        )
    else:
        storage_config.pop("encrypted_credentials", None)

    storage_config.pop("has_encrypted_credentials", None)
    return storage_config


def transform_actions(actions_metadata):
    """Set default flags on action metadata for storage.

    Marks each action as active, sets ``filled_by_llm`` and ``value`` on every
    parameter property. Used by both the generic create_tool and MCP save routes.
    """
    transformed = []
    for action in actions_metadata:
        action["active"] = True
        if "parameters" in action:
            props = action["parameters"].get("properties", {})
            for param_details in props.values():
                param_details["filled_by_llm"] = True
                param_details["value"] = ""
        transformed.append(action)
    return transformed


tools_ns = Namespace("tools", description="Tool management operations", path="/api")


@tools_ns.route("/available_tools")
class AvailableTools(Resource):
    @api.doc(description="Get available tools for a user")
    def get(self):
        if not request.decoded_token:
            return make_response(jsonify({"success": False}), 401)
        try:
            tools_metadata = []
            for tool_name, tool_instance in tool_manager.tools.items():
                doc = tool_instance.__doc__.strip()
                lines = doc.split("\n", 1)
                name = lines[0].strip()
                description = lines[1].strip() if len(lines) > 1 else ""
                config_req = tool_instance.get_config_requirements()
                actions = tool_instance.get_actions_metadata()
                tools_metadata.append(
                    {
                        "name": tool_name,
                        "displayName": name,
                        "description": description,
                        "configRequirements": config_req,
                        "actions": actions,
                    }
                )
        except Exception as err:
            current_app.logger.error(
                f"Error getting available tools: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "data": tools_metadata}), 200)


@tools_ns.route("/get_tools")
class GetTools(Resource):
    @api.doc(description="Get tools created by a user")
    def get(self):
        try:
            decoded_token = request.decoded_token
            if not decoded_token:
                return make_response(jsonify({"success": False}), 401)
            user = decoded_token.get("sub")
            with db_readonly() as conn:
                rows = UserToolsRepository(conn).list_for_user(user)
            user_tools = []
            for row in rows:
                tool_copy = _row_to_api(row)

                config_req = tool_copy.get("configRequirements", {})
                if not config_req:
                    tool_instance = tool_manager.tools.get(tool_copy.get("name"))
                    if tool_instance:
                        config_req = tool_instance.get_config_requirements()
                        tool_copy["configRequirements"] = config_req

                has_secrets = any(
                    spec.get("secret") for spec in config_req.values()
                ) if config_req else False
                if has_secrets and "encrypted_credentials" in tool_copy.get("config", {}):
                    tool_copy["config"]["has_encrypted_credentials"] = True
                    tool_copy["config"].pop("encrypted_credentials", None)

                user_tools.append(tool_copy)
        except Exception as err:
            current_app.logger.error(f"Error getting user tools: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "tools": user_tools}), 200)


@tools_ns.route("/create_tool")
class CreateTool(Resource):
    @api.expect(
        api.model(
            "CreateToolModel",
            {
                "name": fields.String(required=True, description="Name of the tool"),
                "displayName": fields.String(
                    required=True, description="Display name for the tool"
                ),
                "description": fields.String(
                    required=True, description="Tool description"
                ),
                "config": fields.Raw(
                    required=True, description="Configuration of the tool"
                ),
                "customName": fields.String(
                    required=False, description="Custom name for the tool"
                ),
                "status": fields.Boolean(
                    required=True, description="Status of the tool"
                ),
            },
        )
    )
    @api.doc(description="Create a new tool")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = [
            "name",
            "displayName",
            "description",
            "config",
            "status",
        ]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            if data["name"] == "mcp_tool":
                server_url = (data.get("config", {}).get("server_url") or "").strip()
                if server_url:
                    try:
                        validate_url(server_url)
                    except SSRFError:
                        return make_response(
                            jsonify({"success": False, "message": "Invalid server URL"}),
                            400,
                        )
            tool_instance = tool_manager.tools.get(data["name"])
            if not tool_instance:
                return make_response(
                    jsonify({"success": False, "message": "Tool not found"}), 404
                )
            actions_metadata = tool_instance.get_actions_metadata()
            transformed_actions = transform_actions(actions_metadata)
        except Exception as err:
            current_app.logger.error(
                f"Error getting tool actions: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        try:
            config_requirements = tool_instance.get_config_requirements()
            if config_requirements:
                validation_errors = _validate_config(
                    data["config"], config_requirements
                )
                if validation_errors:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "Validation failed",
                                "errors": validation_errors,
                            }
                        ),
                        400,
                    )
            storage_config = _encrypt_secret_fields(
                data["config"], config_requirements, user
            )
            with db_session() as conn:
                created = UserToolsRepository(conn).create(
                    user,
                    data["name"],
                    config=storage_config,
                    custom_name=data.get("customName", ""),
                    display_name=data["displayName"],
                    description=data["description"],
                    config_requirements=config_requirements,
                    actions=transformed_actions,
                    status=bool(data.get("status", True)),
                )
            new_id = str(created["id"])
        except Exception as err:
            current_app.logger.error(f"Error creating tool: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"id": new_id}), 200)


@tools_ns.route("/update_tool")
class UpdateTool(Resource):
    @api.expect(
        api.model(
            "UpdateToolModel",
            {
                "id": fields.String(required=True, description="Tool ID"),
                "name": fields.String(description="Name of the tool"),
                "displayName": fields.String(description="Display name for the tool"),
                "customName": fields.String(description="Custom name for the tool"),
                "description": fields.String(description="Tool description"),
                "config": fields.Raw(description="Configuration of the tool"),
                "actions": fields.List(
                    fields.Raw, description="Actions the tool can perform"
                ),
                "status": fields.Boolean(description="Status of the tool"),
            },
        )
    )
    @api.doc(description="Update a tool by ID")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            update_data: dict = {}
            for key in ("name", "displayName", "customName", "description", "actions"):
                if key in data:
                    update_data[key] = data[key]
            if "config" in data:
                if "actions" in data["config"]:
                    for action_name in list(data["config"]["actions"].keys()):
                        if not validate_function_name(action_name):
                            return make_response(
                                jsonify(
                                    {
                                        "success": False,
                                        "message": f"Invalid function name '{action_name}'. Function names must match pattern '^[a-zA-Z0-9_-]+$'.",
                                        "param": "tools[].function.name",
                                    }
                                ),
                                400,
                            )
                with db_session() as conn:
                    repo = UserToolsRepository(conn)
                    tool_doc = repo.get_any(data["id"], user)
                    if not tool_doc:
                        return make_response(
                            jsonify({"success": False, "message": "Tool not found"}),
                            404,
                        )
                    tool_name = tool_doc.get("name", data.get("name"))
                    tool_instance = tool_manager.tools.get(tool_name)
                    config_requirements = (
                        tool_instance.get_config_requirements()
                        if tool_instance
                        else {}
                    )
                    existing_config = tool_doc.get("config", {}) or {}
                    has_existing_secrets = "encrypted_credentials" in existing_config

                    if config_requirements:
                        validation_errors = _validate_config(
                            data["config"], config_requirements,
                            has_existing_secrets=has_existing_secrets,
                        )
                        if validation_errors:
                            return make_response(
                                jsonify({
                                    "success": False,
                                    "message": "Validation failed",
                                    "errors": validation_errors,
                                }),
                                400,
                            )

                    update_data["config"] = _merge_secrets_on_update(
                        data["config"], existing_config, config_requirements, user
                    )
                    if "status" in data:
                        update_data["status"] = bool(data["status"])
                    repo.update(
                        str(tool_doc["id"]), user, _api_to_update_fields(update_data),
                    )
            else:
                if "status" in data:
                    update_data["status"] = bool(data["status"])
                with db_session() as conn:
                    repo = UserToolsRepository(conn)
                    tool_doc = repo.get_any(data["id"], user)
                    if not tool_doc:
                        return make_response(
                            jsonify({"success": False, "message": "Tool not found"}),
                            404,
                        )
                    repo.update(
                        str(tool_doc["id"]), user, _api_to_update_fields(update_data),
                    )
        except Exception as err:
            current_app.logger.error(f"Error updating tool: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@tools_ns.route("/update_tool_config")
class UpdateToolConfig(Resource):
    @api.expect(
        api.model(
            "UpdateToolConfigModel",
            {
                "id": fields.String(required=True, description="Tool ID"),
                "config": fields.Raw(
                    required=True, description="Configuration of the tool"
                ),
            },
        )
    )
    @api.doc(description="Update the configuration of a tool")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "config"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            with db_session() as conn:
                repo = UserToolsRepository(conn)
                tool_doc = repo.get_any(data["id"], user)
                if not tool_doc:
                    return make_response(jsonify({"success": False}), 404)

                tool_name = tool_doc.get("name")
                if tool_name == "mcp_tool":
                    server_url = (data["config"].get("server_url") or "").strip()
                    if server_url:
                        try:
                            validate_url(server_url)
                        except SSRFError:
                            return make_response(
                                jsonify({"success": False, "message": "Invalid server URL"}),
                                400,
                            )
                tool_instance = tool_manager.tools.get(tool_name)
                config_requirements = (
                    tool_instance.get_config_requirements() if tool_instance else {}
                )
                existing_config = tool_doc.get("config", {}) or {}
                has_existing_secrets = "encrypted_credentials" in existing_config

                if config_requirements:
                    validation_errors = _validate_config(
                        data["config"], config_requirements,
                        has_existing_secrets=has_existing_secrets,
                    )
                    if validation_errors:
                        return make_response(
                            jsonify({
                                "success": False,
                                "message": "Validation failed",
                                "errors": validation_errors,
                            }),
                            400,
                        )

                final_config = _merge_secrets_on_update(
                    data["config"], existing_config, config_requirements, user
                )

                repo.update(str(tool_doc["id"]), user, {"config": final_config})
        except Exception as err:
            current_app.logger.error(
                f"Error updating tool config: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@tools_ns.route("/update_tool_actions")
class UpdateToolActions(Resource):
    @api.expect(
        api.model(
            "UpdateToolActionsModel",
            {
                "id": fields.String(required=True, description="Tool ID"),
                "actions": fields.List(
                    fields.Raw,
                    required=True,
                    description="Actions the tool can perform",
                ),
            },
        )
    )
    @api.doc(description="Update the actions of a tool")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "actions"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            with db_session() as conn:
                repo = UserToolsRepository(conn)
                tool_doc = repo.get_any(data["id"], user)
                if not tool_doc:
                    return make_response(
                        jsonify({"success": False, "message": "Tool not found"}),
                        404,
                    )
                repo.update(
                    str(tool_doc["id"]), user, {"actions": data["actions"]},
                )
        except Exception as err:
            current_app.logger.error(
                f"Error updating tool actions: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@tools_ns.route("/update_tool_status")
class UpdateToolStatus(Resource):
    @api.expect(
        api.model(
            "UpdateToolStatusModel",
            {
                "id": fields.String(required=True, description="Tool ID"),
                "status": fields.Boolean(
                    required=True, description="Status of the tool"
                ),
            },
        )
    )
    @api.doc(description="Update the status of a tool")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "status"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            with db_session() as conn:
                repo = UserToolsRepository(conn)
                tool_doc = repo.get_any(data["id"], user)
                if not tool_doc:
                    return make_response(
                        jsonify({"success": False, "message": "Tool not found"}),
                        404,
                    )
                repo.update(
                    str(tool_doc["id"]), user, {"status": bool(data["status"])},
                )
        except Exception as err:
            current_app.logger.error(
                f"Error updating tool status: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@tools_ns.route("/delete_tool")
class DeleteTool(Resource):
    @api.expect(
        api.model(
            "DeleteToolModel",
            {"id": fields.String(required=True, description="Tool ID")},
        )
    )
    @api.doc(description="Delete a tool by ID")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            with db_session() as conn:
                repo = UserToolsRepository(conn)
                tool_doc = repo.get_any(data["id"], user)
                if not tool_doc:
                    return make_response(
                        jsonify({"success": False, "message": "Tool not found"}), 404
                    )
                repo.delete(str(tool_doc["id"]), user)
        except Exception as err:
            current_app.logger.error(f"Error deleting tool: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@tools_ns.route("/parse_spec")
class ParseSpec(Resource):
    @api.doc(
        description="Parse an API specification (OpenAPI 3.x or Swagger 2.0) and return actions"
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        if "file" in request.files:
            file = request.files["file"]
            if not file.filename:
                return make_response(
                    jsonify({"success": False, "message": "No file selected"}), 400
                )
            try:
                spec_content = file.read().decode("utf-8")
            except UnicodeDecodeError:
                return make_response(
                    jsonify({"success": False, "message": "Invalid file encoding"}), 400
                )
        elif request.is_json:
            data = request.get_json()
            spec_content = data.get("spec_content", "")
        else:
            return make_response(
                jsonify({"success": False, "message": "No spec provided"}), 400
            )
        if not spec_content or not spec_content.strip():
            return make_response(
                jsonify({"success": False, "message": "Empty spec content"}), 400
            )
        try:
            metadata, actions = parse_spec(spec_content)
            return make_response(
                jsonify(
                    {
                        "success": True,
                        "metadata": metadata,
                        "actions": actions,
                    }
                ),
                200,
            )
        except ValueError as e:
            current_app.logger.error(f"Spec validation error: {e}")
            return make_response(jsonify({"success": False, "error": "Invalid specification format"}), 400)
        except Exception as err:
            current_app.logger.error(f"Error parsing spec: {err}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to parse specification"}), 500)


@tools_ns.route("/artifact/<artifact_id>")
class GetArtifact(Resource):
    @api.doc(description="Get artifact data by artifact ID. Returns all todos for the tool when fetching a todo artifact.")
    def get(self, artifact_id: str):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user_id = decoded_token.get("sub")

        try:
            with db_readonly() as conn:
                notes_repo = NotesRepository(conn)
                todos_repo = TodosRepository(conn)

                # Artifact IDs may be PG UUIDs (post-cutover) or legacy
                # Mongo ObjectIds embedded in older conversation history.
                note_doc = None
                try:
                    note_doc = notes_repo.get(artifact_id, user_id)
                except Exception:
                    note_doc = None
                # TODO(pg-cutover): NotesRepository needs get_any for legacy
                # ObjectId fallback; until then, notes referenced by legacy
                # artifact ids in old messages won't resolve.

                if note_doc:
                    content = note_doc.get("note", "") or note_doc.get("content", "")
                    line_count = len(content.split("\n")) if content else 0
                    updated = note_doc.get("updated_at")
                    artifact = {
                        "artifact_type": "note",
                        "data": {
                            "content": content,
                            "line_count": line_count,
                            "updated_at": (
                                updated.isoformat()
                                if hasattr(updated, "isoformat")
                                else updated
                            ),
                        },
                    }
                    return make_response(
                        jsonify({"success": True, "artifact": artifact}), 200
                    )

                todo_doc = None
                try:
                    todo_doc = todos_repo.get(artifact_id, user_id)
                except Exception:
                    todo_doc = None
                if todo_doc is None:
                    legacy = todos_repo.get_by_legacy_id(artifact_id)
                    if legacy and legacy.get("user_id") == user_id:
                        todo_doc = legacy
                if todo_doc:
                    tool_id = todo_doc.get("tool_id")
                    all_todos = todos_repo.list_for_tool(user_id, tool_id) if tool_id else []
                    items = []
                    open_count = 0
                    completed_count = 0
                    for t in all_todos:
                        # PG ``todos`` stores a ``completed BOOLEAN`` column;
                        # the legacy Mongo shape used a ``status`` string.
                        # Keep the response shape stable by translating here.
                        status = "completed" if t.get("completed") else "open"
                        if status == "open":
                            open_count += 1
                        else:
                            completed_count += 1
                        created = t.get("created_at")
                        updated = t.get("updated_at")
                        items.append({
                            "todo_id": t.get("todo_id"),
                            "title": t.get("title", ""),
                            "status": status,
                            "created_at": (
                                created.isoformat()
                                if hasattr(created, "isoformat")
                                else created
                            ),
                            "updated_at": (
                                updated.isoformat()
                                if hasattr(updated, "isoformat")
                                else updated
                            ),
                        })
                    artifact = {
                        "artifact_type": "todo_list",
                        "data": {
                            "items": items,
                            "total_count": len(items),
                            "open_count": open_count,
                            "completed_count": completed_count,
                        },
                    }
                    return make_response(
                        jsonify({"success": True, "artifact": artifact}), 200
                    )
        except Exception as err:
            current_app.logger.error(
                f"Error retrieving artifact: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)

        return make_response(
            jsonify({"success": False, "message": "Artifact not found"}), 404
        )
