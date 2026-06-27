"""Lazily bridge a chat attachment into a conversation-scoped artifact when a tool references it.

A chat attachment lives in the ``attachments`` table (parsed to text for the LLM context); it is
not an artifact and so cannot be fed to ``code_executor`` / ``read_document`` directly. When one of
those tools references an attachment by id or filename, this module materializes it into a
conversation-scoped artifact on demand — only the request's own (already user-scoped) attachments are
reachable, and an already-bridged attachment is reused so repeated references never burn extra quota.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from application.sandbox.artifacts_capture import QuotaExceeded, persist_new_artifact
from application.storage.db.repositories.artifacts import ArtifactsRepository
from application.storage.db.repositories.attachments import AttachmentsRepository
from application.storage.db.session import db_readonly
from application.storage.storage_creator import StorageCreator

logger = logging.getLogger(__name__)


class AttachmentBridgeError(Exception):
    """Raised when a matched attachment cannot be bridged (e.g. quota, unreadable bytes)."""


def _normalize_name(value: Any) -> str:
    """Lowercase + strip a filename for tolerant matching."""
    return str(value or "").strip().lower()


def match_attachment(
    attachments: Optional[List[Dict[str, Any]]], raw_ref: str, user_id: str
) -> Optional[Dict[str, Any]]:
    """Match a model-supplied id/filename against the caller's OWN request attachments; None otherwise.

    Matching is confined to ``attachments`` (already user-scoped when loaded) so a forged id/name can
    never reach another user's or conversation's attachment. An id match is re-verified against
    ``AttachmentsRepository.get_any(id, user_id)`` so only the owner's row is ever bridged. When two
    attachments share a filename the first is chosen; reference by id to disambiguate.
    """
    if not attachments or not raw_ref:
        return None
    ref = raw_ref.strip()
    if not ref:
        return None
    ref_norm = _normalize_name(ref)
    by_filename: Optional[Dict[str, Any]] = None
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        ids = {
            str(attachment.get(key))
            for key in ("id", "_id", "legacy_mongo_id")
            if attachment.get(key) is not None
        }
        if ref in ids:
            return _verify_owner(attachment, user_id)
        filename = attachment.get("filename")
        if by_filename is None and filename and _normalize_name(filename) == ref_norm:
            by_filename = attachment
    if by_filename is not None:
        return _verify_owner(by_filename, user_id)
    return None


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
    attachment: Dict[str, Any], *, user_id: str, conversation_id: str
) -> str:
    """Return the conversation artifact id for ``attachment``, reusing an existing bridge or creating one.

    Idempotent (best-effort): an artifact already derived from this attachment in this conversation
    (matched via its version ``produced_by.attachment_id``) is reused, so a second reference never
    consumes a new quota slot. The reuse is a read-then-write across transactions, so two concurrent
    references to the same not-yet-bridged attachment may each create one. Otherwise the attachment
    bytes are read server-side and persisted as a conversation-scoped ``file`` artifact (server-computed
    size/sha256/storage key).
    """
    attachment_id = str(attachment.get("id") or attachment.get("_id") or attachment.get("legacy_mongo_id"))
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
    try:
        data = StorageCreator.get_storage().get_file(upload_path).read()
    except Exception as exc:
        logger.exception("attachment_bridge: failed to read attachment bytes")
        raise AttachmentBridgeError(f"failed to read attachment {attachment_id}.") from exc
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
