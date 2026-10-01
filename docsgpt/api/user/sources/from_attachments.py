"""Turn files attached to a chat into a Knowledge source.

A turn's attachments that are too large for the model to read at once are
better searched than inlined. This route makes a Knowledge source of them
from the originals already in storage, so nothing is uploaded twice, and
runs it through the same ingest as an upload.
"""

import os
import uuid
from typing import Optional

from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Resource
from sqlalchemy import Connection, text

from docsgpt.api import api
from docsgpt.api.user.sources.upload import (
    _audit_source_created,
    _claim_task_or_get_cached,
    _read_idempotency_key,
    _release_claim,
    _scoped_idempotency_key,
    sources_upload_ns,
)
from docsgpt.api.user.tasks import ingest
from docsgpt.core.settings import settings
from docsgpt.parser.file.constants import SUPPORTED_SOURCE_EXTENSIONS
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.attachments import AttachmentsRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.storage.db.source_ids import derive_source_id
from docsgpt.storage.storage_creator import StorageCreator
from docsgpt.utils import safe_filename


# One request names the composer's chips; a zip among them brings its members.
MAX_ATTACHMENT_IDS = 500
_MAX_NAME_CHARS = 255


def default_source_name(filenames: list[str]) -> str:
    """Name a source after the files it was made from.

    Args:
        filenames: Display names of the attachments, in composer order.

    Returns:
        The first name, plus how many more there are when there are several
        (``report.pdf and 4 more``).
    """
    first = filenames[0]
    rest = len(filenames) - 1
    return f"{first} and {rest} more" if rest > 0 else first


def _is_archive(row: dict) -> bool:
    """Whether a row is a zip index whose members are rows of their own."""
    metadata = row.get("metadata")
    return isinstance(metadata, dict) and isinstance(metadata.get("archive"), dict)


def _unique_name(name: str, taken: set[str]) -> str:
    """Return ``name``, or ``name-2.ext`` and so on when it is already used."""
    if name not in taken:
        return name
    stem, ext = os.path.splitext(name)
    counter = 2
    while f"{stem}-{counter}{ext}" in taken:
        counter += 1
    return f"{stem}-{counter}{ext}"


def link_attachments_to_source(conn: Connection, ids: list[str], user_id: str, source_id: str) -> int:
    """Record on each attachment the Knowledge source made from it.

    Merges ``metadata.knowledge_source_id`` in place, so the rest of the
    metadata (archive index, extraction status) is kept.

    Args:
        conn: An open connection in a write transaction.
        ids: PG ``attachments.id`` values.
        user_id: The owner; other users' rows are left alone.
        source_id: The new source's id.

    Returns:
        The number of rows updated.
    """
    wanted = [str(i) for i in ids if i is not None and looks_like_uuid(str(i))]
    if not wanted:
        return 0
    result = conn.execute(
        text(
            "UPDATE attachments SET metadata = COALESCE(metadata, '{}'::jsonb) "
            "|| jsonb_build_object('knowledge_source_id', CAST(:source_id AS text)) "
            "WHERE id::text = ANY(:ids) AND user_id = :user_id"
        ),
        {"ids": wanted, "user_id": user_id, "source_id": str(source_id)},
    )
    return result.rowcount


def _error(status: int, message: str):
    return make_response(jsonify({"success": False, "message": message}), status)


def _read_request() -> tuple[Optional[list[str]], Optional[str], Optional[object]]:
    """Return ``(attachment_ids, name, error_response)`` from the JSON body."""
    body = request.get_json(silent=True) or {}
    ids = body.get("attachment_ids")
    if (
        not isinstance(ids, list)
        or not ids
        or len(ids) > MAX_ATTACHMENT_IDS
        or not all(isinstance(i, str) and i.strip() for i in ids)
    ):
        return None, None, _error(
            400, f"attachment_ids must be a list of 1 to {MAX_ATTACHMENT_IDS} ids"
        )
    name = body.get("name")
    name = name.strip()[:_MAX_NAME_CHARS] if isinstance(name, str) else ""
    return list(dict.fromkeys(i.strip() for i in ids)), name or None, None


@sources_upload_ns.route("/sources/from_attachments")
class SourceFromAttachments(Resource):
    @api.expect(
        api.model(
            "SourceFromAttachmentsModel",
            {
                "attachment_ids": fields.List(
                    fields.String,
                    required=True,
                    description="Ids of the caller's chat attachments, in the order to list them",
                ),
                "name": fields.String(
                    required=False,
                    description="Name of the new source; defaults to the first file's name and a count",
                ),
            },
        )
    )
    @api.doc(
        description=(
            "Creates a Knowledge source from chat attachments the caller already "
            "uploaded. The stored originals are copied into a new source and "
            "ingested like an upload (a zip contributes its files). Returns the "
            "source id and the ingest task id; progress arrives as "
            "``source.ingest.*`` events for that source id. Honors an optional "
            "``Idempotency-Key`` header: a repeat request with the same key "
            "within 24h returns the first request's source and task ids "
            "without copying the files or queueing a second ingest."
        ),
    )
    def post(self):
        decoded_token = getattr(request, "decoded_token", None)
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        idempotency_key, key_error = _read_idempotency_key()
        if key_error is not None:
            return key_error

        ids, name, error = _read_request()
        if error is not None:
            return error

        with db_readonly() as conn:
            repo = AttachmentsRepository(conn)
            resolved = repo.resolve_ids(ids)
            wanted = [resolved[i] for i in ids if i in resolved]
            rows = repo.list_for_planning(wanted, user) if len(wanted) == len(ids) else []
        found = {str(row["id"]) for row in rows}
        if not wanted or len(wanted) != len(ids) or not set(wanted) <= found:
            return _error(404, "Attachment not found")

        chips = [row for row in rows if str(row["id"]) in set(wanted)]
        files = [row for row in rows if not _is_archive(row) and row.get("upload_path")]
        if not files:
            return _error(400, "These attachments have no stored files to add")

        # Claimed only once the request is known to be valid, so a refused
        # request leaves the key free. A repeat gets the first one's ids.
        scoped_key = _scoped_idempotency_key(idempotency_key, user)
        predetermined_task_id = None
        if scoped_key:
            predetermined_task_id, cached = _claim_task_or_get_cached(scoped_key, "ingest")
            if cached is not None:
                return make_response(jsonify(cached), 200)

        job_name = name or default_source_name([row["filename"] for row in chips])
        # With a key, the source id is derived from it as /api/upload does, so
        # a repeat (and a retried worker task) lands on the same source.
        source_uuid = derive_source_id(scoped_key) if scoped_key else uuid.uuid4()
        dir_name = f"{safe_filename(job_name)}-{source_uuid.hex[:8]}"
        base_path = f"{settings.UPLOAD_FOLDER}/{safe_filename(user)}/{dir_name}"
        file_name_map: dict[str, str] = {}

        storage = StorageCreator.get_storage()
        try:
            for row in files:
                stored_name = _unique_name(safe_filename(row["filename"]), set(file_name_map))
                file_name_map[stored_name] = row["filename"]
                original = storage.get_file(row["upload_path"])
                try:
                    storage.save_file(original, f"{base_path}/{stored_name}")
                finally:
                    original.close()
            ingest_kwargs: dict = {
                "args": (
                    settings.UPLOAD_FOLDER,
                    list(SUPPORTED_SOURCE_EXTENSIONS),
                    job_name,
                    user,
                ),
                "kwargs": {
                    "file_path": base_path,
                    "filename": dir_name,
                    "file_name_map": file_name_map,
                    "config": None,
                    # Scoped, so the worker's dedup row is the one claimed here.
                    "idempotency_key": scoped_key,
                    "source_id": str(source_uuid),
                },
            }
            if predetermined_task_id is not None:
                ingest_kwargs["task_id"] = predetermined_task_id
            task = ingest.apply_async(**ingest_kwargs)
        except Exception as err:
            current_app.logger.error(
                "Could not make a source from attachments: %s", err, exc_info=True
            )
            if scoped_key:
                _release_claim(scoped_key)
            try:
                storage.remove_directory(base_path)
            except Exception:
                current_app.logger.warning("Could not clean up %s", base_path, exc_info=True)
            return _error(500, "Could not copy the attached files")

        task_id = predetermined_task_id or task.id
        _audit_source_created(
            source_id=str(source_uuid),
            user=user,
            name=job_name,
            source_type="local",
            task_id=task_id,
        )
        try:
            with db_session() as conn:
                link_attachments_to_source(
                    conn, [str(row["id"]) for row in rows], user, str(source_uuid)
                )
        except Exception as err:
            # The source is queued either way; the link only records where the
            # files went.
            current_app.logger.warning(
                "Could not link attachments to source %s: %s", source_uuid, err, exc_info=True
            )

        return make_response(
            jsonify(
                {
                    "success": True,
                    "task_id": task_id,
                    "source_id": str(source_uuid),
                    "name": job_name,
                }
            ),
            200,
        )
