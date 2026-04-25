import os

broker_url = os.getenv("CELERY_BROKER_URL")
result_backend = os.getenv("CELERY_RESULT_BACKEND")

task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']

# Autodiscover tasks
imports = ('application.api.user.tasks',)

beat_scheduler = "redbeat.RedBeatScheduler"
redbeat_redis_url = broker_url
redbeat_key_prefix = "redbeat:docsgpt:"
redbeat_lock_timeout = 90
