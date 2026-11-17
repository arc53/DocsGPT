"""Resuming an ingest that a restart killed: what to store, and how to queue it again."""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
from typing import Any, Iterable, Optional

from docsgpt.core.settings import settings

logger = logging.getLogger(__name__)

# Celery task name -> the ``with_idempotency`` name its guard key is made
# from. Only tasks whose arguments are safe to keep in Postgres while they
# run: a connector ingest carries a session token, so it is not resumed.
RESUMABLE_INGEST_TASKS = {
    "docsgpt.api.user.tasks.ingest": "ingest",
    "docsgpt.api.user.tasks.ingest_remote": "ingest_remote",
    "docsgpt.api.user.tasks.sync_source": "sync_source",
}

_UPLOAD_INGEST = "docsgpt.api.user.tasks.ingest"


def _chunk_text(doc: Any) -> str:
    """The text the embed loop reads from a chunk."""
    return str(getattr(doc, "text", getattr(doc, "page_content", doc)) or "")


def chunk_fingerprint(docs: Iterable[Any]) -> str:
    """Hash a chunk set and the embeddings model, so a resume only continues the same work.

    Args:
        docs: The chunks about to be embedded, in order.

    Returns:
        A hex digest that changes when any chunk, their order or count, or
        ``EMBEDDINGS_NAME`` changes.
    """
    digest = hashlib.sha256()
    digest.update(str(settings.EMBEDDINGS_NAME or "").encode())
    for doc in docs:
        text = _chunk_text(doc).encode("utf-8", "surrogatepass")
        digest.update(len(text).to_bytes(8, "big"))
        digest.update(text)
    return digest.hexdigest()


def dispatch_of(task: Any, source_id: Any) -> Optional[dict]:
    """The task name and named arguments to queue ``task`` again, or ``None``.

    ``None`` for a task not in :data:`RESUMABLE_INGEST_TASKS`, or whose
    arguments cannot be named or stored as JSON. A ``source_id`` argument
    left empty is pinned to ``source_id``, so the resume lands on the same
    source even when the first dispatch let the worker pick the id.

    Args:
        task: The bound Celery task running the ingest.
        source_id: The source being embedded.

    Returns:
        ``{"task": name, "kwargs": {...}}``, or ``None``.
    """
    request = getattr(task, "request", None)
    name = getattr(request, "task", None)
    if not isinstance(name, str) or name not in RESUMABLE_INGEST_TASKS:
        return None
    args = getattr(request, "args", None) or ()
    kwargs = getattr(request, "kwargs", None) or {}
    if not isinstance(args, (list, tuple)) or not isinstance(kwargs, dict):
        return None
    try:
        signature = inspect.signature(task.run)
        named = dict(signature.bind_partial(*args, **kwargs).arguments)
        if "source_id" in signature.parameters and not named.get("source_id"):
            named["source_id"] = str(source_id)
        json.dumps(named)
    except (TypeError, ValueError):
        logger.warning("Ingest %s of %s cannot be stored for a resume", name, source_id, exc_info=True)
        return None
    return {"task": name, "kwargs": named}


def guard_key(dispatch: dict) -> Optional[str]:
    """The ``task_dedup`` key that tells whether the stored ingest is running.

    Args:
        dispatch: A stored dispatch from :func:`dispatch_of`.

    Returns:
        The task's idempotency key, the key ``with_idempotency`` makes from
        its ``source_id``, or ``None`` when it ran without a guard.
    """
    from docsgpt.api.user.idempotency import _synthesize_guard_key

    kwargs = dispatch.get("kwargs") or {}
    key = kwargs.get("idempotency_key")
    if isinstance(key, str) and key:
        return key
    guard_name = RESUMABLE_INGEST_TASKS.get(dispatch.get("task") or "")
    return _synthesize_guard_key(guard_name, kwargs) if guard_name else None


def inputs_available(dispatch: dict) -> bool:
    """Whether the files an upload ingest reads are still in storage.

    Remote ingests and syncs fetch their content again, so they count as
    available. A storage error counts as available too: the resumed task
    then fails with the real error and closes its row.

    Args:
        dispatch: A stored dispatch from :func:`dispatch_of`.

    Returns:
        ``False`` only when an upload's files are known to be gone.
    """
    if dispatch.get("task") != _UPLOAD_INGEST:
        return True
    kwargs = dispatch.get("kwargs") or {}
    try:
        from docsgpt.storage.storage_creator import StorageCreator

        storage = StorageCreator.get_storage()
        copies = kwargs.get("copy_files") or []
        if copies:
            return all(storage.file_exists(copy["from"]) for copy in copies)
        path = kwargs.get("file_path")
        return bool(path) and (storage.is_directory(path) or storage.file_exists(path))
    except Exception:  # noqa: BLE001 - an unknown answer must not end the ingest
        logger.warning("Could not check the inputs of a stalled ingest", exc_info=True)
        return True


def requeue(dispatch: dict, task_id: str) -> None:
    """Queue the stored ingest again on the ingest queue under ``task_id``.

    Args:
        dispatch: A stored dispatch from :func:`dispatch_of`.
        task_id: The Celery task id to reuse, so a client polling the first
            task's status follows the resume.
    """
    from docsgpt.celery_init import celery

    celery.send_task(
        dispatch["task"], kwargs=dispatch.get("kwargs") or {}, task_id=task_id, queue=settings.INGEST_QUEUE,
    )
