"""The whole extracted text of an attachment whose stored text was cut.

An attachment's ``content`` column holds at most ``ATTACHMENT_MAX_TOKENS`` of
its text: it is what the planner inlines. When the parser extracted more, the
worker keeps the whole text (up to ``ATTACHMENT_FULL_TEXT_MAX_BYTES``) in
object storage next to the original, as ``<original path>.extracted.txt``,
and records it in ``metadata.extraction``:

* ``full_text_path``: where the side copy is;
* ``full_text_tokens``: its size in tokens;
* ``full_text_bytes``: its size in bytes;
* ``full_text_cut``: present (True) when the side copy itself was capped.

The attachments tool reads and searches that copy, so the tail of a long
document is reachable. Nothing else reads it, and a missing or unreadable
copy only means the tool falls back to the stored text. A copy whose
recorded size is unknown or over the current cap is never offered: the
planner tells the model it can read past the cut only for a copy the tool
would load.
"""

from __future__ import annotations

import io
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

FULL_TEXT_SUFFIX = ".extracted.txt"


def full_text_path_for(original_path: str) -> str:
    """Storage path of the side copy for an attachment stored at ``original_path``."""
    return f"{original_path}{FULL_TEXT_SUFFIX}"


def _max_bytes() -> int:
    from docsgpt.core.settings import settings

    return max(int(getattr(settings, "ATTACHMENT_FULL_TEXT_MAX_BYTES", 0) or 0), 0)


def store_full_text(
    storage: Any, original_path: str, text: str, encoding: Any, token_count: int
) -> Dict[str, Any]:
    """Save the whole extracted text beside the original file.

    Never raises: the upload must not fail because its side copy could not
    be written; the attachment then reads as it always did, cut.

    Args:
        storage: The storage backend holding the original.
        original_path: Storage path of the uploaded file.
        text: The whole extracted text.
        encoding: The tokenizer the stored cut was made with.
        token_count: Tokens of ``text``; recounted only when the copy is capped.

    Returns:
        The ``extraction`` keys to record, or an empty dict when no copy was kept.
    """
    cap = _max_bytes()
    if cap <= 0 or not text:
        return {}
    data = text.encode("utf-8")
    cut = len(data) > cap
    if cut:
        data = data[:cap]
        text = data.decode("utf-8", errors="ignore")
        data = text.encode("utf-8")
    path = full_text_path_for(original_path)
    try:
        storage.save_file(io.BytesIO(data), path)
    except Exception as exc:
        logger.warning("Could not keep the full text of %s: %s", original_path, exc)
        return {}
    info: Dict[str, Any] = {
        "full_text_path": path,
        "full_text_tokens": len(encoding.encode_ordinary(text)) if cut else int(token_count),
        "full_text_bytes": len(data),
    }
    if cut:
        info["full_text_cut"] = True
    return info


def copy_full_text(storage: Any, extraction: Dict[str, Any], original_path: str) -> Dict[str, Any]:
    """Give a reused parse its own side copy, next to its own original.

    Args:
        storage: The storage backend.
        extraction: The earlier row's ``extraction`` record.
        original_path: Storage path of the new upload.

    Returns:
        ``extraction`` with the side-copy keys pointing at the new copy, or
        without them when there was none or it could not be copied.
    """
    source = extraction.get("full_text_path")
    kept = {k: v for k, v in extraction.items() if not k.startswith("full_text_")}
    if not source:
        return kept
    path = full_text_path_for(original_path)
    try:
        handle = storage.get_file(source)
        try:
            data = handle.read(_max_bytes() + 1)
        finally:
            close = getattr(handle, "close", None)
            if callable(close):
                close()
        if not data or len(data) > _max_bytes():
            return kept
        storage.save_file(io.BytesIO(data), path)
    except Exception as exc:
        logger.warning("Could not copy the full text of %s: %s", source, exc)
        return kept
    copied = {k: v for k, v in extraction.items() if k.startswith("full_text_")}
    return {**kept, **copied, "full_text_path": path, "full_text_bytes": len(data)}


def full_text_location(row: Dict[str, Any]) -> Optional[str]:
    """Where a row's side copy is, when it has a trustworthy, loadable one.

    Only a copy the worker wrote for this very row is accepted: one beside
    the row's original file, named after it, whose recorded size is within
    the current ``ATTACHMENT_FULL_TEXT_MAX_BYTES``. Checking the recorded
    size, not the object, keeps this free of storage calls; an object gone
    since it was written still falls back to the stored text when read.

    Args:
        row: An attachment row.

    Returns:
        The storage path, or None.
    """
    metadata = row.get("metadata")
    extraction = metadata.get("extraction") if isinstance(metadata, dict) else None
    if not isinstance(extraction, dict) or not extraction.get("truncated"):
        return None
    path = extraction.get("full_text_path")
    original = row.get("upload_path") or row.get("path")
    if not isinstance(path, str) or not path.endswith(FULL_TEXT_SUFFIX) or not original:
        return None
    if os.path.dirname(path) != os.path.dirname(str(original)):
        return None
    if not 0 < _recorded_bytes(extraction) <= _max_bytes():
        return None
    return path


def _recorded_bytes(extraction: Dict[str, Any]) -> int:
    """The side copy's recorded size in bytes; 0 when it is missing or unusable."""
    try:
        return max(int(extraction.get("full_text_bytes") or 0), 0)
    except (TypeError, ValueError):
        return 0


def full_text_tokens(row: Dict[str, Any]) -> Optional[int]:
    """Tokens of a row's side copy, when it has one."""
    if full_text_location(row) is None:
        return None
    extraction = row["metadata"]["extraction"]
    try:
        tokens = int(extraction.get("full_text_tokens") or 0)
    except (TypeError, ValueError):
        return None
    return tokens if tokens > 0 else None


def load_full_text(storage: Any, path: str) -> Optional[str]:
    """Read a side copy, refusing one larger than the configured cap.

    Args:
        storage: The storage backend.
        path: The side copy's storage path.

    Returns:
        The text, or None when it is missing, too large or unreadable.
    """
    cap = _max_bytes()
    if cap <= 0:
        return None
    try:
        handle = storage.get_file(path)
        try:
            data = handle.read(cap + 1)
        finally:
            close = getattr(handle, "close", None)
            if callable(close):
                close()
    except Exception as exc:
        logger.info("Full text %s unavailable: %s", path, exc)
        return None
    if not data or len(data) > cap:
        if data:
            logger.warning("Full text %s is larger than ATTACHMENT_FULL_TEXT_MAX_BYTES; not loaded", path)
        return None
    return data.decode("utf-8", errors="replace")
