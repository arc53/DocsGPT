from kombu import Queue

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

# Route document parsing to a dedicated queue so a parse enqueued from inside a
# Celery worker (headless/scheduled agent) is served by a separate parsing worker
# and never self-deadlocks the awaiting worker. The tool also passes the queue at
# apply_async time, so this routing is the default for any other enqueuer.
task_routes = {
    "application.api.user.tasks.parse_document": {"queue": settings.DOCUMENT_PARSE_QUEUE},
}

# Declare every queue so a bare ``celery worker`` (no -Q) consumes ALL of them —
# the default worker does the whole job, parsing included. Operators who want
# heavy OCR isolated run one worker with ``-Q docsgpt`` and another with
# ``-Q parsing``. (dict.fromkeys dedupes if DOCUMENT_PARSE_QUEUE == "docsgpt".)
task_queues = tuple(
    Queue(name) for name in dict.fromkeys(["docsgpt", settings.DOCUMENT_PARSE_QUEUE])
)

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

# Recycle the prefork worker child to bound native-heap growth from
# docling/torch parsing. Left unset (Celery's unlimited default) when 0.
if settings.CELERY_WORKER_MAX_MEMORY_PER_CHILD > 0:
    worker_max_memory_per_child = settings.CELERY_WORKER_MAX_MEMORY_PER_CHILD
if settings.CELERY_WORKER_MAX_TASKS_PER_CHILD > 0:
    worker_max_tasks_per_child = settings.CELERY_WORKER_MAX_TASKS_PER_CHILD
