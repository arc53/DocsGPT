import logging
from datetime import timedelta

from application.api.user.idempotency import with_idempotency
from application.celery_init import celery
from application.worker import (
    agent_webhook_worker,
    attachment_worker,
    ingest_worker,
    mcp_oauth,
    parse_document_worker,
    reembed_wiki_page_worker,
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


# operation tag for the poison-path source.ingest.failed event, per task.
_INGEST_POISON_OPERATION = {
    "ingest": "upload",
    "ingest_remote": "upload",
    "ingest_connector_task": "upload",
    "reingest_source_task": "reingest",
}


def _emit_ingest_poison_event(task_name, bound):
    """Publish a terminal ``source.ingest.failed`` when the poison-guard trips.

    The guard returns before the worker runs, so the worker's own failed
    event never fires — without this the upload toast spins on "training".
    """
    user = bound.get("user")
    source_id = bound.get("source_id")
    if not user or not source_id:
        return
    from application.events.publisher import publish_user_event

    publish_user_event(
        user,
        "source.ingest.failed",
        {
            "source_id": str(source_id),
            "filename": bound.get("filename") or "",
            "operation": _INGEST_POISON_OPERATION.get(task_name, "upload"),
            "error": "Ingestion stopped after repeated failures.",
        },
        scope={"kind": "source", "id": str(source_id)},
    )


@celery.task(**DURABLE_TASK)
@with_idempotency(task_name="ingest", on_poison=_emit_ingest_poison_event)
def ingest(
    self,
    directory,
    formats,
    job_name,
    user,
    file_path,
    filename,
    file_name_map=None,
    config=None,
    idempotency_key=None,
    source_id=None,
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
        config=config,
        idempotency_key=idempotency_key,
        source_id=source_id,
    )
    return resp


@celery.task(**DURABLE_TASK)
@with_idempotency(task_name="ingest_remote", on_poison=_emit_ingest_poison_event)
def ingest_remote(
    self, source_data, job_name, user, loader,
    config=None, idempotency_key=None, source_id=None,
):
    resp = remote_worker(
        self, source_data, job_name, user, loader,
        config=config,
        idempotency_key=idempotency_key,
        source_id=source_id,
    )
    return resp


@celery.task(**DURABLE_TASK)
@with_idempotency(
    task_name="reingest_source_task", on_poison=_emit_ingest_poison_event,
)
def reingest_source_task(self, source_id, user, idempotency_key=None):
    from application.worker import reingest_source_worker

    resp = reingest_source_worker(self, source_id, user)
    return resp


@celery.task(**DURABLE_TASK)
@with_idempotency(task_name="reembed_wiki_page")
def reembed_wiki_page(
    self, source_id, path, content_hash, user, idempotency_key=None,
):
    resp = reembed_wiki_page_worker(self, source_id, path, content_hash, user)
    return resp


@celery.task(**DURABLE_TASK)
@with_idempotency(task_name="convert_source_to_wiki")
def convert_source_to_wiki(self, source_id, user, idempotency_key=None):
    from application.worker import convert_source_to_wiki_worker

    resp = convert_source_to_wiki_worker(self, source_id, user)
    return resp


def _emit_graph_poison_event(task_name, bound):
    """Publish a terminal ``graph.extract.failed`` when the poison-guard trips.

    The guard returns before the worker runs, so the worker's own failed event
    never fires — without this the build UI spins forever.
    """
    user = bound.get("user")
    source_id = bound.get("source_id")
    if not user or not source_id:
        return
    from application.events.publisher import publish_user_event

    publish_user_event(
        user,
        "graph.extract.failed",
        {
            "source_id": str(source_id),
            "error": "Graph extraction stopped after repeated failures.",
        },
        scope={"kind": "source", "id": str(source_id)},
    )


@celery.task(**DURABLE_TASK)
@with_idempotency(task_name="extract_graph", on_poison=_emit_graph_poison_event)
def extract_graph(self, source_id, user, idempotency_key=None):
    from application.worker import extract_graph_worker

    resp = extract_graph_worker(self, source_id, user)
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


def _emit_attachment_poison_event(task_name, bound):
    """Publish a terminal ``attachment.failed`` when the poison-guard trips.

    Mirrors ``_emit_ingest_poison_event``: the guard returns before the
    worker runs, so ``attachment_worker``'s own events never fire and the
    upload toast would otherwise spin on "processing" forever.
    """
    user = bound.get("user")
    file_info = bound.get("file_info") or {}
    attachment_id = file_info.get("attachment_id")
    if not user or not attachment_id:
        return
    from application.events.publisher import publish_user_event

    publish_user_event(
        user,
        "attachment.failed",
        {
            "attachment_id": str(attachment_id),
            "filename": file_info.get("filename") or "",
            "error": "Attachment processing stopped after repeated failures.",
        },
        scope={"kind": "attachment", "id": str(attachment_id)},
    )


@celery.task(**DURABLE_TASK)
@with_idempotency(
    task_name="store_attachment", on_poison=_emit_attachment_poison_event,
)
def store_attachment(self, file_info, user, idempotency_key=None):
    resp = attachment_worker(self, file_info, user)
    return resp


@celery.task(**DURABLE_TASK)
@with_idempotency(task_name="process_agent_webhook")
def process_agent_webhook(self, agent_id, payload, idempotency_key=None):
    resp = agent_webhook_worker(self, agent_id, payload)
    return resp


# Not DURABLE: the read_document tool awaits this synchronously with a timeout, so a
# blind autoretry would double-parse and the caller would already have degraded. The
# task is routed to the dedicated ``parsing`` queue (celeryconfig task_routes) so a
# parse enqueued from inside a Celery worker (headless/scheduled agent) is served by a
# separate parsing worker and never self-deadlocks the awaiting worker.
@celery.task(bind=True, acks_late=False, autoretry_for=())
def parse_document(self, artifact_id, parent, user_id, options=None):
    """Parse an input artifact on the parsing queue; self-terminate at the soft time limit."""
    from celery.exceptions import SoftTimeLimitExceeded

    try:
        return parse_document_worker(self, artifact_id, parent, user_id, options or {})
    except SoftTimeLimitExceeded:
        # A pathological/malicious document must not pin a parsing-worker slot past the
        # window the caller already abandoned. Return the worker's clean error shape so
        # the slot frees and the Redis result backend still gets a terminal result.
        limit = getattr(self, "soft_time_limit", None)
        suffix = f" after {int(limit)}s" if limit else ""
        return {"status": "error", "error": f"document parsing timed out{suffix}."}


# Bind the soft limit to DOCUMENT_PARSE_TIMEOUT (the same window read_document awaits) so
# the prefork worker self-terminates a runaway parse instead of pinning the slot; the hard
# limit is the SIGKILL backstop if the soft handler can't unwind in time.
try:
    from application.core.settings import settings as _parse_settings
    parse_document.soft_time_limit = int(_parse_settings.DOCUMENT_PARSE_TIMEOUT)
    parse_document.time_limit = parse_document.soft_time_limit + 30
except Exception:
    pass


@celery.task(**DURABLE_TASK)
@with_idempotency(
    task_name="ingest_connector_task", on_poison=_emit_ingest_poison_event,
)
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
    config=None,
    idempotency_key=None,
    source_id=None,
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
        config=config,
        idempotency_key=idempotency_key,
        source_id=source_id,
    )
    return resp


@celery.task(bind=True, acks_late=False)
def dispatch_scheduled_runs(self):
    """Beat-driven scheduler poller (body in scheduler_dispatcher)."""
    from application.api.user.scheduler_dispatcher import dispatch_due_runs

    return dispatch_due_runs()


@celery.task(
    bind=True,
    acks_late=True,
    # Not DURABLE_TASK: agent runs have side effects; blind retry would double them.
    autoretry_for=(),
    max_retries=0,
)
def execute_scheduled_run(self, run_id):
    """Execute one scheduled run; soft-time-limit honors SCHEDULE_RUN_TIMEOUT."""
    from application.api.user.scheduler_worker import execute_scheduled_run_body

    return execute_scheduled_run_body(run_id, getattr(self.request, "id", None))


# Bind runtime soft-time-limit so the prefork worker can raise mid-agent.
try:
    from application.core.settings import settings as _scheduler_settings
    execute_scheduled_run.soft_time_limit = max(
        30, int(_scheduler_settings.SCHEDULE_RUN_TIMEOUT),
    )
    execute_scheduled_run.time_limit = (
        execute_scheduled_run.soft_time_limit + 60
    )
except Exception:
    pass


@celery.task(bind=True, acks_late=False)
def cleanup_schedule_runs(self):
    """Trim ``schedule_runs`` per ``SCHEDULE_RUN_OUTPUT_RETENTION_DAYS``."""
    from application.core.settings import settings
    if not settings.POSTGRES_URI:
        return {"deleted": 0, "skipped": "POSTGRES_URI not set"}

    from application.storage.db.engine import get_engine
    from application.storage.db.repositories.schedule_runs import (
        ScheduleRunsRepository,
    )

    ttl_days = settings.SCHEDULE_RUN_OUTPUT_RETENTION_DAYS
    engine = get_engine()
    with engine.begin() as conn:
        deleted = ScheduleRunsRepository(conn).cleanup_older_than(ttl_days)
    return {"deleted": deleted, "ttl_days": ttl_days}


@celery.task(bind=True, acks_late=False)
def reap_sandbox_sessions(self):
    """Close sandbox sessions idle past their TTL in this worker process.

    The SandboxManager registry is per-process, so this reaps only sessions
    bound in THIS worker; the API processes reap their own opportunistically on
    ``open``. Artifacts are persisted eagerly, so reaping only closes idle
    kernels and never loses a user-facing artifact.
    """
    try:
        from application.sandbox.sandbox_creator import SandboxCreator

        reaped = SandboxCreator.get_manager().reap_expired()
    except Exception:  # noqa: BLE001 - housekeeping must never crash the beat loop
        logging.getLogger(__name__).exception("reap_sandbox_sessions failed")
        return {"reaped": 0, "error": True}
    return {"reaped": len(reaped)}


@celery.task(bind=True, acks_late=False)
def reap_stale_workflow_runs(self):
    """Fail workflow runs stranded in ``running`` past the stale deadline.

    A run row is pre-created as ``running`` and finalized when its generator
    finishes; a client disconnect or worker crash can leave it ``running``
    forever. This closes those rows out so the UI/API stop showing a run that
    will never complete.
    """
    from datetime import datetime, timezone

    from application.core.settings import settings
    from application.storage.db.engine import get_engine
    from application.storage.db.repositories.workflow_runs import WorkflowRunsRepository

    try:
        stale_seconds = max(60, int(settings.WORKFLOW_RUN_STALE_SECONDS))
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
        engine = get_engine()
        with engine.begin() as conn:
            reaped = WorkflowRunsRepository(conn).mark_stale_running_failed(cutoff)
    except Exception:  # noqa: BLE001 - housekeeping must never crash the beat loop
        logging.getLogger(__name__).exception("reap_stale_workflow_runs failed")
        return {"reaped": 0, "error": True}
    return {"reaped": reaped}


@celery.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    from application.core.settings import settings

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
    # Bound ``message_events`` growth — every streamed SSE chunk writes
    # one row, so retained chats accumulate hundreds of rows per
    # message. Reconnect-replay is only meaningful for streams the user
    # could plausibly still be waiting on, so 14 days is generous.
    sender.add_periodic_task(
        timedelta(hours=24),
        cleanup_message_events.s(),
        name="cleanup-message-events",
    )
    sender.add_periodic_task(
        timedelta(hours=24),
        cleanup_orphan_memories.s(),
        name="cleanup-orphan-memories",
    )
    # Scheduler dispatcher and run-log trim.
    sender.add_periodic_task(
        timedelta(seconds=max(15, settings.SCHEDULE_DISPATCHER_INTERVAL)),
        dispatch_scheduled_runs.s(),
        name="dispatch-scheduled-runs",
    )
    sender.add_periodic_task(
        timedelta(hours=24),
        cleanup_schedule_runs.s(),
        name="cleanup-schedule-runs",
    )
    # Close idle-past-TTL sandbox sessions roughly every minute. The on-open
    # opportunistic reap still runs in the API processes; this covers worker
    # processes (and quiet periods where no new session is opened).
    sender.add_periodic_task(
        timedelta(seconds=60),
        reap_sandbox_sessions.s(),
        name="reap-sandbox-sessions",
    )
    # Fail workflow runs stranded in ``running`` (client disconnect / crash) so
    # they don't linger forever. Every few minutes is plenty; the cutoff is hours.
    sender.add_periodic_task(
        timedelta(seconds=300),
        reap_stale_workflow_runs.s(),
        name="reap-stale-workflow-runs",
    )


# Bound time limits so a hung OAuth discovery (user never finishes the
# consent flow, upstream never redirects) self-terminates instead of
# stranding the ``mcp.oauth.awaiting_redirect`` envelope forever. The
# soft limit raises inside ``mcp_oauth``'s ``try`` so it publishes a
# terminal ``mcp.oauth.failed``; the hard limit is the prefork backstop.
# Generous so a human actively clicking through OAuth isn't cut off.
@celery.task(bind=True, soft_time_limit=600, time_limit=660)
def mcp_oauth_task(self, config, user):
    resp = mcp_oauth(self, config, user)
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
        cleared = repo.cleanup_expired()

    # Reaping the resumable state retires any awaiting-approval prompt
    # tied to it. Without a clearing event the durable
    # ``tool.approval.required`` envelope replays on reconnect and the UI
    # toast lingers for a conversation that can no longer be resumed.
    from application.events.publisher import publish_user_event

    for row in cleared:
        user_id = row.get("user_id")
        conversation_id = row.get("conversation_id")
        if not user_id or not conversation_id:
            continue
        publish_user_event(
            str(user_id),
            "tool.approval.cleared",
            {"conversation_id": str(conversation_id), "reason": "expired"},
            scope={"kind": "conversation", "id": str(conversation_id)},
        )
    return {"deleted": len(cleared), "reverted": reverted}


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
def cleanup_message_events(self):
    """Delete ``message_events`` rows older than the retention window.

    Streamed answer responses write one journal row per SSE yield,
    so unbounded growth would dominate Postgres for any retained-
    conversations deployment. The reconnect-replay path only needs
    rows for in-flight streams; 14 days covers paused/tool-action
    flows comfortably.
    """
    from application.core.settings import settings
    if not settings.POSTGRES_URI:
        return {"deleted": 0, "skipped": "POSTGRES_URI not set"}

    from application.storage.db.engine import get_engine
    from application.storage.db.repositories.message_events import (
        MessageEventsRepository,
    )

    ttl_days = settings.MESSAGE_EVENTS_RETENTION_DAYS
    engine = get_engine()
    with engine.begin() as conn:
        deleted = MessageEventsRepository(conn).cleanup_older_than(ttl_days)
    return {"deleted": deleted, "ttl_days": ttl_days}


@celery.task(bind=True, acks_late=False)
def cleanup_orphan_memories(self):
    """Sweep orphan memories left by the 0009 FK-to-trigger orphan window.

    A ``memories`` INSERT for a real ``tool_id`` racing a ``user_tools``
    DELETE leaves a permanent orphan the dropped FK would have rejected.
    Default-tool synthetic ids are preserved (legitimate built-in data).
    """
    from application.core.settings import settings
    if not settings.POSTGRES_URI:
        return {"deleted": 0, "skipped": "POSTGRES_URI not set"}

    from application.agents.default_tools import default_tool_ids
    from application.storage.db.engine import get_engine
    from application.storage.db.repositories.memories import MemoriesRepository

    keep_tool_ids = list(default_tool_ids().values())
    engine = get_engine()
    with engine.begin() as conn:
        deleted = MemoriesRepository(conn).delete_orphans(keep_tool_ids)
    return {"deleted": deleted}


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
