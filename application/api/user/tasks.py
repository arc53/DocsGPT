from datetime import timedelta

from application.api.user.idempotency import with_idempotency
from application.celery_init import celery
from application.worker import (
    agent_webhook_worker,
    attachment_worker,
    ingest_worker,
    mcp_oauth,
    mcp_oauth_status,
    remote_worker,
    sync,
    sync_worker,
)


# Shared decorator config for long-running, side-effecting tasks. ``acks_late``
# is also the celeryconfig default but stays explicit here so each task's
# durability story is grep-able next to the body. Combined with
# ``autoretry_for=(Exception,)`` and a bounded ``max_retries`` so a poison
# message can't loop forever.
DURABLE_TASK = dict(
    bind=True,
    acks_late=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 60},
    retry_backoff=True,
)


@celery.task(**DURABLE_TASK)
@with_idempotency(task_name="ingest")
def ingest(
    self,
    directory,
    formats,
    job_name,
    user,
    file_path,
    filename,
    file_name_map=None,
    idempotency_key=None,
):
    resp = ingest_worker(
        self,
        directory,
        formats,
        job_name,
        file_path,
        filename,
        user,
        file_name_map=file_name_map,
        idempotency_key=idempotency_key,
    )
    return resp


@celery.task(**DURABLE_TASK)
@with_idempotency(task_name="ingest_remote")
def ingest_remote(self, source_data, job_name, user, loader, idempotency_key=None):
    resp = remote_worker(
        self, source_data, job_name, user, loader,
        idempotency_key=idempotency_key,
    )
    return resp


@celery.task(**DURABLE_TASK)
@with_idempotency(task_name="reingest_source_task")
def reingest_source_task(self, source_id, user, idempotency_key=None):
    from application.worker import reingest_source_worker

    resp = reingest_source_worker(self, source_id, user)
    return resp


# Beat-driven dispatch tasks default to ``acks_late=False``: a SIGKILL
# of a beat tick is harmless to redeliver only if the dispatch itself is
# idempotent. We keep these early-ACK so the broker doesn't replay a
# dispatch that already enqueued downstream work.
@celery.task(bind=True, acks_late=False)
def schedule_syncs(self, frequency):
    resp = sync_worker(self, frequency)
    return resp


@celery.task(bind=True)
def sync_source(
    self,
    source_data,
    job_name,
    user,
    loader,
    sync_frequency,
    retriever,
    doc_id,
):
    resp = sync(
        self,
        source_data,
        job_name,
        user,
        loader,
        sync_frequency,
        retriever,
        doc_id,
    )
    return resp


@celery.task(**DURABLE_TASK)
@with_idempotency(task_name="store_attachment")
def store_attachment(self, file_info, user, idempotency_key=None):
    resp = attachment_worker(self, file_info, user)
    return resp


@celery.task(**DURABLE_TASK)
@with_idempotency(task_name="process_agent_webhook")
def process_agent_webhook(self, agent_id, payload, idempotency_key=None):
    resp = agent_webhook_worker(self, agent_id, payload)
    return resp


@celery.task(**DURABLE_TASK)
@with_idempotency(task_name="ingest_connector_task")
def ingest_connector_task(
    self,
    job_name,
    user,
    source_type,
    session_token=None,
    file_ids=None,
    folder_ids=None,
    recursive=True,
    retriever="classic",
    operation_mode="upload",
    doc_id=None,
    sync_frequency="never",
    idempotency_key=None,
):
    from application.worker import ingest_connector

    resp = ingest_connector(
        self,
        job_name,
        user,
        source_type,
        session_token=session_token,
        file_ids=file_ids,
        folder_ids=folder_ids,
        recursive=recursive,
        retriever=retriever,
        operation_mode=operation_mode,
        doc_id=doc_id,
        sync_frequency=sync_frequency,
        idempotency_key=idempotency_key,
    )
    return resp


@celery.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        timedelta(days=1),
        schedule_syncs.s("daily"),
    )
    sender.add_periodic_task(
        timedelta(weeks=1),
        schedule_syncs.s("weekly"),
    )
    sender.add_periodic_task(
        timedelta(days=30),
        schedule_syncs.s("monthly"),
    )
    # Replaces Mongo's TTL index on pending_tool_state.expires_at.
    sender.add_periodic_task(
        timedelta(seconds=60),
        cleanup_pending_tool_state.s(),
        name="cleanup-pending-tool-state",
    )
    # Pure housekeeping for ``task_dedup`` / ``webhook_dedup`` — the
    # upsert paths already handle stale rows, so cadence only bounds
    # table size. Hourly is plenty for typical traffic.
    sender.add_periodic_task(
        timedelta(hours=1),
        cleanup_idempotency_dedup.s(),
        name="cleanup-idempotency-dedup",
    )
    sender.add_periodic_task(
        timedelta(seconds=30),
        reconciliation_task.s(),
        name="reconciliation",
    )
    sender.add_periodic_task(
        timedelta(hours=7),
        version_check_task.s(),
        name="version-check",
    )


@celery.task(bind=True)
def mcp_oauth_task(self, config, user):
    resp = mcp_oauth(self, config, user)
    return resp


@celery.task(bind=True)
def mcp_oauth_status_task(self, task_id):
    resp = mcp_oauth_status(self, task_id)
    return resp


@celery.task(bind=True, acks_late=False)
def cleanup_pending_tool_state(self):
    """Revert stale ``resuming`` rows, then delete TTL-expired rows."""
    from application.core.settings import settings
    if not settings.POSTGRES_URI:
        return {"deleted": 0, "reverted": 0, "skipped": "POSTGRES_URI not set"}

    from application.storage.db.engine import get_engine
    from application.storage.db.repositories.pending_tool_state import (
        PendingToolStateRepository,
    )

    engine = get_engine()
    with engine.begin() as conn:
        repo = PendingToolStateRepository(conn)
        reverted = repo.revert_stale_resuming(grace_seconds=600)
        deleted = repo.cleanup_expired()
    return {"deleted": deleted, "reverted": reverted}


@celery.task(bind=True, acks_late=False)
def cleanup_idempotency_dedup(self):
    """Delete TTL-expired rows from ``task_dedup`` and ``webhook_dedup``.

    Pure housekeeping — the upsert paths already ignore stale rows
    (TTL-aware ``ON CONFLICT DO UPDATE``), so this only bounds table
    growth and keeps SELECT planning tight on large deployments.
    """
    from application.core.settings import settings
    if not settings.POSTGRES_URI:
        return {
            "task_dedup_deleted": 0,
            "webhook_dedup_deleted": 0,
            "skipped": "POSTGRES_URI not set",
        }

    from application.storage.db.engine import get_engine
    from application.storage.db.repositories.idempotency import (
        IdempotencyRepository,
    )

    engine = get_engine()
    with engine.begin() as conn:
        return IdempotencyRepository(conn).cleanup_expired()


@celery.task(bind=True, acks_late=False)
def reconciliation_task(self):
    """Sweep stuck durability rows and escalate them to terminal status + alert."""
    from application.api.user.reconciliation import run_reconciliation

    return run_reconciliation()


@celery.task(bind=True, acks_late=False)
def version_check_task(self):
    """Periodic anonymous version check.

    Complements the ``worker_ready`` boot trigger so long-running
    deployments (>6h cache TTL) still refresh advisories. ``run_check``
    is fail-silent and coordinates across replicas via Redis lock +
    cache (see ``application.updates.version_check``).
    """
    from application.updates.version_check import run_check
    run_check()
