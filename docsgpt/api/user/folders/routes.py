"""``/api/folders``: one folder system for agents and knowledge (sources).

Folders are personal filing. Each user keeps their own folders of each type
and files any agent or source they can see into them, one folder per item.
The rules live in :mod:`docsgpt.api.user.folders.service`; a token needs the
scope of the type's family (``agents:*`` or ``sources:*``).
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
    folder_error,
    list_folders,
    parse_resource_type,
    resolve_folder,
    serialize_folder,
    update_folder,
)
from docsgpt.api.user.resource_usage import empty_usage, used_by_many
from docsgpt.storage.db.session import db_readonly, db_session

folders_ns = Namespace("folders", description="Folders for agents and knowledge", path="/api")

#: The token scope family of each folder type.
TYPE_FAMILY = {"agent": "agents", "source": "sources"}

_FOLDER_MODEL = api.model(
    "Folder",
    {
        "id": fields.String(description="Folder id"),
        "name": fields.String(description="Folder name"),
        "parent_id": fields.String(description="Parent folder id; null at the top level"),
        "type": fields.String(description="agent or source"),
        "created_at": fields.String(description="ISO timestamp"),
        "updated_at": fields.String(description="ISO timestamp"),
        "item_count": fields.Integer(description="Items filed directly in it that the caller can see"),
        "folder_count": fields.Integer(description="Folders directly in it"),
        "used_by": fields.Raw(
            description="Source folders only: {agents: [{id, name, agent_type, can_edit, status}], others} "
            "reading it live"
        ),
    },
)


def _user() -> Optional[str]:
    decoded = getattr(request, "decoded_token", None)
    return decoded.get("sub") if decoded else None


def _unauthorized() -> Response:
    return make_response(jsonify({"success": False, "message": "Unauthorized"}), 401)


def _scope_refusal(resource_type: str, write: bool) -> Optional[Response]:
    """A token's 403 when it lacks the read/write scope of the folder type's family."""
    refusal = missing_scope_response(request, f"{TYPE_FAMILY[resource_type]}:{'write' if write else 'read'}")
    return make_response(jsonify(refusal[0]), refusal[1]) if refusal else None


def _body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise FolderError(400, "invalid_body", "A JSON object is required")
    return body


def _server_error(message: str, err: Exception) -> Response:
    current_app.logger.error(f"{message}: {err}", exc_info=True)
    return folder_error(500, "server_error", message)


def _with_counts(folder: dict) -> dict:
    out = {**serialize_folder(folder), "item_count": 0, "folder_count": 0}
    if out["type"] == "source":
        out["used_by"] = empty_usage()
    return out


@folders_ns.route("/folders")
class Folders(Resource):
    @api.doc(
        description=(
            "The caller's folders of one type, oldest first: {folders: [Folder]}. item_count and folder_count "
            "count direct children; used_by (source folders) names the agents reading the folder live."
        ),
        params={"type": "agent or source (required)"},
    )
    def get(self):
        user = _user()
        if not user:
            return _unauthorized()
        try:
            resource_type = parse_resource_type(request.args.get("type"))
        except FolderError as err:
            return err.response()
        if (refusal := _scope_refusal(resource_type, write=False)) is not None:
            return refusal
        try:
            with db_readonly() as conn:
                folders = list_folders(conn, user, resource_type)
                if resource_type == "source" and folders:
                    ids = [f["id"] for f in folders]
                    usage = used_by_many(
                        conn, user, "folder", ids, deletable_ids=ids, agent_allowlist=used_by_agent_allowlist(request),
                    )
                    for folder in folders:
                        folder["used_by"] = usage.get(folder["id"]) or empty_usage()
        except Exception as err:
            return _server_error("Failed to fetch folders", err)
        return make_response(jsonify({"folders": folders}), 200)

    @api.doc(
        description=(
            "Create a folder: {type, name, parent_id?}. Names are trimmed, 1-80 characters, unique among "
            "siblings ignoring case (409 folder_name_taken); folders nest 3 levels deep (400 folder_too_deep). "
            "Answers 201 with the Folder."
        )
    )
    @api.response(201, "The new folder", _FOLDER_MODEL)
    @api.expect(
        api.model(
            "CreateFolderRequest",
            {
                "type": fields.String(required=True, description="agent or source"),
                "name": fields.String(required=True, description="Folder name"),
                "parent_id": fields.String(required=False, description="Parent folder id"),
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
            with db_session() as conn:
                folder = create_folder(conn, user, resource_type, data.get("name"), data.get("parent_id"))
        except FolderError as err:
            return err.response()
        except Exception as err:
            return _server_error("Failed to create folder", err)
        return make_response(jsonify(_with_counts(folder)), 201)


@folders_ns.route("/folders/<string:folder_id>")
class FolderResource(Resource):
    @api.doc(
        description=(
            "Rename or move a folder: {name?, parent_id?}; parent_id null moves it to the top level. "
            "Errors: 404 folder_not_found, 400 folder_cycle / folder_too_deep, 409 folder_name_taken."
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
        try:
            data = _body()
            with db_session() as conn:
                folder = resolve_folder(conn, folder_id, user)
                if (refusal := _scope_refusal(folder.get("resource_type") or "agent", write=True)) is not None:
                    return refusal
                kwargs = {key: data[key] for key in ("name", "parent_id") if key in data}
                folder = update_folder(conn, user, folder, **kwargs)
        except FolderError as err:
            return err.response()
        except Exception as err:
            return _server_error("Failed to update folder", err)
        return make_response(jsonify(serialize_folder(folder)), 200)

    @api.doc(
        description=(
            "Delete a folder. Its folders and items move to its parent (the top level and unfiled when it "
            "had none); agents reading it live lose it. Answers {success, moved_items, moved_folders}."
        )
    )
    def delete(self, folder_id: str):
        user = _user()
        if not user:
            return _unauthorized()
        try:
            with db_session() as conn:
                folder = resolve_folder(conn, folder_id, user)
                if (refusal := _scope_refusal(folder.get("resource_type") or "agent", write=True)) is not None:
                    return refusal
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
            "File items into one of the caller's folders: {type, folder_id, ids}; folder_id null unfiles them. "
            "Any agent or source the caller can see can be filed, into their own folder of its type. "
            "Answers {success, moved: [ids], skipped: [ids the caller can't see]}."
        )
    )
    @api.expect(
        api.model(
            "FileFolderItemsRequest",
            {
                "type": fields.String(required=True, description="agent or source"),
                "folder_id": fields.String(required=False, description="Target folder id, or null to unfile"),
                "ids": fields.List(fields.String, required=True, description="Agent or source ids"),
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
                moved, skipped = file_items(conn, user, resource_type, data.get("folder_id"), ids)
        except FolderError as err:
            return err.response()
        except Exception as err:
            return _server_error("Failed to move items", err)
        return make_response(jsonify({"success": True, "moved": moved, "skipped": skipped}), 200)
