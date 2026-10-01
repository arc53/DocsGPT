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
from docsgpt.storage.db.repositories.attachments import AttachmentsRepository, is_archive_row
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.storage.db.source_ids import derive_source_id
from docsgpt.storage.base import BaseStorage
from docsgpt.storage.storage_creator import StorageCreator
from docsgpt.upload_limits import upload_request_limit_message
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
            "WHERE id = ANY(CAST(:ids AS uuid[])) AND user_id = :user_id"
        ),
        {"ids": wanted, "user_id": user_id, "source_id": str(source_id)},
    )
    return result.rowcount


def _stored_bytes(storage: BaseStorage, rows: list[dict]) -> Optional[int]:
    """Total size of the rows' stored originals, or None when one is missing.

    Args:
        storage: The storage holding the originals.
        rows: Attachment rows with an ``upload_path``.

    Returns:
        The recorded ``size`` of each row, or its size in storage when none
        was recorded, summed; None when an original is gone or storage
        cannot be asked.
    """
    total = 0
    for row in rows:
        size = row.get("size")
        try:
            if size is None:
                size = storage.get_file_size(row["upload_path"])
            elif not storage.file_exists(row["upload_path"]):
                return None
        except Exception:
            return None
        total += int(size)
    return total


def _content_hash(row: dict) -> Optional[str]:
    """The sha256 of a row's original bytes, when it was recorded."""
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    value = row.get("content_hash") or metadata.get("content_hash")
    return str(value) if value else None


def _distinct_files(rows: list[dict]) -> list[dict]:
    """The rows with byte-identical originals kept once, first one wins.

    The same file attached twice (or re-sent by an API client) would
    otherwise be ingested twice and answer every search twice.

    Args:
        rows: Attachment rows, in composer order.

    Returns:
        The rows, without later rows whose ``content_hash`` was seen.
    """
    seen: set[str] = set()
    kept = []
    for row in rows:
        digest = _content_hash(row)
        if digest is not None:
            if digest in seen:
                continue
            seen.add(digest)
        kept.append(row)
    return kept


def _source_name(source_id: Optional[str], user: str) -> Optional[str]:
    """The stored name of a source, if its row exists yet."""
    if not source_id:
        return None
    try:
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        with db_readonly() as conn:
            row = SourcesRepository(conn).get_any(str(source_id), user)
    except Exception:
        return None
    return (row or {}).get("name") or None


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
            "ingested like an upload (a zip contributes its files); the files "
            "together may not exceed the upload request limit (413). Returns the "
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
        files = _distinct_files(
            [row for row in rows if not is_archive_row(row) and row.get("upload_path")]
        )
        if not files:
            return _error(400, "These attachments have no stored files to add")

        # The same ceiling as uploading these files in one request; the
        # ingest task copies them, so the request itself never reads them.
        storage = StorageCreator.get_storage()
        total = _stored_bytes(storage, files)
        if total is None:
            return _error(500, "An attached file is no longer stored")
        if total > int(settings.UPLOAD_MAX_REQUEST_BYTES):
            return _error(413, f"{upload_request_limit_message()}; add fewer files at a time")

        # Claimed only once the request is known to be valid, so a refused
        # request leaves the key free. A repeat gets the first one's ids.
        scoped_key = _scoped_idempotency_key(idempotency_key, user)
        predetermined_task_id = None
        job_name = name or default_source_name([row["filename"] for row in chips])
        if scoped_key:
            predetermined_task_id, cached = _claim_task_or_get_cached(scoped_key, "ingest")
            if cached is not None:
                # The same shape as the first response, name included.
                cached["name"] = _source_name(cached.get("source_id"), user) or job_name
                return make_response(jsonify(cached), 200)

        # With a key, the source id is derived from it as /api/upload does, so
        # a repeat (and a retried worker task) lands on the same source.
        source_uuid = derive_source_id(scoped_key) if scoped_key else uuid.uuid4()
        dir_name = f"{safe_filename(job_name)}-{source_uuid.hex[:8]}"
        base_path = f"{settings.UPLOAD_FOLDER}/{safe_filename(user)}/{dir_name}"
        file_name_map: dict[str, str] = {}
        copy_files: list[dict[str, str]] = []
        for row in files:
            stored_name = _unique_name(safe_filename(row["filename"]), set(file_name_map))
            file_name_map[stored_name] = row["filename"]
            copy_files.append({"from": row["upload_path"], "to": f"{base_path}/{stored_name}"})

        try:
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
                    "copy_files": copy_files,
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
            return _error(500, "Could not queue the new source")

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
