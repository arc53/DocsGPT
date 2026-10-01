"""Store the files a ``/v1`` request sends inline as the user's attachments.

A ``/v1`` client sends files as ``file`` / ``input_file`` parts and images as
``image_url`` / ``input_image`` data URLs, and re-sends all of them on every
turn and every tool round. Each distinct file becomes (or reuses) a row in
``attachments``, so the turn goes through the same attachment planner,
manifest and attachments tool as a web upload, and later turns see the file.

Bytes the user already sent are matched by ``content_hash`` and the parsed
row is reused as is: a client re-sending 19 PDFs every round costs one
lookup each. New bytes are stored like an upload and parsed by the worker's
``store_attachment`` task, which this request waits for (the same
dispatch-and-wait ``read_document`` uses). The API process never runs a
parser: OCR and docling need gigabytes and belong on the worker, and the
worker task already applies the size and zip limits and the parse reuse.

A zip's own task returns once it has unpacked and queued its members, so
a zip counts as parsed only when its row says every member has finished
(``metadata.archive.status``), within the same parse timeout. A file that
cannot be stored or parsed in time is left out of the mapping; its part
then stays in the request as the client sent it.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from werkzeug.datastructures import FileStorage

from docsgpt.api.v1.translator import InlineFile
from docsgpt.core.settings import settings
from docsgpt.parser.file.constants import is_attachment_archive
from docsgpt.utils import safe_filename

logger = logging.getLogger(__name__)

# How often a zip's row is checked while its members are parsed.
_ARCHIVE_POLL_SECONDS = 0.5


def _storage() -> Any:
    from docsgpt.storage.storage_creator import StorageCreator

    return StorageCreator.get_storage()


def _find_parsed(user: str, content_hash: str, *, archive: bool) -> Optional[Dict[str, Any]]:
    """The user's newest parsed row for these bytes: a finished zip for a zip, else a non-zip."""
    from docsgpt.storage.db.repositories.attachments import AttachmentsRepository
    from docsgpt.storage.db.session import db_readonly

    with db_readonly() as conn:
        return AttachmentsRepository(conn).find_by_hash(user, content_hash, archive=archive)


def _archive_status(user: str, attachment_id: str) -> Optional[str]:
    """A zip row's ``metadata.archive.status`` (``processing`` / ``complete``), if any."""
    from docsgpt.storage.db.repositories.attachments import AttachmentsRepository
    from docsgpt.storage.db.session import db_readonly

    with db_readonly() as conn:
        row = AttachmentsRepository(conn).get_by_legacy_id(attachment_id, user)
    archive = ((row or {}).get("metadata") or {}).get("archive")
    return archive.get("status") if isinstance(archive, dict) else None


def _wait_for_archive(user: str, attachment_id: str, deadline: float) -> bool:
    """Wait until every member of a zip has finished, or the deadline passes."""
    while True:
        if _archive_status(user, attachment_id) == "complete":
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(_ARCHIVE_POLL_SECONDS)


def _dispatch_parse(file_info: Dict[str, Any], user: str, timeout: float) -> Any:
    """Queue the worker's ``store_attachment`` task for one stored file."""
    from docsgpt.api.user.tasks import store_attachment

    return store_attachment.apply_async(args=[file_info, user])


def _parse_timeout(size: int) -> float:
    from docsgpt.api.user.tasks import parse_timeout_for_size

    return float(parse_timeout_for_size(size))


def _store_original(inline: InlineFile, user: str) -> Dict[str, Any]:
    """Save the bytes where an upload would go; return the task's file info.

    Raises:
        UnsupportedUploadTypeError: A binary file no parser reads.
    """
    from docsgpt.upload_limits import enforce_parseable_attachment

    attachment_id = str(uuid.uuid4())
    filename = safe_filename(inline.filename) or f"attachment-{attachment_id[:8]}"
    relative_path = f"{settings.UPLOAD_FOLDER}/{safe_filename(user)}/attachments/{attachment_id}/{filename}"
    with tempfile.TemporaryDirectory() as temp_dir:
        staged_path = os.path.join(temp_dir, filename)
        with open(staged_path, "wb") as handle:
            handle.write(inline.data)
        enforce_parseable_attachment(staged_path, filename)
        with open(staged_path, "rb") as stream:
            metadata = _storage().save_file(
                FileStorage(stream=stream, filename=filename, content_type=inline.mime_type),
                relative_path,
            )
    return {
        "filename": filename,
        "attachment_id": attachment_id,
        "path": relative_path,
        "metadata": metadata,
    }


def ingest_inline_files(files: List[InlineFile], user: str) -> Dict[str, str]:
    """Turn a request's inline files into attachment ids.

    Args:
        files: Distinct inline files, in request order.
        user: The owner of the rows (the agent's owner on ``/v1``).

    Returns:
        ``content_hash`` to attachment id, in request order, for every file
        that is now a parsed attachment.
    """
    converted: Dict[str, str] = {}
    pending: List[Tuple[InlineFile, str, Any, float]] = []
    limit = int(settings.UPLOAD_MAX_FILE_BYTES)
    for inline in files:
        if limit and len(inline.data) > limit:
            logger.warning("v1 file %s exceeds the upload limit; left in the request", inline.filename)
            continue
        try:
            row = _find_parsed(user, inline.content_hash, archive=is_attachment_archive(inline.filename))
        except Exception:
            logger.warning("Could not look up an earlier parse of %s", inline.filename, exc_info=True)
            row = None
        if row and row.get("id"):
            converted[inline.content_hash] = str(row["id"])
            continue
        try:
            file_info = _store_original(inline, user)
            timeout = _parse_timeout(len(inline.data))
            pending.append((inline, file_info["attachment_id"], _dispatch_parse(file_info, user, timeout), timeout))
        except Exception as exc:
            logger.warning("v1 file %s was not stored as an attachment: %s", inline.filename, exc)

    if pending:
        deadline = time.monotonic() + max(timeout for *_, timeout in pending)
        for inline, attachment_id, result, _ in pending:
            remaining = max(deadline - time.monotonic(), 1.0)
            try:
                result.get(timeout=remaining, disable_sync_subtasks=False)
            except Exception as exc:
                logger.warning("v1 file %s was not parsed: %s", inline.filename, exc)
                continue
            if is_attachment_archive(inline.filename):
                try:
                    finished = _wait_for_archive(user, attachment_id, deadline)
                except Exception:
                    logger.warning("Could not check zip %s", inline.filename, exc_info=True)
                    finished = False
                if not finished:
                    logger.warning("v1 zip %s was not unpacked in time", inline.filename)
                    continue
            converted[inline.content_hash] = attachment_id
    # Request order, whichever path each file took.
    order = {f.content_hash: i for i, f in enumerate(files)}
    return dict(sorted(converted.items(), key=lambda item: order.get(item[0], 0)))
