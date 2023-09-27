from celery import Celery
from application.core.settings import settings

def make_celery(app_name=__name__):
    celery = Celery(app_name, broker=settings.CELERY_BROKER_URL)
    celery.conf.update(settings)
    return celery

celery = make_celery()
