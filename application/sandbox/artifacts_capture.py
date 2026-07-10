"""Shared sandbox->artifact persistence: detect produced files and store them by reference.

Both the ``code_executor`` chat tool and the workflow ``code`` node run code in a
run/conversation-scoped sandbox session and must turn newly written workspace files
into ``artifacts`` rows. Only metadata (size/sha256/mime + the storage key) is stored
here; binary bytes live in ``BaseStorage`` and never enter LLM context or workflow state.
"""

from __future__ import annotations

import fnmatch
import hashlib
import io
import logging
import mimetypes
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import text

from application.agents.tools.artifact_ref import make_ref
from application.core.settings import settings
from application.storage.db.repositories.artifacts import ArtifactsRepository
from application.storage.db.session import db_session
from application.storage.storage_creator import StorageCreator
from application.utils import safe_filename

logger = logging.getLogger(__name__)


class QuotaExceeded(Exception):
    """Raised when persisting an artifact would breach a per-user size/count quota."""

# Cap the per-run capture work so a workspace full of pre-existing files can't turn
# one exec into an unbounded read+persist sweep.
MAX_CAPTURED_FILES = 64

# Cap the per-pass READ sweep independently of the persist cap: unchanged files are
# read (to detect a change) then skipped without counting toward MAX_CAPTURED_FILES,
# so a workspace full of unchanged files could otherwise be re-read in full every exec.
MAX_SCANNED_FILES = 256

# Auto-capture skips scratch/intermediate workspace paths so install steps, extracted
# archives, and temp files don't each become a downloadable artifact. Agents write
# throwaway files under ``tmp/``; an explicit ``outputs`` list bypasses this skip (the
# agent is then naming exactly what to keep).
_SCRATCH_PREFIXES = ("tmp/",)
_SCRATCH_SUFFIXES = (".tmp", ".lock", ".pyc", ".pyo")

_DEFAULT_KIND = "file"

# Coarse mime -> artifact kind mapping for the UI rail; defaults to "file".
_KIND_BY_MIME_PREFIX: Dict[str, str] = {
    "image/": "image",
    "text/html": "html",
    "text/csv": "data",
    "application/json": "data",
    "application/vnd.openxmlformats-officedocument.presentationml": "presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml": "spreadsheet",
    "application/vnd.ms-excel": "spreadsheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml": "document",
    "application/msword": "document",
    "application/pdf": "document",
}


def unique_input_path(rel_path: str, used: Set[str]) -> str:
    """Return ``rel_path`` (reserving it) or a ``-2``/``-3``... suffixed variant when already staged.

    Two inputs whose current versions share a filename would otherwise clobber each other at the
    same ``inputs/{name}`` path; the numeric suffix is inserted before the extension. Mutates
    ``used`` to record the returned path.
    """
    if rel_path not in used:
        used.add(rel_path)
        return rel_path
    base, ext = os.path.splitext(rel_path)
    n = 2
    while f"{base}-{n}{ext}" in used:
        n += 1
    unique = f"{base}-{n}{ext}"
    used.add(unique)
    return unique


def infer_mime(filename: str) -> str:
    """Infer a mime type from a filename, falling back to a generic binary type."""
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


def kind_for_mime(mime: str) -> str:
    """Map a mime type to a coarse artifact ``kind`` for the artifact rail."""
    for prefix, kind in _KIND_BY_MIME_PREFIX.items():
        if mime.startswith(prefix):
            return kind
    return _DEFAULT_KIND


def _is_scratch(rel_path: str) -> bool:
    """True for scratch/junk workspace paths excluded from auto-capture."""
    if rel_path == "tmp" or rel_path.startswith(_SCRATCH_PREFIXES):
        return True
    if any(part == "__pycache__" or part.startswith(".") for part in rel_path.split("/")):
        return True
    return rel_path.endswith(_SCRATCH_SUFFIXES)


def _matches_outputs(rel_path: str, outputs: List[str]) -> bool:
    """True when a workspace path matches any caller-supplied ``outputs`` glob.

    Each pattern is matched against the full workspace-relative path and the bare
    filename, so ``report.pdf``, ``*.csv``, and ``out/*.json`` all work.
    """
    name = rel_path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(name, pat) for pat in outputs)


def snapshot_signatures(manager: Any, session_id: str) -> Dict[str, Tuple[int, Optional[str]]]:
    """Map each non-input, non-scratch workspace file to a (size, sha256) signature."""
    signatures: Dict[str, Tuple[int, Optional[str]]] = {}
    try:
        files = manager.list_files(session_id)
    except Exception:
        logger.exception("artifacts_capture: pre-exec listing failed")
        return signatures
    candidates = sorted(f for f in files if not f.startswith("inputs/") and not _is_scratch(f))
    if len(candidates) > MAX_SCANNED_FILES:
        logger.warning(
            "artifacts_capture: pre-exec signature scan capped at %d of %d files",
            MAX_SCANNED_FILES,
            len(candidates),
        )
    for rel_path in candidates[:MAX_SCANNED_FILES]:
        try:
            data = manager.get_file(session_id, rel_path)
        except Exception:
            logger.exception("artifacts_capture: pre-exec signature read failed")
            continue
        signatures[rel_path] = (len(data), hashlib.sha256(data).hexdigest())
    return signatures


def capture_artifacts(
    manager: Any,
    session_id: str,
    pre_signatures: Dict[str, Tuple[int, Optional[str]]],
    *,
    user_id: str,
    conversation_id: Optional[str] = None,
    workflow_run_id: Optional[str] = None,
    message_id: Optional[str] = None,
    produced_by: Optional[Dict[str, Any]] = None,
    outputs: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Persist workspace files that are new or whose content changed.

    When ``outputs`` is given, capture only files matching those globs (the caller is
    naming exactly what to keep). Otherwise auto-capture every produced file except
    scratch/intermediate paths (``tmp/`` and obvious junk; see ``_is_scratch``).
    Returns one artifact reference per captured file: ``{artifact_id, version,
    filename, mime_type, size}`` (JSON primitives only; never bytes).
    """
    try:
        post_files = set(manager.list_files(session_id))
    except Exception:
        logger.exception("artifacts_capture: post-exec listing failed")
        return []

    produced = (f for f in post_files if not f.startswith("inputs/"))
    if outputs:
        candidates = sorted(f for f in produced if _matches_outputs(f, outputs))
    else:
        candidates = sorted(f for f in produced if not _is_scratch(f))
    captured: List[Dict[str, Any]] = []
    scanned = 0
    for rel_path in candidates:
        if len(captured) >= MAX_CAPTURED_FILES:
            logger.warning("artifacts_capture: capture cap reached; remaining files skipped")
            break
        if scanned >= MAX_SCANNED_FILES:
            logger.warning("artifacts_capture: read-scan cap reached; remaining files skipped")
            break
        scanned += 1
        try:
            data = manager.get_file(session_id, rel_path)
        except Exception:
            logger.exception("artifacts_capture: get_file failed during capture")
            continue
        # A pre-existing file is only captured when its content changed; an
        # unchanged file is skipped so re-runs don't re-persist stale inputs.
        signature = (len(data), hashlib.sha256(data).hexdigest())
        if pre_signatures.get(rel_path) == signature:
            continue
        try:
            ref = persist_artifact(
                rel_path,
                data,
                user_id=user_id,
                conversation_id=conversation_id,
                workflow_run_id=workflow_run_id,
                message_id=message_id,
                produced_by=produced_by,
            )
        except QuotaExceeded:
            # Out of quota: stop capturing the remaining files rather than retry
            # each one. Files already captured this run are returned as-is.
            logger.warning("artifacts_capture: per-user quota reached; remaining files not captured")
            break
        if ref is not None:
            captured.append(ref)
    return captured


def persist_artifact(
    rel_path: str,
    data: bytes,
    *,
    user_id: str,
    conversation_id: Optional[str] = None,
    workflow_run_id: Optional[str] = None,
    message_id: Optional[str] = None,
    produced_by: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Store a captured workspace file as a new artifact (kind/mime inferred from its name)."""
    # The sandbox filename is display-only; mime/kind are inferred from it, and
    # the storage key is derived from server-controlled values downstream.
    display_name = rel_path.rsplit("/", 1)[-1]
    filename = safe_filename(display_name)
    mime_type = infer_mime(filename)
    return persist_new_artifact(
        user_id=user_id,
        kind=kind_for_mime(mime_type),
        data=data,
        filename=filename,
        mime_type=mime_type,
        title=display_name,
        conversation_id=conversation_id,
        workflow_run_id=workflow_run_id,
        message_id=message_id,
        produced_by=produced_by,
    )


def _storage_key(user_id: str, artifact_id: str, version: int, filename: str) -> str:
    """Build the server-controlled storage key (``inputs/{user}/artifacts/{id}/v{n}/{file}``)."""
    # ``inputs/{user}/artifacts/...`` is the project storage-namespace convention
    # (matches attachments + spec §4); ``inputs/`` is the user's namespace root.
    return f"inputs/{user_id}/artifacts/{artifact_id}/v{version}/{filename}"


def _set_version_storage_path(conn: Any, artifact_id: str, version: int, storage_path: str) -> None:
    """Set the server-derived storage key on an existing version row."""
    conn.execute(
        text(
            "UPDATE artifact_versions SET storage_path = :p "
            "WHERE artifact_id = CAST(:aid AS uuid) AND version = :v"
        ),
        {"p": storage_path, "aid": artifact_id, "v": version},
    )


def _cleanup_orphan(storage: Any, saved_key: Optional[str]) -> None:
    """Best-effort delete of a stored key whose owning transaction failed to commit."""
    if saved_key is None:
        return
    try:
        storage.delete_file(saved_key)
    except Exception:
        logger.exception("artifacts_capture: orphaned-key cleanup failed for %s", saved_key)


def _check_single_artifact_size(size: int) -> None:
    """Reject a single artifact version whose byte size exceeds ``ARTIFACT_MAX_BYTES``."""
    max_bytes = int(getattr(settings, "ARTIFACT_MAX_BYTES", 0) or 0)
    if max_bytes > 0 and size > max_bytes:
        raise QuotaExceeded(f"artifact is too large: {size} bytes exceeds the {max_bytes}-byte per-file cap")


def _enforce_user_quota(repo: ArtifactsRepository, user_id: str, added_bytes: int, *, new_artifact: bool) -> None:
    """Reject the write when ``user_id`` is at/over their count or total-bytes quota.

    Best-effort SOFT cap (not hard under concurrency): the count/total-bytes reads run
    on the same connection as the pending insert, but under READ COMMITTED two concurrent
    persists can each read a pre-insert total and both pass, briefly overshooting the cap.
    A NEW artifact also consumes one count slot; appending a version only adds bytes to an
    existing identity.
    """
    _check_single_artifact_size(added_bytes)
    max_count = int(getattr(settings, "ARTIFACT_MAX_COUNT_PER_USER", 0) or 0)
    if new_artifact and max_count > 0 and repo.count_for_user(user_id) >= max_count:
        raise QuotaExceeded(f"artifact count quota reached ({max_count}); delete artifacts to free space")
    max_total = int(getattr(settings, "ARTIFACT_MAX_TOTAL_BYTES_PER_USER", 0) or 0)
    if max_total > 0 and repo.total_bytes_for_user(user_id) + added_bytes > max_total:
        raise QuotaExceeded(f"artifact storage quota reached ({max_total} bytes); delete artifacts to free space")


def _ref_from_metadata(metadata: Any) -> Optional[str]:
    """Return the short ref (``A{ref_seq}``) from a stored metadata dict, or None when absent/non-numeric."""
    if not isinstance(metadata, dict):
        return None
    try:
        seq = int(metadata.get("ref_seq"))
    except (TypeError, ValueError):
        return None
    return make_ref(seq) if seq >= 1 else None


def _ref_for(
    repo: ArtifactsRepository,
    artifact_id: str,
    *,
    conversation_id: Optional[str],
    workflow_run_id: Optional[str],
    metadata: Any = None,
) -> Optional[str]:
    """Compute the short ref for an artifact: its STABLE stored ``ref_seq``, else positional fallback.

    The ref_seq is assigned at creation and kept in ``metadata`` so it survives deletions of
    earlier artifacts. Legacy rows created before ref_seq existed have none, so they fall back to
    the (mutable) position-in-parent; ``resolve_artifact_id`` mirrors this fallback.
    """
    if conversation_id is None and workflow_run_id is None:
        return None
    seq_ref = _ref_from_metadata(metadata)
    if seq_ref is not None:
        return seq_ref
    try:
        position = repo.position_in_parent(
            artifact_id, conversation_id=conversation_id, workflow_run_id=workflow_run_id
        )
    except Exception:
        logger.exception("artifacts_capture: failed to compute artifact ref")
        return None
    return make_ref(position) if position >= 1 else None


def persist_new_artifact(
    *,
    user_id: str,
    kind: str,
    data: bytes,
    filename: str,
    mime_type: str,
    title: Optional[str] = None,
    conversation_id: Optional[str] = None,
    workflow_run_id: Optional[str] = None,
    message_id: Optional[str] = None,
    spec: Any = None,
    preview_text: Optional[str] = None,
    produced_by: Any = None,
) -> Optional[Dict[str, Any]]:
    """Create an artifact + version 1 and write its bytes (storage-write-last); return its reference.

    The storage write is the last statement before commit, so a failed write rolls
    the row back (bytes are never orphaned). The only remaining window is a commit
    that fails after a successful write; that key is deleted best-effort.
    """
    safe_name = safe_filename(filename)
    size = len(data)
    sha256 = hashlib.sha256(data).hexdigest()
    storage = StorageCreator.get_storage()
    saved_key: Optional[str] = None
    ref: Optional[str] = None
    try:
        with db_session() as conn:
            repo = ArtifactsRepository(conn)
            _enforce_user_quota(repo, user_id, size, new_artifact=True)
            artifact = repo.create_artifact(
                user_id,
                kind,
                conversation_id=conversation_id,
                workflow_run_id=workflow_run_id,
                message_id=message_id,
                title=title or safe_name,
                mime_type=mime_type,
                filename=safe_name,
                storage_path=None,
                size=size,
                sha256=sha256,
                spec=spec,
                preview_text=preview_text,
                produced_by=produced_by,
            )
            artifact_id = str(artifact["id"])
            storage_path = _storage_key(user_id, artifact_id, 1, safe_name)
            _set_version_storage_path(conn, artifact_id, 1, storage_path)
            # The freshly-created row carries the stable ``ref_seq`` in its metadata.
            ref = _ref_for(
                repo,
                artifact_id,
                conversation_id=conversation_id,
                workflow_run_id=workflow_run_id,
                metadata=artifact.get("metadata"),
            )
            storage.save_file(io.BytesIO(data), storage_path)
            saved_key = storage_path
    except QuotaExceeded:
        # Quota check runs before any storage write, so nothing to clean up;
        # surface a clean error the caller can render.
        raise
    except Exception:
        logger.exception("artifacts_capture: failed to persist new artifact")
        _cleanup_orphan(storage, saved_key)
        return None
    payload: Dict[str, Any] = {
        "artifact_id": artifact_id,
        "version": 1,
        "filename": safe_name,
        "mime_type": mime_type,
        "size": size,
    }
    if ref is not None:
        payload["ref"] = ref
    return payload


def append_artifact_version(
    *,
    user_id: str,
    artifact_id: str,
    data: bytes,
    filename: str,
    mime_type: str,
    spec: Any = None,
    preview_text: Optional[str] = None,
    produced_by: Any = None,
    conversation_id: Optional[str] = None,
    workflow_run_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Append a new version (new spec + new bytes) to an existing artifact; return its reference."""
    safe_name = safe_filename(filename)
    size = len(data)
    sha256 = hashlib.sha256(data).hexdigest()
    storage = StorageCreator.get_storage()
    saved_key: Optional[str] = None
    ref: Optional[str] = None
    try:
        with db_session() as conn:
            repo = ArtifactsRepository(conn)
            _enforce_user_quota(repo, user_id, size, new_artifact=False)
            version = repo.append_version(
                artifact_id,
                mime_type=mime_type,
                filename=safe_name,
                storage_path=None,
                size=size,
                sha256=sha256,
                spec=spec,
                preview_text=preview_text,
                produced_by=produced_by,
            )
            version_number = int(version["version"])
            storage_path = _storage_key(user_id, artifact_id, version_number, safe_name)
            _set_version_storage_path(conn, artifact_id, version_number, storage_path)
            # The identity's stable ``ref_seq`` was assigned at creation; read it so an
            # edit hands back the SAME ref the model already holds.
            existing = repo.get_artifact(str(artifact_id))
            ref = _ref_for(
                repo,
                str(artifact_id),
                conversation_id=conversation_id,
                workflow_run_id=workflow_run_id,
                metadata=(existing or {}).get("metadata"),
            )
            storage.save_file(io.BytesIO(data), storage_path)
            saved_key = storage_path
    except QuotaExceeded:
        raise
    except Exception:
        logger.exception("artifacts_capture: failed to append artifact version")
        _cleanup_orphan(storage, saved_key)
        return None
    payload: Dict[str, Any] = {
        "artifact_id": str(artifact_id),
        "version": version_number,
        "filename": safe_name,
        "mime_type": mime_type,
        "size": size,
    }
    if ref is not None:
        payload["ref"] = ref
    return payload
