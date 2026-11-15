"""``/api/folders``: one folder tree per workspace for agents, knowledge (sources), tools and prompts.

A list or a create works in the request's workspace (``X-DocsGPT-Workspace``):
the caller's own tree in Personal, the team's one tree in a team. A route
about one folder goes by the folder's own owner. In a team any member lists,
and creating, renaming, moving, filing and deleting need Editor. ``type`` on a
list only picks what ``item_count`` counts. The rules live in
:mod:`docsgpt.api.user.folders.service`. A token needs the read/write scope of
any of the four families for the tree itself, and the family's own scope to
file items of that kind.
"""

from __future__ import annotations

from typing import Optional

from flask import Response, current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource, fields

from docsgpt.api import api
from docsgpt.api.pat.rules import missing_scope_response, used_by_agent_allowlist
from docsgpt.api.user.folders.service import (
    MAX_FILING_IDS,
    FolderError,
    create_folder,
    delete_folder,
    file_items,
    folder_by_id,
    folder_error,
    list_folders,
    parse_optional_type,
    parse_resource_type,
    serialize_folder,
    update_folder,
    workspace_tree,
)
from docsgpt.api.user.resource_access import created_by_payload, creator_payloads
from docsgpt.api.user.resource_usage import empty_usage, used_by_many
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.workspaces.context import WorkspaceError, current_workspace

folders_ns = Namespace("folders", description="Folders for agents, knowledge, tools and prompts", path="/api")

#: The token scope family of each item kind.
TYPE_FAMILY = {"agent": "agents", "source": "sources", "tool": "tools", "prompt": "prompts"}

_FOLDER_MODEL = api.model(
    "Folder",
    {
        "id": fields.String(description="Folder id"),
        "name": fields.String(description="Folder name"),
        "parent_id": fields.String(description="Parent folder id; null at the top level"),
        "type": fields.String(description="The kind the request named (agent when none); folders hold every kind"),
        "created_by": fields.Raw(description="{user_id, label} of the person who made it, or null"),
        "created_at": fields.String(description="ISO timestamp"),
        "updated_at": fields.String(description="ISO timestamp"),
        "counts": fields.Raw(description="{agent, source, tool, prompt}: items filed directly in it the caller can see"),
        "item_count": fields.Integer(description="Items of the requested type filed directly in it (all kinds without)"),
        "folder_count": fields.Integer(description="Folders directly in it"),
        "used_by": fields.Raw(
            description="{agents: [{id, name, agent_type, can_edit, status}], others}: who reads its sources live"
        ),
    },
)


def _user() -> Optional[str]:
    decoded = getattr(request, "decoded_token", None)
    return decoded.get("sub") if decoded else None


def _unauthorized() -> Response:
    return make_response(jsonify({"success": False, "message": "Unauthorized"}), 401)


def _scope_refusal(resource_type: str, write: bool) -> Optional[Response]:
    """A token's 403 when it lacks the read/write scope of one kind's family."""
    refusal = missing_scope_response(request, f"{TYPE_FAMILY[resource_type]}:{'write' if write else 'read'}")
    return make_response(jsonify(refusal[0]), refusal[1]) if refusal else None


def _any_scope_refusal(write: bool) -> Optional[Response]:
    """A token's 403 when it lacks the scope of every kind: a folder holds every kind."""
    refusal = None
    for resource_type in TYPE_FAMILY:
        refusal = _scope_refusal(resource_type, write)
        if refusal is None:
            return None
    return refusal


def _body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise FolderError(400, "invalid_body", "A JSON object is required")
    return body


def _server_error(message: str, err: Exception) -> Response:
    current_app.logger.error(f"{message}: {err}", exc_info=True)
    return folder_error(500, "server_error", message)


def _with_counts(folder: dict, resource_type: Optional[str], created_by: Optional[dict]) -> dict:
    return {
        **serialize_folder(folder, resource_type),
        "created_by": created_by,
        "counts": {kind: 0 for kind in TYPE_FAMILY},
        "item_count": 0,
        "folder_count": 0,
        "used_by": empty_usage(),
    }


def _creator(conn, user: str, folder: dict) -> Optional[dict]:
    return created_by_payload(folder, creator_payloads(conn, user, [folder]))


@folders_ns.route("/folders")
class Folders(Resource):
    @api.doc(
        description=(
            "The folder tree of the workspace the request names (header X-DocsGPT-Workspace, default "
            "Personal), oldest first: {folders: [Folder], workspace}. In a team it is the team's one tree, the "
            "same for every member. counts, item_count and folder_count count direct children; used_by names "
            "the agents reading a folder's sources live. 404 workspace_not_found for a team the caller isn't in."
        ),
        params={"type": "agent, source, tool or prompt (optional): the kind item_count counts"},
    )
    def get(self):
        user = _user()
        if not user:
            return _unauthorized()
        try:
            resource_type = parse_optional_type(request.args.get("type"))
        except FolderError as err:
            return err.response()
        refusal = _scope_refusal(resource_type, write=False) if resource_type else _any_scope_refusal(write=False)
        if refusal is not None:
            return refusal
        try:
            with db_readonly() as conn:
                workspace = current_workspace(conn)
                tree = workspace_tree(workspace)
                tree.require("list")
                folders = list_folders(conn, user, resource_type, tree=tree)
                if folders:
                    ids = [f["id"] for f in folders]
                    usage = used_by_many(
                        conn, user, "folder", ids, deletable_ids=ids, agent_allowlist=used_by_agent_allowlist(request),
                    )
                    for folder in folders:
                        folder["used_by"] = usage.get(folder["id"]) or empty_usage()
        except (FolderError, WorkspaceError) as err:
            return err.response()
        except Exception as err:
            return _server_error("Failed to fetch folders", err)
        return make_response(jsonify({"folders": folders, "workspace": workspace.payload()}), 200)

    @api.doc(
        description=(
            "Create a folder in the workspace the request names: {name, parent_id?} (type is ignored). Names "
            "are trimmed, 1-80 characters, unique among siblings ignoring case across kinds (409 "
            "folder_name_taken); folders nest 3 levels deep (400 folder_too_deep). In a team it needs the "
            "Editor role (403 workspace_role_required). Answers 201 with the Folder."
        )
    )
    @api.response(201, "The new folder", _FOLDER_MODEL)
    @api.expect(
        api.model(
            "CreateFolderRequest",
            {
                "type": fields.String(required=False, description="Ignored: a folder holds every kind"),
                "name": fields.String(required=True, description="Folder name"),
                "parent_id": fields.String(required=False, description="Parent folder id"),
            },
        )
    )
    def post(self):
        user = _user()
        if not user:
            return _unauthorized()
        if (refusal := _any_scope_refusal(write=True)) is not None:
            return refusal
        try:
            data = _body()
            try:
                # Only echoed back as ``type``: a folder holds every kind.
                resource_type = parse_optional_type(data.get("type"))
            except FolderError:
                resource_type = None
            with db_session() as conn:
                tree = workspace_tree(current_workspace(conn))
                tree.require("create")
                folder = create_folder(
                    conn, tree.owner_id, resource_type, data.get("name"), data.get("parent_id"), created_by=user,
                )
                created_by = _creator(conn, user, folder)
        except (FolderError, WorkspaceError) as err:
            return err.response()
        except Exception as err:
            return _server_error("Failed to create folder", err)
        return make_response(jsonify(_with_counts(folder, resource_type, created_by)), 201)


@folders_ns.route("/folders/<string:folder_id>")
class FolderResource(Resource):
    @api.doc(
        description=(
            "Rename or move a folder within its tree: {name?, parent_id?}; parent_id null moves it to the top "
            "level. The folder's own tree decides (a team's folder needs the Editor role there). Errors: 404 "
            "folder_not_found, 403 workspace_role_required, 400 folder_cycle / folder_too_deep, 409 "
            "folder_name_taken."
        )
    )
    @api.expect(
        api.model(
            "UpdateFolderRequest",
            {
                "name": fields.String(required=False, description="New name"),
                "parent_id": fields.String(required=False, description="New parent folder id, or null"),
            },
        )
    )
    def put(self, folder_id: str):
        user = _user()
        if not user:
            return _unauthorized()
        if (refusal := _any_scope_refusal(write=True)) is not None:
            return refusal
        try:
            data = _body()
            with db_session() as conn:
                folder, tree = folder_by_id(conn, folder_id, user)
                if "name" in data:
                    tree.require("rename")
                if "parent_id" in data:
                    tree.require("move")
                kwargs = {key: data[key] for key in ("name", "parent_id") if key in data}
                folder = update_folder(conn, tree.owner_id, folder, **kwargs)
        except FolderError as err:
            return err.response()
        except Exception as err:
            return _server_error("Failed to update folder", err)
        return make_response(jsonify(serialize_folder(folder)), 200)

    @api.doc(
        description=(
            "Delete a folder. Its folders and items move to its parent (the top level and unfiled when it "
            "had none); a child folder whose name is taken there gets a \" (n)\" suffix; agents reading it "
            "live lose it. A team's folder needs the Editor role there. Answers {success, moved_items, "
            "moved_folders, renamed: [{id, from, to}]}."
        )
    )
    def delete(self, folder_id: str):
        user = _user()
        if not user:
            return _unauthorized()
        if (refusal := _any_scope_refusal(write=True)) is not None:
            return refusal
        try:
            with db_session() as conn:
                folder, tree = folder_by_id(conn, folder_id, user)
                tree.require("delete")
                moved = delete_folder(conn, folder)
        except FolderError as err:
            return err.response()
        except Exception as err:
            return _server_error("Failed to delete folder", err)
        return make_response(jsonify({"success": True, **moved}), 200)


@folders_ns.route("/folders/items")
class FolderItems(Resource):
    @api.doc(
        description=(
            "File items into a folder: {type, folder_id, ids}; folder_id null takes them out of the tree of "
            "the workspace the request names. A team's folder holds only the team's own items and needs the "
            "Editor role (403 workspace_role_required); a personal folder holds the caller's own items and "
            "personal items shared with them. 409 team_item_not_fileable (a team's item into a personal "
            "folder) or item_not_in_team (anything else into a team's folder), with ids; nothing is filed then. "
            "Answers {success, moved: [ids], skipped: [ids the caller can't see]}."
        )
    )
    @api.expect(
        api.model(
            "FileFolderItemsRequest",
            {
                "type": fields.String(required=True, description="agent, source, tool or prompt"),
                "folder_id": fields.String(required=False, description="Target folder id, or null to unfile"),
                "ids": fields.List(fields.String, required=True, description="Ids of items of that kind"),
            },
        )
    )
    def post(self):
        user = _user()
        if not user:
            return _unauthorized()
        try:
            data = _body()
            resource_type = parse_resource_type(data.get("type"))
            if (refusal := _scope_refusal(resource_type, write=True)) is not None:
                return refusal
            ids = data.get("ids")
            if not isinstance(ids, list) or not ids:
                raise FolderError(400, "invalid_ids", "ids must be a non-empty list")
            if len(ids) > MAX_FILING_IDS:
                raise FolderError(400, "invalid_ids", f"At most {MAX_FILING_IDS} ids at a time")
            with db_session() as conn:
                folder_id = data.get("folder_id")
                tree = None if folder_id else workspace_tree(current_workspace(conn))
                moved, skipped = file_items(conn, user, resource_type, folder_id, ids, tree=tree)
        except (FolderError, WorkspaceError) as err:
            return err.response()
        except Exception as err:
            return _server_error("Failed to move items", err)
        return make_response(jsonify({"success": True, "moved": moved, "skipped": skipped}), 200)
