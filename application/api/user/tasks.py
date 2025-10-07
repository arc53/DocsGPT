from datetime import timedelta

from application.celery_init import celery
from application.worker import (
    agent_webhook_worker,
    attachment_worker,
    ingest_worker,
    mcp_oauth,
    mcp_oauth_status,
    remote_worker,
    sync_worker,
)


@celery.task(bind=True)
def ingest(self, directory, formats, job_name, user, file_path, filename):
    resp = ingest_worker(self, directory, formats, job_name, file_path, filename, user)
    return resp


@celery.task(bind=True)
def ingest_remote(self, source_data, job_name, user, loader):
    resp = remote_worker(self, source_data, job_name, user, loader)
    return resp


@celery.task(bind=True)
def reingest_source_task(self, source_id, user):
    from application.worker import reingest_source_worker

    resp = reingest_source_worker(self, source_id, user)
    return resp


@celery.task(bind=True)
def schedule_syncs(self, frequency):
    resp = sync_worker(self, frequency)
    return resp


@celery.task(bind=True)
def store_attachment(self, file_info, user):
    resp = attachment_worker(self, file_info, user)
    return resp


@celery.task(bind=True)
def process_agent_webhook(self, agent_id, payload):
    resp = agent_webhook_worker(self, agent_id, payload)
    return resp


@celery.task(bind=True)
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


@celery.task(bind=True)
def mcp_oauth_task(self, config, user):
    resp = mcp_oauth(self, config, user)
    return resp


@celery.task(bind=True)
def mcp_oauth_status_task(self, task_id):
    resp = mcp_oauth_status(self, task_id)
    return resp
