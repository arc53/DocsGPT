"""Celery broker, result backend and worker process limits."""

from __future__ import annotations

from typing import Optional

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
        gt=0,
        description=(
            "Broker visibility timeout in seconds. Must exceed the longest legitimate task runtime but stay "
            "short enough that SIGKILLed tasks redeliver promptly."
        ),
    )
    CELERY_WORKER_MAX_MEMORY_PER_CHILD: int = Field(
        default=4194304,
        ge=0,
        description=(
            "Recycle a prefork child past this resident size in KB; backstops docling/torch heap growth. "
            "Checked between tasks, so it does not bound the peak within one. 0 disables."
        ),
    )
    CELERY_WORKER_MAX_TASKS_PER_CHILD: int = Field(
        default=0, ge=0, description="Recycle a worker child after N tasks; 0 disables."
    )
    API_URL: str = Field(
        default="http://localhost:7091",
        description=(
            "Address of the API. The worker hands finished indexes to it here, and the API builds the agent image, "
            "agent webhook, device pairing and MCP OAuth callback links it hands out from it, so on the API set it "
            "to the address browsers use. Docker Compose sets the worker's to http://backend:7091."
        ),
    )
    WORKER_API_URL: Optional[str] = Field(
        default=None,
        description=(
            "Address the worker uses for its own calls into the API (handing over finished indexes). Unset falls "
            "back to API_URL. Set it when the API and the worker share one settings file and API_URL is a public "
            "address, e.g. http://127.0.0.1:7091; `docsgpt up --native` does."
        ),
    )
