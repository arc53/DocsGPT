import ctypes
import gc
import inspect
import logging
import sys
import threading

from celery import Celery
from docsgpt.core import log_context
from docsgpt.core.settings import settings
from celery.signals import (
    celeryd_after_setup,
    setup_logging,
    task_postrun,
    task_prerun,
    worker_process_init,
    worker_ready,
)


def make_celery(app_name=__name__):
    celery = Celery(
        app_name,
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
    )
    celery.conf.update(settings)
    return celery


@setup_logging.connect
def config_loggers(*args, **kwargs):
    from docsgpt.core.logging_config import setup_logging

    setup_logging()


@worker_process_init.connect
def _dispose_db_engine_on_fork(*args, **kwargs):
    """Dispose the SQLAlchemy engine pool in each forked Celery worker.

    SQLAlchemy connection pools are not fork-safe: file descriptors shared
    between the parent and a forked worker will corrupt the pool. Disposing
    on ``worker_process_init`` gives every worker its own fresh pool on
    first use.

    Imported lazily so Celery workers that don't touch Postgres (or where
    ``POSTGRES_URI`` is unset) don't fail at startup.
    """
    try:
        from docsgpt.storage.db.engine import dispose_engine
    except Exception:
        return
    dispose_engine()


# Most tasks in this repo accept ``user`` where the log context wants
# ``user_id``; map task parameter names to context keys explicitly.
_TASK_PARAM_TO_CTX_KEY: dict[str, str] = {
    "user": "user_id",
    "user_id": "user_id",
    "agent_id": "agent_id",
    "conversation_id": "conversation_id",
}

_task_log_tokens: dict[str, object] = {}


@task_prerun.connect
def _bind_task_log_context(task_id, task, args, kwargs, **_):
    # Resolve task args by parameter name — nearly every task in this repo
    # is called positionally, so ``kwargs.get('user')`` would bind nothing.
    ctx = {"activity_id": task_id}
    try:
        sig = inspect.signature(task.run)
        bound = sig.bind_partial(*args, **kwargs).arguments
    except (TypeError, ValueError):
        bound = dict(kwargs)
    for param_name, value in bound.items():
        ctx_key = _TASK_PARAM_TO_CTX_KEY.get(param_name)
        if ctx_key and value:
            ctx[ctx_key] = value
    _task_log_tokens[task_id] = log_context.bind(**ctx)


@task_postrun.connect
def _unbind_task_log_context(task_id, **_):
    # ``task_postrun`` fires on both success and failure. Required for
    # Celery: unlike the Flask path, tasks aren't isolated in their own
    # ``copy_context().run(...)``, so a missing reset would leak the
    # bind onto the next task on the same worker.
    token = _task_log_tokens.pop(task_id, None)
    if token is None:
        return
    try:
        log_context.reset(token)
    except ValueError:
        # task_prerun and task_postrun ran on different threads (non-default
        # Celery pool); the token isn't valid in this context. Drop it.
        logging.getLogger(__name__).debug(
            "log_context reset skipped for task %s", task_id
        )


def _trim_native_heap() -> None:
    """Return freed glibc heap pages to the OS (Linux only; no-op elsewhere)."""
    # docling/torch parsing makes large transient allocations; glibc keeps the
    # freed pages in per-thread malloc arenas rather than returning them, so a
    # long-lived worker child's RSS only ever climbs. malloc_trim hands them
    # back. The symbol is glibc-only — absent in macOS libc.
    if not sys.platform.startswith("linux"):
        return
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


# Tasks that allocate almost nothing and run on a latency-sensitive path, so
# the reclaim below costs far more than it recovers. Query embedding is one:
# measured at ~86 ms for the collect against ~8 ms for the embed itself on a
# worker holding the ONNX model, i.e. a 9x slowdown of the whole round trip.
_NO_RECLAIM_TASKS = frozenset({"docsgpt.vectorstore.embeddings_tasks.embed_texts"})
LEGACY_TASK_PREFIX = "application."


@task_postrun.connect
def _reclaim_memory_after_task(task=None, **kwargs):
    """Drop per-task allocations so the prefork child's RSS doesn't ratchet.

    Skipped for the tasks in :data:`_NO_RECLAIM_TASKS`. This exists for the
    large transient allocations docling/torch parsing makes; running a full
    generational collect after a task that allocated a few kilobytes just
    charges the next task for walking the whole heap.
    """
    name = getattr(task, "name", None)
    if isinstance(name, str) and name.startswith(LEGACY_TASK_PREFIX):
        name = "docsgpt." + name[len(LEGACY_TASK_PREFIX):]
    if name in _NO_RECLAIM_TASKS:
        return
    gc.collect()
    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
    _trim_native_heap()


@worker_ready.connect
def _run_version_check(*args, **kwargs):
    """Kick off the anonymous version check on worker startup.

    Runs in a daemon thread so a slow endpoint or bad DNS never holds
    up the worker becoming ready for tasks. The check itself is
    fail-silent (see ``docsgpt.updates.version_check.run_check``);
    this handler's only job is to launch it and get out of the way.

    Import is lazy so the symbol resolution never fires at module
    import time — consistent with the ``_dispose_db_engine_on_fork``
    pattern above.
    """
    try:
        from docsgpt.updates.version_check import run_check
    except Exception:
        return
    threading.Thread(target=run_check, name="version-check", daemon=True).start()


celery = make_celery()
celery.config_from_object("docsgpt.celeryconfig")

#: Task-name prefix the package carried before the rename to ``docsgpt``.


def register_legacy_task_names(app: Celery) -> int:
    """Make every ``docsgpt.*`` task answer to its old ``application.*`` name too.

    Messages queued by the previous release carry the old names; without the
    alias a worker on this release rejects them as unregistered. Each alias is
    a distinct task object (a subclass carrying the old name), not the same
    object under a second key: Celery builds its execution tracer per task
    object, and one object under two names would log every run under
    whichever name was traced last. Kept for one release, together with the
    ``application`` import alias.

    Returns:
        The number of aliases added.
    """
    added = 0
    for name, task in list(app.tasks.items()):
        if not name.startswith("docsgpt."):
            continue
        legacy = LEGACY_TASK_PREFIX + name[len("docsgpt."):]
        if legacy in app.tasks:
            continue
        base = type(task)
        legacy_cls = type(base.__name__, (base,), {"name": legacy, "__module__": base.__module__, "__doc__": base.__doc__})
        app.register_task(legacy_cls())
        added += 1
    return added


@celeryd_after_setup.connect
def _alias_legacy_task_names(sender=None, instance=None, **kwargs):
    """Register the pre-rename task names once the worker has loaded its tasks."""
    app = getattr(instance, "app", None) or celery
    added = register_legacy_task_names(app)
    if added:
        logging.getLogger(__name__).info("Registered %d legacy 'application.*' task-name aliases", added)
