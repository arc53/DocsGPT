import os

broker_url = os.getenv("CELERY_BROKER_URL")
result_backend = os.getenv("CELERY_RESULT_BACKEND")

task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
