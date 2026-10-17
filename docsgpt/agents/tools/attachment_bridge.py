"""Lazily bridge a chat attachment into a conversation-scoped artifact when a tool references it.

A chat attachment lives in the ``attachments`` table (parsed to text for the LLM context); it is
not an artifact and so cannot be fed to ``code_executor`` / ``read_document`` directly. When one of
those tools references an attachment by its conversation ref (``F3``), id or filename, this module
materializes it into a conversation-scoped artifact on demand — only the conversation's own
(already user-scoped, owner re-checked) attachments are reachable, and an already-bridged attachment
is reused so repeated references never burn extra quota.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from docsgpt.agents.attachment_budget import assign_refs
from docsgpt.core.settings import settings
from docsgpt.sandbox.artifacts_capture import QuotaExceeded, persist_new_artifact
from docsgpt.storage.db.repositories.artifacts import ArtifactsRepository
from docsgpt.storage.db.repositories.attachments import AttachmentsRepository
from docsgpt.storage.db.session import db_readonly
from docsgpt.storage.storage_creator import StorageCreator

logger = logging.getLogger(__name__)


class AttachmentBridgeError(Exception):
    """Raised when a matched attachment cannot be bridged (e.g. quota, unreadable bytes)."""


# A conversation file ref as the manifest prints it: F1, F2, ...
_FILE_REF_RE = re.compile(r"^[Ff](\d+)$")


def _normalize_name(value: Any) -> str:
    """Lowercase + strip a filename for tolerant matching."""
    return str(value or "").strip().lower()


def match_attachment(
    attachments: Optional[List[Dict[str, Any]]], raw_ref: str, user_id: str
) -> Optional[Dict[str, Any]]:
    """Match a model-supplied ref/id/filename against the conversation's OWN attachments; None otherwise.

    ``attachments`` is the conversation's files in upload order (earlier turns first, then this
    turn's), already user-scoped when loaded, so a forged ref/id/name can never reach another user's
    or conversation's attachment. A ref ``F#`` resolves exactly as the turn's manifest numbers the
    files (``attachment_budget.assign_refs``). Every match is re-verified against
    ``AttachmentsRepository.get_any(id, user_id)`` so only the owner's row is ever bridged. When two
    attachments share a filename the latest upload is chosen; reference by ``F#`` to disambiguate.
    """
    if not attachments or not raw_ref:
        return None
    ref = raw_ref.strip()
    if not ref:
        return None
    rows = [a for a in attachments if isinstance(a, dict)]
    ref_match = _FILE_REF_RE.match(ref)
    if ref_match:
        wanted = f"F{int(ref_match.group(1))}"
        for planned in assign_refs(rows):
            if planned.ref == wanted:
                return _verify_owner(planned.attachment, user_id)
    ref_norm = _normalize_name(ref)
    by_filename: Optional[Dict[str, Any]] = None
    for attachment in rows:
        ids = {
            str(attachment.get(key))
            for key in ("id", "_id", "legacy_mongo_id")
            if attachment.get(key) is not None
        }
        if ref in ids:
            return _verify_owner(attachment, user_id)
        filename = attachment.get("filename")
        if filename and _normalize_name(filename) == ref_norm:
            by_filename = attachment
    if by_filename is not None:
        return _verify_owner(by_filename, user_id)
    return None


def format_bytes(size: int) -> str:
    """A byte count as the user reads it (``3.2 MB``)."""
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} bytes"


def too_large_message(attachment: Dict[str, Any], max_bytes: int, *, size: Optional[int] = None) -> str:
    """Explain that an attachment is over a byte cap, naming the file and both sizes.

    Args:
        attachment: The attachment row.
        max_bytes: The cap it exceeds.
        size: Its size, when known (defaults to the row's ``size``).

    Returns:
        The message.
    """
    name = attachment.get("filename") or "attachment"
    size = size if size is not None else attachment.get("size")
    if isinstance(size, (int, float)) and size > 0:
        return f"{name} is {format_bytes(int(size))}, over the {format_bytes(max_bytes)} limit"
    return f"{name} is over the {format_bytes(max_bytes)} limit"


def _verify_owner(attachment: Dict[str, Any], user_id: str) -> Optional[Dict[str, Any]]:
    """Re-confirm the attachment belongs to ``user_id`` via the user-scoped repo; in-memory dict on hit."""
    attachment_id = attachment.get("id") or attachment.get("_id") or attachment.get("legacy_mongo_id")
    if attachment_id is None:
        return None
    try:
        with db_readonly() as conn:
            owned = AttachmentsRepository(conn).get_any(str(attachment_id), user_id)
    except Exception:
        logger.exception("attachment_bridge: ownership re-check failed")
        return None
    # Prefer the DB row (authoritative upload_path/mime) but only when it confirms ownership.
    return owned if owned is not None else None


def bridge_attachment(
    attachment: Dict[str, Any], *, user_id: str, conversation_id: str, max_bytes: Optional[int] = None
) -> str:
    """Return the conversation artifact id for ``attachment``, reusing an existing bridge or creating one.

    Idempotent (best-effort): an artifact already derived from this attachment in this conversation
    (matched via its version ``produced_by.attachment_id``) is reused, so a second reference never
    consumes a new quota slot. The reuse is a read-then-write across transactions, so two concurrent
    references to the same not-yet-bridged attachment may each create one. Otherwise the attachment
    bytes are read server-side and persisted as a conversation-scoped ``file`` artifact (server-computed
    size/sha256/storage key).

    Args:
        attachment: The (owner-verified) attachment row.
        user_id: The owner.
        conversation_id: The conversation the artifact belongs to.
        max_bytes: The calling tool's own cap (``SANDBOX_MAX_INPUT_BYTES`` for the sandbox); the
            smaller of it and ``ARTIFACT_MAX_BYTES`` applies. A file over it is refused before
            anything is read or copied.

    Raises:
        AttachmentBridgeError: Over the cap, unreadable, or over the artifact quota.
    """
    attachment_id = str(attachment.get("id") or attachment.get("_id") or attachment.get("legacy_mongo_id"))
    caller_cap = int(max_bytes or 0)
    declared_size = attachment.get("size")
    if caller_cap and isinstance(declared_size, (int, float)) and declared_size > caller_cap:
        raise AttachmentBridgeError(f"{too_large_message(attachment, caller_cap)}.")
    try:
        with db_readonly() as conn:
            existing = ArtifactsRepository(conn).find_bridged_attachment(
                attachment_id, conversation_id=conversation_id
            )
    except Exception:
        logger.exception("attachment_bridge: idempotency lookup failed")
        existing = None
    if existing is not None:
        return str(existing["id"])

    upload_path = attachment.get("upload_path") or attachment.get("path")
    if not upload_path:
        raise AttachmentBridgeError(f"attachment {attachment_id} has no stored content.")
    filename = attachment.get("filename") or "attachment"
    mime_type = attachment.get("mime_type") or "application/octet-stream"
    # Reject oversize attachments BEFORE buffering them: the authoritative ``size``
    # column lets us avoid pulling a multi-hundred-MB file fully into worker memory,
    # and the bounded read below backstops a missing/lying ``size``.
    artifact_cap = int(settings.ARTIFACT_MAX_BYTES or 0)
    max_bytes = min(c for c in (artifact_cap, caller_cap) if c) if (artifact_cap or caller_cap) else 0
    if max_bytes and isinstance(declared_size, (int, float)) and declared_size > max_bytes:
        raise AttachmentBridgeError(
            f"attachment {attachment_id} exceeds the {max_bytes}-byte artifact size limit."
        )
    try:
        file_obj = StorageCreator.get_storage().get_file(upload_path)
        try:
            data = file_obj.read(max_bytes + 1) if max_bytes else file_obj.read()
        finally:
            close = getattr(file_obj, "close", None)
            if callable(close):
                close()
    except Exception as exc:
        logger.exception("attachment_bridge: failed to read attachment bytes")
        raise AttachmentBridgeError(f"failed to read attachment {attachment_id}.") from exc
    if max_bytes and len(data) > max_bytes:
        # The read stopped one byte past the cap, so the real size is unknown here.
        raise AttachmentBridgeError(f"{too_large_message({**attachment, 'size': None}, max_bytes)}.")
    try:
        ref = persist_new_artifact(
            user_id=user_id,
            kind="file",
            data=data,
            filename=filename,
            mime_type=mime_type,
            title=filename,
            conversation_id=conversation_id,
            produced_by={"attachment_id": attachment_id, "source": "chat_attachment"},
        )
    except QuotaExceeded as exc:
        raise AttachmentBridgeError(str(exc)) from exc
    if ref is None:
        raise AttachmentBridgeError(f"failed to bridge attachment {attachment_id}.")
    return str(ref["artifact_id"])
