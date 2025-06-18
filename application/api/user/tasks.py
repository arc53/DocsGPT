from datetime import timedelta

from application.celery_init import celery
from application.worker import (
    agent_webhook_worker,
    attachment_worker,
    ingest_worker,
    remote_worker,
    sync_worker,
)


@celery.task(bind=True)
def ingest(self, directory, formats, job_name, filename, user, dir_name, user_dir):
    resp = ingest_worker(self, directory, formats, job_name, filename, user, dir_name, user_dir)
    return resp


@celery.task(bind=True)
def ingest_remote(self, source_data, job_name, user, loader):
    resp = remote_worker(self, source_data, job_name, user, loader)
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
