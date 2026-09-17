"""The API process itself."""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from docsgpt.core.settings._shared import SettingsGroup


class ServerSettings(SettingsGroup):
    """Serving the UI, public URLs, and process-level knobs of the API server."""

    DEPLOYMENT_TYPE: Optional[str] = Field(
        default=None,
        description=(
            "Deployment class, e.g. cloud or production. A production class refuses to run without a "
            "configured JWT_SECRET_KEY instead of generating a local one on disk."
        ),
    )
    SERVE_UI: bool = Field(
        default=True, description="Serve the web UI shipped in the package (docsgpt/static) from the API process."
    )
    FLASK_DEBUG_MODE: bool = Field(default=False, description="Run Flask in debug mode.")
    VERSION_CHECK: bool = Field(default=True, description="Anonymous startup version check for security issues.")
    PUBLIC_API_BASE_URL: Optional[str] = Field(
        default=None, description="Public base URL for user-facing endpoint references in prompts."
    )
    GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS: int = Field(
        default=30,
        description=(
            "Bounds uvicorn's shutdown drain (uvicorn_worker doesn't forward --graceful-timeout). Keep below the "
            "gunicorn --timeout (180) watchdog. Used by BoundedDrainUvicornWorker."
        ),
    )
    WSGI_THREADPOOL_WORKERS: int = Field(
        default=96, ge=1, description="Threads serving the WSGI (Flask) part of the app under the ASGI server."
    )
    V1_SESSION_TTL_SECONDS: int = Field(
        default=24 * 60 * 60,
        description=(
            "Lets OpenAI-compatible clients identify a logical chat by session header, which chat-completions "
            "itself has no field for; TTL of that session mapping."
        ),
    )
