"""Prompt management routes."""


from typing import Optional

from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource

from docsgpt.api import api
from docsgpt.api.pat.rules import filter_listing, used_by_agent_allowlist
from docsgpt.api.user.folders.service import FolderError, ItemFiling, filing_folder, filing_owner
from docsgpt.api.user.resource_access import (
    _user_labels,
    AccessDenied,
    created_by_payload,
    creator_payloads,
    delete_settings,
    payload_for,
    require,
    settings_many,
)
from docsgpt.api.user.resource_usage import attach_used_by, deletable_ids_of
from docsgpt.api.user.team_sharing import visible_with_access
from docsgpt.drafter.prompt_checks import prompt_checks
from docsgpt.drafter.prompt_recipe import READ_MAX
from docsgpt.storage.db.repositories.folders import FolderItemsRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.prompts.composer import compose_preset, is_composed_preset
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.utils import check_required_fields
from docsgpt.workspaces.context import current_workspace, require_workspace_role, WorkspaceError
from docsgpt.workspaces.principal import is_principal_id

prompts_ns = Namespace(
    "prompts", description="Prompt management operations", path="/api"
)


def _denied(err: AccessDenied):
    """JSON response for an :class:`AccessDenied` (403 or 404)."""
    return make_response(jsonify({"success": False, "message": err.message}), err.status)


#: Longest ``preview`` a listed prompt carries.
PREVIEW_LENGTH = 200
#: Most ``POST /api/check_prompt`` calls a user makes in a minute. The editor checks once typing rests
#: (400 ms), so a writer stays well under it; a script can't keep a worker on 100,000-character checks.
CHECK_PROMPT_RATE_PER_MINUTE = 120

#: The built-in prompts, listed by name; they have no row.
PRESET_PROMPTS = ("default", "creative", "strict")


def prompt_preview(content: Optional[str]) -> str:
    """The start of a prompt's text for its card: whitespace collapsed, at most ``PREVIEW_LENGTH`` characters.

    Args:
        content: The prompt's text.

    Returns:
        str: The preview; empty for an empty prompt.
    """
    return " ".join((content or "").split())[:PREVIEW_LENGTH]


def _iso(value):
    """ISO-8601 string for a timestamp (``expected_updated_at`` round-trips it)."""
    return value.isoformat() if hasattr(value, "isoformat") else value


@prompts_ns.route("/create_prompt")
class CreatePrompt(Resource):
    create_prompt_model = api.model(
        "CreatePromptModel",
        {
            "content": fields.String(
                required=True, description="Content of the prompt"
            ),
            "name": fields.String(required=True, description="Name of the prompt"),
            "folder_id": fields.String(
                required=False, description="A folder of the workspace's tree to file the new prompt in"
            ),
        },
    )

    @api.expect(create_prompt_model)
    @api.doc(
        description=(
            "Create a new prompt in the workspace the request names (header X-DocsGPT-Workspace, default "
            "Personal); in a team it needs the Editor role and the team owns it"
        ),
        responses={
            200: "The new prompt's id and updated_at (the version a save over it sends back)",
            403: "A Viewer in the team (error workspace_role_required)",
            404: "Not a member of the named team (error workspace_not_found), or folder_id isn't a folder of the "
            "workspace's tree (error folder_not_found)",
        },
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        data = request.get_json()
        required_fields = ["content", "name"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        user = decoded_token.get("sub")
        try:
            with db_session() as conn:
                workspace = current_workspace(conn)
                require_workspace_role(workspace, "editor")
                owner_id, created_by = workspace.owner_for_create(user)
                folder_pg = filing_folder(conn, owner_id, data.get("folder_id"))
                prompt = PromptsRepository(conn).create(owner_id, data["name"], data["content"], created_by=created_by)
                if folder_pg:
                    FolderItemsRepository(conn).file(owner_id, "prompt", str(prompt["id"]), folder_pg)
            new_id = str(prompt["id"])
        except (WorkspaceError, FolderError) as err:
            return err.response()
        except Exception as err:
            current_app.logger.error(f"Error creating prompt: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"id": new_id, "updated_at": _iso(prompt.get("updated_at"))}), 200)


@prompts_ns.route("/get_prompts")
class GetPrompts(Resource):
    @api.doc(
        description=(
            "Get the prompts of the workspace the request names (header X-DocsGPT-Workspace, default Personal), "
            "after the built-in presets: in a team, the team's prompts with the caller's team role; in Personal, "
            "the caller's own and those shared with them, never a team's. Each row carries workspace, created_by "
            "{user_id, label}, access, allowed_actions, team_role, origin and its filing in the workspace's "
            "folder tree (folder_id, folder_path [{id, name}] from the top-level folder down; presets have none)"
        )
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            with db_readonly() as conn:
                workspace = current_workspace(conn)
                repo = PromptsRepository(conn)
                if workspace.is_team:
                    # The team's prompts only, by the caller's role; nobody's personal ones.
                    prompts, shared_prompts, team_shared = [], [], {}
                    team_prompts = repo.list_for_user(workspace.owner_id)
                    team_label = _user_labels(conn, [workspace.owner_id]).get(workspace.owner_id)
                else:
                    team_prompts, team_label = [], None
                    prompts = [p for p in repo.list_for_user(user) if not is_principal_id(p.get("user_id"))]
                    owned_ids = {str(p["id"]) for p in prompts}
                    team_shared = visible_with_access(conn, user, "prompt")
                    shared_ids = [pid for pid in team_shared if pid not in owned_ids]
                    # A team's prompt never shows in Personal, whatever a lookup answered.
                    shared_prompts = [
                        p for p in repo.list_by_ids(shared_ids) if not is_principal_id(p.get("user_id"))
                    ]
                switches = settings_many(
                    conn, "prompt", [*(str(p["id"]) for p in prompts), *(str(p["id"]) for p in shared_prompts)]
                )
                creators = creator_payloads(conn, user, [*prompts, *shared_prompts, *team_prompts])
                # Each prompt's filing in this workspace's folder tree.
                filing = ItemFiling(conn, workspace.owner_id, "prompt")
            list_prompts = [{"id": name, "name": name, "type": "public"} for name in PRESET_PROMPTS]
            for prompt in prompts:
                pid = str(prompt["id"])
                list_prompts.append(
                    {
                        "id": pid,
                        "name": prompt["name"],
                        "type": "private",
                        "preview": prompt_preview(prompt.get("content")),
                        "updated_at": _iso(prompt.get("updated_at")),
                        "created_by": created_by_payload(prompt, creators),
                        **filing.fields(pid),
                        **payload_for("prompt", "owner", switches.get(pid)),
                    }
                )
            for prompt in shared_prompts:
                pid = str(prompt["id"])
                list_prompts.append(
                    {
                        "id": pid,
                        "name": prompt["name"],
                        "type": "team",
                        "team_access": team_shared.get(pid),
                        "preview": prompt_preview(prompt.get("content")),
                        "updated_at": _iso(prompt.get("updated_at")),
                        "created_by": created_by_payload(prompt, creators),
                        **filing.fields(pid),
                        **payload_for("prompt", team_shared.get(pid), switches.get(pid)),
                    }
                )
            for prompt in team_prompts:
                list_prompts.append(
                    {
                        "id": str(prompt["id"]),
                        "name": prompt["name"],
                        # Compat: today's UI reads a team row like a shared one.
                        "type": "team",
                        "team_access": "viewer" if workspace.role in (None, "viewer") else "editor",
                        "owner_label": team_label,
                        "preview": prompt_preview(prompt.get("content")),
                        "updated_at": _iso(prompt.get("updated_at")),
                        "created_by": created_by_payload(prompt, creators),
                        **filing.fields(prompt["id"]),
                        **payload_for(
                            "prompt", None, None, team_id=workspace.team_id, team_role=workspace.role,
                            policy=workspace.outside_policy,
                        ),
                    }
                )
            # Presets (default/creative/strict) have no row id and stay visible to a restricted token.
            list_prompts = filter_listing(request, "prompts", list_prompts)
            with db_readonly() as conn:
                attach_used_by(
                    conn, user, "prompt", list_prompts,
                    deletable_ids=deletable_ids_of(list_prompts), agent_allowlist=used_by_agent_allowlist(request),
                )
        except WorkspaceError as err:
            return err.response()
        except Exception as err:
            current_app.logger.error(f"Error retrieving prompts: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(list_prompts), 200)


@prompts_ns.route("/get_single_prompt")
class GetSinglePrompt(Resource):
    @api.doc(params={"id": "ID of the prompt"}, description="Get a single prompt by ID")
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        prompt_id = request.args.get("id")
        if not prompt_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )
        try:
            if is_composed_preset(prompt_id):
                return make_response(
                    jsonify({"content": compose_preset(prompt_id)}), 200
                )
            with db_readonly() as conn:
                ra = require(conn, "prompt", prompt_id, user, "use")
                prompt = PromptsRepository(conn).get_any(ra.resource_id, ra.owner_id)
                creators = creator_payloads(conn, user, [prompt] if prompt else [])
                filed = ItemFiling(conn, filing_owner(ra, user), "prompt").fields(ra.resource_id) if prompt else {}
            if not prompt:
                return make_response(
                    jsonify({"success": False, "message": "Prompt not found"}), 404
                )
        except AccessDenied as err:
            return _denied(err)
        except Exception as err:
            current_app.logger.error(f"Error retrieving prompt: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(
            jsonify(
                {
                    "content": prompt["content"],
                    "name": prompt.get("name"),
                    "updated_at": _iso(prompt.get("updated_at")),
                    "created_by": created_by_payload(prompt, creators),
                    **filed,
                    **ra.payload(),
                }
            ),
            200,
        )


@prompts_ns.route("/delete_prompt")
class DeletePrompt(Resource):
    delete_prompt_model = api.model(
        "DeletePromptModel",
        {"id": fields.String(required=True, description="Prompt ID to delete")},
    )

    @api.expect(delete_prompt_model)
    @api.doc(description="Delete a prompt by ID")
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
                ra = require(conn, "prompt", data["id"], user, "delete")
                # Grants go with the row (delete trigger); switches have no FK.
                PromptsRepository(conn).delete(ra.resource_id, ra.owner_id)
                delete_settings(conn, "prompt", ra.resource_id)
        except AccessDenied as err:
            return _denied(err)
        except Exception as err:
            current_app.logger.error(f"Error deleting prompt: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@prompts_ns.route("/update_prompt")
class UpdatePrompt(Resource):
    update_prompt_model = api.model(
        "UpdatePromptModel",
        {
            "id": fields.String(required=True, description="Prompt ID to update"),
            "name": fields.String(required=True, description="New name of the prompt"),
            "content": fields.String(
                required=True, description="New content of the prompt"
            ),
            "expected_updated_at": fields.String(
                required=False,
                description="The prompt's updated_at as last read or saved; the save is refused (409) "
                "when someone saved it since",
            ),
            "folder_id": fields.String(
                required=False,
                description="File the prompt in this folder of its workspace's tree; null takes it out",
            ),
        },
    )

    @api.expect(update_prompt_model)
    @api.doc(
        description="Update an existing prompt",
        responses={
            200: "Saved: success and the new updated_at, the version the next save sends back",
            409: "Someone saved the prompt since expected_updated_at (code stale_write)",
        },
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "name", "content"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            with db_session() as conn:
                ra = require(conn, "prompt", data["id"], user, "edit")
                # A team's prompt is filed in the team's tree, anyone else's in the caller's own.
                tree_owner = filing_owner(ra, user)
                folder_pg = filing_folder(conn, tree_owner, data["folder_id"]) if "folder_id" in data else None
                result = PromptsRepository(conn).update_by_id(
                    ra.resource_id,
                    data["name"],
                    data["content"],
                    expected_updated_at=data.get("expected_updated_at"),
                )
                if result is None:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "Prompt was modified by someone else",
                                "code": "stale_write",
                            }
                        ),
                        409,
                    )
                if "folder_id" in data:
                    FolderItemsRepository(conn).file(tree_owner, "prompt", ra.resource_id, folder_pg)
        except AccessDenied as err:
            return _denied(err)
        except FolderError as err:
            return err.response()
        except Exception as err:
            current_app.logger.error(f"Error updating prompt: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(
            jsonify({"success": True, "updated_at": _iso(result) if isinstance(result, str) else None}), 200
        )


@prompts_ns.route("/check_prompt")
class CheckPrompt(Resource):
    check_prompt_model = api.model(
        "CheckPromptModel",
        {
            "content": fields.String(
                required=True, description=f"The prompt's text as the editor holds it, at most {READ_MAX:,} characters"
            ),
        },
    )

    @api.expect(check_prompt_model)
    @api.doc(
        description="Check a prompt's text without a model: blanks left in, lines DocsGPT already adds to a "
        "persona, and a template that doesn't parse, runs tool variables, or lacks the Boundaries section or "
        "citation rules. Each check is a code the client words; works with the drafter off",
        responses={
            200: "checks: at most 20 of {code, ...}: placeholder {text, line}, repeats_builtin {topic, line}, "
            "template_invalid, tool_variables {variables}, boundaries_missing, citations_missing",
            400: "content is missing, not text, or too long",
            429: f"more than {CHECK_PROMPT_RATE_PER_MINUTE} checks in a minute",
        },
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        from docsgpt.monitors import triggers

        if triggers.rate_limited("check_prompt", decoded_token.get("sub"), CHECK_PROMPT_RATE_PER_MINUTE):
            return make_response(jsonify({"success": False, "message": "Too many checks in a minute"}), 429)
        data = request.get_json(silent=True)
        content = data.get("content") if isinstance(data, dict) else None
        if not isinstance(content, str):
            return make_response(jsonify({"success": False, "message": "content must be text"}), 400)
        if len(content) > READ_MAX:
            return make_response(
                jsonify({"success": False, "message": f"content can be at most {READ_MAX:,} characters"}), 400
            )
        return make_response(jsonify({"checks": prompt_checks(content)}), 200)
