from datetime import timedelta

from application.celery_init import celery
from application.worker import ingest_worker, remote_worker, sync_worker


@celery.task(bind=True)
def ingest(self, directory, formats, name_job, filename, user):
    resp = ingest_worker(self, directory, formats, name_job, filename, user)
    return resp


@celery.task(bind=True)
def ingest_remote(self, source_data, job_name, user, loader):
    resp = remote_worker(self, source_data, job_name, user, loader)
    return resp


@celery.task(bind=True)
def schedule_syncs(self, frequency):
    resp = sync_worker(self, frequency)
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
