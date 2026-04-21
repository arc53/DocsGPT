import threading

from celery import Celery
from application.core.settings import settings
from celery.signals import setup_logging, worker_process_init, worker_ready


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
