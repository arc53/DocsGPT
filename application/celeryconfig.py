from application.core.settings import settings

# Pydantic loads .env into ``settings`` but does not inject values into
# ``os.environ`` — read directly from settings so beat startup (which
# imports this module before any explicit env load) sees a real URL.
broker_url = settings.CELERY_BROKER_URL
result_backend = settings.CELERY_RESULT_BACKEND

task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']

# Autodiscover tasks
imports = ('application.api.user.tasks',)

# Project-scoped queue so a stray sibling worker on the same broker
# (other repo, same default ``celery`` queue) can't grab DocsGPT tasks.
task_default_queue = "docsgpt"
task_default_exchange = "docsgpt"
task_default_routing_key = "docsgpt"

beat_scheduler = "redbeat.RedBeatScheduler"
redbeat_redis_url = broker_url
redbeat_key_prefix = "redbeat:docsgpt:"
redbeat_lock_timeout = 90

# Survive worker SIGKILL/OOM without silently dropping in-flight tasks.
task_acks_late = True
task_reject_on_worker_lost = True
worker_prefetch_multiplier = settings.CELERY_WORKER_PREFETCH_MULTIPLIER
broker_transport_options = {"visibility_timeout": settings.CELERY_VISIBILITY_TIMEOUT}
result_expires = 86400 * 7
task_track_started = True
