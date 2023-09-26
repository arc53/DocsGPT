from celery import Celery
from app import create_app

def make_celery(app_name=__name__):
    app = create_app()
    celery = Celery(app_name, broker=app.config['CELERY_BROKER_URL'])
    celery.conf.update(app.config)
    return celery

celery = make_celery()
