"""
Shared utilities, database connections, and helper functions for user API routes.
"""

import datetime
import os
import uuid
from functools import wraps
from pathlib import PurePosixPath
from typing import Optional, Tuple

from flask import current_app, jsonify, make_response, Response
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

from sqlalchemy import text as _sql_text

from application.core.settings import settings
from application.storage.db.base_repository import looks_like_uuid, row_to_dict
from application.storage.db.repositories.users import UsersRepository
from application.storage.db.session import db_readonly, db_session
from application.storage.storage_creator import StorageCreator
from application.utils import (
    AGENT_IMAGE_FORMATS,
    get_agent_image_content_type,
    is_external_image_url,
    safe_user_storage_component,
)
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


def _validate_agent_image_upload(file, filename: str) -> None:
    """Validate an uploaded agent avatar and rewind it for storage.

    Args:
        file: Werkzeug file upload object.
        filename: Sanitized upload filename.

    Raises:
        OSError: If the upload stream cannot be inspected.
        ValueError: If the file exceeds a limit or is not an allowed raster image.
    """
    extension = PurePosixPath(filename).suffix.lower()
    image_policy = AGENT_IMAGE_FORMATS.get(extension)
    if not filename or image_policy is None:
        raise ValueError("Unsupported image extension")

    stream = file.stream
    stream.seek(0, os.SEEK_END)
    size_bytes = stream.tell()
    stream.seek(0)
    if size_bytes > settings.AGENT_IMAGE_MAX_BYTES:
        raise ValueError("Image exceeds the upload size limit")

    with Image.open(stream) as image:
        image_format = (image.format or "").upper()
        if image_format != image_policy[0]:
            raise ValueError("Image content does not match its extension")
        if image.width * image.height > settings.AGENT_IMAGE_MAX_PIXELS:
            raise ValueError("Image exceeds the pixel limit")
        image.verify()
    stream.seek(0)


def _safe_agent_image_filename(filename: str) -> str:
    """Build an ASCII storage filename without discarding a Unicode file's suffix.

    Args:
        filename: Original multipart upload filename.

    Returns:
        A traversal-safe filename with a normalized, allow-listed extension.

    Raises:
        ValueError: If the original filename has no supported image extension.
    """
    normalized_path = filename.replace("\\", "/")
    original_path = PurePosixPath(normalized_path)
    extension = original_path.suffix.lower()
    if extension not in AGENT_IMAGE_FORMATS:
        raise ValueError("Unsupported image extension")

    safe_stem = secure_filename(original_path.stem).strip("._") or "avatar"
    return f"{safe_stem}{extension}"


def copy_agent_image_for_user(image_path: object, user: str, storage) -> str:
    """Copy an internal agent avatar into ``user``'s own attachments directory.

    Avatar paths are validated against their owner's upload directory, so an
    agent copied to a new owner needs its own blob rather than a reference to
    the original owner's.

    Args:
        image_path: Source avatar storage path, or an external image URL.
        user: Identity that will own the copy.
        storage: Storage backend used for both the read and the write.

    Returns:
        The newly owned storage path, an unchanged external URL, or an empty
        string when the source is unusable.
    """
    if not isinstance(image_path, str) or not image_path:
        return ""
    if is_external_image_url(image_path):
        return image_path
    if get_agent_image_content_type(image_path) is None:
        return ""

    source_name = PurePosixPath(image_path).name
    prefix, separator, remainder = source_name.partition("_")
    if separator and remainder and looks_like_uuid(prefix):
        source_name = remainder
    try:
        filename = _safe_agent_image_filename(source_name)
    except ValueError:
        return ""

    owner_component = safe_user_storage_component(user)
    destination = (
        f"{settings.UPLOAD_FOLDER.rstrip('/')}/{owner_component}/"
        f"attachments/{uuid.uuid4()}_{filename}"
    )
    try:
        with storage.get_file(image_path) as source_file:
            storage.save_file(source_file, destination, storage_class="STANDARD")
    except Exception as e:
        current_app.logger.warning(
            "Could not copy agent image %s for %s: %s", image_path, user, e
        )
        return ""
    return destination


def handle_image_upload(
    request, existing_url: str, user: str, storage
) -> Tuple[Optional[str], Optional[Response]]:
    """
    Handle image file upload from request.

    Args:
        request: Flask request object
        existing_url: Existing image URL (fallback)
        user: User ID
        storage: Storage instance

    Returns:
        Tuple of (image_url, error_response)
    """
    image_url = existing_url

    if "image" in request.files:
        file = request.files["image"]
        if file.filename != "":
            try:
                filename = _safe_agent_image_filename(file.filename)
                _validate_agent_image_upload(file, filename)
            except (
                Image.DecompressionBombError,
                UnidentifiedImageError,
                ValueError,
                OSError,
            ) as e:
                current_app.logger.warning(f"Invalid agent image upload: {e}")
                return None, make_response(
                    jsonify({"success": False, "message": "Invalid image upload"}),
                    400,
                )

            owner_component = safe_user_storage_component(user)
            upload_path = (
                f"{settings.UPLOAD_FOLDER.rstrip('/')}/{owner_component}/"
                f"attachments/{uuid.uuid4()}_{filename}"
            )
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
