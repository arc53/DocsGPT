"""
Shared utilities, database connections, and helper functions for user API routes.
"""

import datetime
import os
import uuid
from functools import wraps
from typing import Optional, Tuple

from flask import current_app, jsonify, make_response, Response
from werkzeug.utils import secure_filename

from sqlalchemy import text as _sql_text

from application.core.settings import settings
from application.storage.db.base_repository import looks_like_uuid, row_to_dict
from application.storage.db.repositories.users import UsersRepository
from application.storage.db.session import db_readonly, db_session
from application.storage.storage_creator import StorageCreator
from application.vectorstore.vector_creator import VectorCreator


storage = StorageCreator.get_storage()


current_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def generate_minute_range(start_date, end_date):
    """Generate a dictionary with minute-level time ranges."""
    return {
        (start_date + datetime.timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:00"): 0
        for i in range(int((end_date - start_date).total_seconds() // 60) + 1)
    }


def generate_hourly_range(start_date, end_date):
    """Generate a dictionary with hourly time ranges."""
    return {
        (start_date + datetime.timedelta(hours=i)).strftime("%Y-%m-%d %H:00"): 0
        for i in range(int((end_date - start_date).total_seconds() // 3600) + 1)
    }


def generate_date_range(start_date, end_date):
    """Generate a dictionary with daily date ranges."""
    return {
        (start_date + datetime.timedelta(days=i)).strftime("%Y-%m-%d"): 0
        for i in range((end_date - start_date).days + 1)
    }


def ensure_user_doc(user_id):
    """
    Ensure a Postgres ``users`` row exists for ``user_id``.

    Returns the row as a dict with the shape legacy callers expect — in
    particular ``user_id`` and ``agent_preferences`` (with ``pinned`` and
    ``shared_with_me`` list keys always present).

    Args:
        user_id: The user ID to ensure

    Returns:
        The user document as a dict.
    """
    with db_session() as conn:
        user_doc = UsersRepository(conn).upsert(user_id)

    prefs = user_doc.get("agent_preferences") or {}
    if not isinstance(prefs, dict):
        prefs = {}
    prefs.setdefault("pinned", [])
    prefs.setdefault("shared_with_me", [])
    user_doc["agent_preferences"] = prefs
    return user_doc


def resolve_tool_details(tool_ids):
    """
    Resolve tool IDs to their display details.

    Accepts Postgres UUIDs, legacy Mongo ObjectId strings, or the
    synthetic ids of default chat tools / agent-selectable builtins
    (mixed lists are supported). Synthetic ids are resolved in memory;
    real ids are looked up via ``get_any``. Unknown ids are silently
    skipped.

    Args:
        tool_ids: List of tool IDs (UUIDs, legacy ObjectId strings, or
            synthetic default-tool / builtin ids).

    Returns:
        List of tool details with ``id``, ``name``, and ``display_name``.
    """
    if not tool_ids:
        return []

    from application.agents.default_tools import (
        is_synthesized_tool_id,
        synthesize_tool_by_name,
        synthesized_tool_name_for_id,
    )

    uuid_ids: list[str] = []
    legacy_ids: list[str] = []
    default_details: list[dict] = []
    for tid in tool_ids:
        if not tid:
            continue
        tid_str = str(tid)
        if is_synthesized_tool_id(tid_str):
            synth = synthesize_tool_by_name(synthesized_tool_name_for_id(tid_str))
            if synth is not None:
                default_details.append(
                    {
                        "id": tid_str,
                        "name": synth.get("name", ""),
                        "display_name": synth.get("display_name", ""),
                    }
                )
            continue
        if looks_like_uuid(tid_str):
            uuid_ids.append(tid_str)
        else:
            legacy_ids.append(tid_str)

    if not uuid_ids and not legacy_ids:
        return default_details

    rows: list[dict] = []
    with db_readonly() as conn:
        if uuid_ids:
            result = conn.execute(
                _sql_text(
                    "SELECT * FROM user_tools "
                    "WHERE id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": uuid_ids},
            )
            rows.extend(row_to_dict(r) for r in result.fetchall())
        if legacy_ids:
            result = conn.execute(
                _sql_text(
                    "SELECT * FROM user_tools "
                    "WHERE legacy_mongo_id = ANY(:ids)"
                ),
                {"ids": legacy_ids},
            )
            rows.extend(row_to_dict(r) for r in result.fetchall())

    return default_details + [
        {
            "id": str(tool.get("id") or tool.get("legacy_mongo_id") or ""),
            "name": tool.get("name", "") or "",
            "display_name": (
                tool.get("custom_name")
                or tool.get("display_name")
                or tool.get("name", "")
                or ""
            ),
        }
        for tool in rows
    ]


_BUILTIN_PROMPT_NAMES = {
    "default": "Default",
    "creative": "Creative",
    "strict": "Strict",
}


def resolve_prompt_name(prompt_id) -> Optional[str]:
    """Resolve a prompt id to its display name by id (owner-agnostic).

    Mirrors ``resolve_tool_details``: looks the prompt up by id without user
    scoping, so a team member viewing a shared agent sees the OWNER's prompt
    name rather than nothing. Built-in prompt sentinels map to friendly labels.
    Returns None when the prompt is missing/unknown.
    """
    if not prompt_id:
        return None
    pid = str(prompt_id)
    if pid in _BUILTIN_PROMPT_NAMES:
        return _BUILTIN_PROMPT_NAMES[pid]
    if not looks_like_uuid(pid):
        return None
    with db_readonly() as conn:
        result = conn.execute(
            _sql_text("SELECT name FROM prompts WHERE id = CAST(:id AS uuid)"),
            {"id": pid},
        )
        row = result.fetchone()
    return row[0] if row is not None else None


def resolve_source_details(source_ids) -> list[dict]:
    """Resolve source ids to ``[{"id", "name"}]`` by id (owner-agnostic).

    Order-preserving; an id with no matching source row yields ``name: None`` so
    the client can fall back. Lets a team member viewing a shared agent see the
    owner's source names instead of a raw id / "External KB".
    """
    ids = [str(s) for s in (source_ids or []) if s and looks_like_uuid(str(s))]
    if not ids:
        return []
    with db_readonly() as conn:
        result = conn.execute(
            _sql_text(
                "SELECT id, name FROM sources WHERE id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": ids},
        )
        by_id = {str(r[0]): r[1] for r in result.fetchall()}
    return [{"id": sid, "name": by_id.get(sid)} for sid in ids]


def get_vector_store(source_id):
    """
    Get the Vector Store for a given source ID.

    Args:
        source_id (str): source id of the document

    Returns:
        Vector store instance
    """
    store = VectorCreator.create_vectorstore(
        settings.VECTOR_STORE,
        source_id=source_id,
        embeddings_key=os.getenv("EMBEDDINGS_KEY"),
    )
    return store


def handle_image_upload(
    request, existing_url: str, user: str, storage, base_path: str = "attachments/"
) -> Tuple[str, Optional[Response]]:
    """
    Handle image file upload from request.

    Args:
        request: Flask request object
        existing_url: Existing image URL (fallback)
        user: User ID
        storage: Storage instance
        base_path: Base path for upload

    Returns:
        Tuple of (image_url, error_response)
    """
    image_url = existing_url

    if "image" in request.files:
        file = request.files["image"]
        if file.filename != "":
            filename = secure_filename(file.filename)
            upload_path = f"{settings.UPLOAD_FOLDER.rstrip('/')}/{user}/{base_path.rstrip('/')}/{uuid.uuid4()}_{filename}"
            try:
                storage.save_file(file, upload_path, storage_class="STANDARD")
                image_url = upload_path
            except Exception as e:
                current_app.logger.error(f"Error uploading image: {e}")
                return None, make_response(
                    jsonify({"success": False, "message": "Image upload failed"}),
                    400,
                )
    return image_url, None


def require_agent(func):
    """
    Decorator to require valid agent webhook token.

    Args:
        func: Function to decorate

    Returns:
        Wrapped function
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        from application.storage.db.repositories.agents import AgentsRepository

        webhook_token = kwargs.get("webhook_token")
        if not webhook_token:
            return make_response(
                jsonify({"success": False, "message": "Webhook token missing"}), 400
            )
        with db_readonly() as conn:
            agent = AgentsRepository(conn).find_by_webhook_token(webhook_token)
        if not agent:
            current_app.logger.warning(
                f"Webhook attempt with invalid token: {webhook_token}"
            )
            return make_response(
                jsonify({"success": False, "message": "Agent not found"}), 404
            )
        kwargs["agent"] = agent
        kwargs["agent_id_str"] = str(agent["id"])
        return func(*args, **kwargs)

    return wrapper
