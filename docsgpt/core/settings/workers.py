"""Celery broker, result backend and worker process limits."""

from __future__ import annotations

from pydantic import Field

from docsgpt.core.settings._shared import SettingsGroup


class WorkerSettings(SettingsGroup):
    """How background tasks are queued and how worker processes are recycled."""

    CELERY_BROKER_URL: str = Field(default="redis://localhost:6379/0", description="Celery broker URL.")
    CELERY_RESULT_BACKEND: str = Field(default="redis://localhost:6379/1", description="Celery result backend URL.")
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = Field(
        default=1, description="Tasks prefetched per worker process; 1 caps SIGKILL loss to one task."
    )
    CELERY_VISIBILITY_TIMEOUT: int = Field(
        default=3600,
        description=(
            "Broker visibility timeout in seconds. Must exceed the longest legitimate task runtime but stay "
            "short enough that SIGKILLed tasks redeliver promptly."
        ),
    )
    CELERY_WORKER_MAX_MEMORY_PER_CHILD: int = Field(
        default=4194304,
        description=(
            "Recycle a prefork child past this resident size in KB; backstops docling/torch heap growth. "
            "Checked between tasks, so it does not bound the peak within one. 0 disables."
        ),
    )
    CELERY_WORKER_MAX_TASKS_PER_CHILD: int = Field(
        default=0, description="Recycle a worker child after N tasks; 0 disables."
    )
    API_URL: str = Field(
        default="http://localhost:7091", description="Backend URL the Celery worker calls back into."
    )
