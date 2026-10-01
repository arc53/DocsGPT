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
cannot be stored or parsed in time is left out of the mapping, with the
reason, and the turn's manifest names it with that reason. A file known to
be unreadable (a damaged image, a type no parser reads, over the size
limit) is also removed from the request the model gets; any other file
left out (not stored, or not parsed in time) stays as the client sent it.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from werkzeug.datastructures import FileStorage

from docsgpt.api.v1.translator import InlineFile
from docsgpt.core.settings import settings
from docsgpt.error import bounded_error_text
from docsgpt.parser.file.constants import is_attachment_archive
from docsgpt.upload_limits import UnsupportedUploadTypeError
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


def _failure_code(user: str, attachment_id: str) -> Optional[str]:
    """The worker's rejection code on a failed parse's row (``image_unreadable``, say), if any."""
    from docsgpt.storage.db.repositories.attachments import AttachmentsRepository
    from docsgpt.storage.db.session import db_readonly

    with db_readonly() as conn:
        row = AttachmentsRepository(conn).get_by_legacy_id(attachment_id, user)
    extraction = ((row or {}).get("metadata") or {}).get("extraction")
    code = extraction.get("code") if isinstance(extraction, dict) else None
    return code if isinstance(code, str) else None


def _dispatch_parse(file_info: Dict[str, Any], user: str) -> Any:
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


# Why an inline file did not become an attachment, as the manifest names it.
TOO_LARGE = "too_large"
UNSUPPORTED = "unsupported"
NOT_STORED = "not_stored"
NOT_PARSED = "not_parsed"
IMAGE_UNREADABLE = "image_unreadable"

# The worker's rejection codes that say a file can never be read, as the
# manifest names them; any other failed parse is ``not_parsed``.
_REJECTION_REASONS = {
    "image_unreadable": IMAGE_UNREADABLE,
    "unsupported_type": UNSUPPORTED,
    "too_large": TOO_LARGE,
}


@dataclass
class InlineIngest:
    """A request's inline files on their way to becoming attachment rows.

    ``start_inline_files`` does the quick part (reuse by hash, store the
    new originals, queue their parses); ``wait`` waits for the parses. A
    streaming route waits inside its stream, behind SSE keepalives.

    Attributes:
        files: The inline files, in request order.
        user: The owner of the rows; a zip's row is read as this user.
        converted: ``content_hash`` to attachment id, for files done.
        skipped: ``content_hash`` to the reason a file was left out.
        pending: Parses still running: file, attachment id, task result,
            parse window in seconds.
    """

    files: List[InlineFile]
    user: str = ""
    converted: Dict[str, str] = field(default_factory=dict)
    skipped: Dict[str, str] = field(default_factory=dict)
    pending: List[Tuple[InlineFile, str, Any, float]] = field(default_factory=list)

    def wait(self) -> Dict[str, str]:
        """Wait for the queued parses, at most the longest parse window in all.

        A parse not done when the window closes is left out (``not_parsed``);
        the window is never overrun by waiting on each late result in turn.
        A zip's task returns once its members are queued, so a zip counts
        only when every member has finished within the same window.

        Returns:
            ``content_hash`` to attachment id, in request order.
        """
        if self.pending:
            deadline = time.monotonic() + max(timeout for *_, timeout in self.pending)
            zips: List[Tuple[InlineFile, str]] = []
            for inline, attachment_id, result, _ in self.pending:
                remaining = deadline - time.monotonic()
                try:
                    ready = getattr(result, "ready", None)
                    if remaining <= 0 and not (callable(ready) and ready()):
                        raise TimeoutError("the parse window closed")
                    result.get(timeout=max(remaining, 0.01), disable_sync_subtasks=False)
                except Exception as exc:
                    logger.warning("v1 file %s was not parsed: %s", inline.filename, bounded_error_text(exc))
                    self.skipped[inline.content_hash] = self._failure_reason(inline, attachment_id)
                    continue
                if is_attachment_archive(inline.filename):
                    zips.append((inline, attachment_id))
                    continue
                self.converted[inline.content_hash] = attachment_id
            # Zips last, so a zip still unpacking never eats a finished file's window.
            for inline, attachment_id in zips:
                if self._archive_finished(inline, attachment_id, deadline):
                    self.converted[inline.content_hash] = attachment_id
                else:
                    self.skipped[inline.content_hash] = NOT_PARSED
            self.pending = []
        order = {f.content_hash: i for i, f in enumerate(self.files)}
        self.converted = dict(sorted(self.converted.items(), key=lambda item: order.get(item[0], 0)))
        return self.converted

    def _failure_reason(self, inline: InlineFile, attachment_id: str) -> str:
        """Why a parse failed: the worker's rejection, else ``not_parsed`` (slow or failed)."""
        try:
            code = _failure_code(self.user, attachment_id)
        except Exception as exc:
            logger.warning("Could not read why %s failed: %s", inline.filename, bounded_error_text(exc))
            return NOT_PARSED
        return _REJECTION_REASONS.get(code or "", NOT_PARSED)

    def _archive_finished(self, inline: InlineFile, attachment_id: str, deadline: float) -> bool:
        """Whether every member of a queued zip finished before the deadline."""
        try:
            finished = _wait_for_archive(self.user, attachment_id, deadline)
        except Exception as exc:
            logger.warning("Could not check zip %s: %s", inline.filename, bounded_error_text(exc))
            return False
        if not finished:
            logger.warning("v1 zip %s was not unpacked in time", inline.filename)
        return finished


def start_inline_files(files: List[InlineFile], user: str) -> InlineIngest:
    """Reuse, store and queue a request's inline files, without waiting on a parse.

    Args:
        files: Distinct inline files, in request order.
        user: The owner of the rows (the agent's owner on ``/v1``).

    Returns:
        The ingest; ``wait`` it for the parses.
    """
    ingest = InlineIngest(files=list(files), user=user)
    limit = int(settings.UPLOAD_MAX_FILE_BYTES)
    for inline in files:
        if limit and len(inline.data) > limit:
            logger.warning("v1 file %s exceeds the upload limit; left in the request", inline.filename)
            ingest.skipped[inline.content_hash] = TOO_LARGE
            continue
        try:
            row = _find_parsed(user, inline.content_hash, archive=is_attachment_archive(inline.filename))
        except Exception as exc:
            logger.warning("Could not look up an earlier parse of %s: %s", inline.filename, bounded_error_text(exc))
            row = None
        if row and row.get("id"):
            ingest.converted[inline.content_hash] = str(row["id"])
            continue
        try:
            file_info = _store_original(inline, user)
            timeout = _parse_timeout(len(inline.data))
            ingest.pending.append((inline, file_info["attachment_id"], _dispatch_parse(file_info, user), timeout))
        except UnsupportedUploadTypeError as exc:
            logger.warning("v1 file %s has no parser: %s", inline.filename, bounded_error_text(exc))
            ingest.skipped[inline.content_hash] = UNSUPPORTED
        except Exception as exc:
            logger.warning("v1 file %s was not stored as an attachment: %s", inline.filename, bounded_error_text(exc))
            ingest.skipped[inline.content_hash] = NOT_STORED
    return ingest


def ingest_inline_files(
    files: List[InlineFile], user: str, skipped: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    """Turn a request's inline files into attachment ids, waiting for their parses.

    Args:
        files: Distinct inline files, in request order.
        user: The owner of the rows (the agent's owner on ``/v1``).
        skipped: Filled with ``content_hash`` to the reason a file was left
            out (``too_large``, ``unsupported``, ``image_unreadable``,
            ``not_stored``, ``not_parsed``).

    Returns:
        ``content_hash`` to attachment id, in request order, for every file
        that is now a parsed attachment.
    """
    ingest = start_inline_files(files, user)
    converted = ingest.wait()
    if skipped is not None:
        skipped.update(ingest.skipped)
    return converted
