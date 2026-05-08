import inspect
import logging
import threading

from celery import Celery
from application.core import log_context
from application.core.settings import settings
from celery.signals import (
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
    from application.core.logging_config import setup_logging

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
        from application.storage.db.engine import dispose_engine
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


@worker_ready.connect
def _run_version_check(*args, **kwargs):
    """Kick off the anonymous version check on worker startup.

    Runs in a daemon thread so a slow endpoint or bad DNS never holds
    up the worker becoming ready for tasks. The check itself is
    fail-silent (see ``application.updates.version_check.run_check``);
    this handler's only job is to launch it and get out of the way.

    Import is lazy so the symbol resolution never fires at module
    import time — consistent with the ``_dispose_db_engine_on_fork``
    pattern above.
    """
    try:
        from application.updates.version_check import run_check
    except Exception:
        return
    threading.Thread(target=run_check, name="version-check", daemon=True).start()


celery = make_celery()
celery.config_from_object("application.celeryconfig")
