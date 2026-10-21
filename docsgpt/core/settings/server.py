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
            "Deployment class: cloud or production makes a missing JWT_SECRET_KEY fatal at startup. Otherwise "
            "the API generates .jwt_secret_key in the data home, which suits a single local process only."
        ),
    )
    SERVE_UI: bool = Field(
        default=True, description="Serve the web UI shipped in the package (docsgpt/static) from the API process."
    )
    FLASK_DEBUG_MODE: bool = Field(default=False, description="Run Flask in debug mode.")
    VERSION_CHECK: bool = Field(
        default=True,
        description=(
            "Outbound version check for security advisories: the worker sends its version, a random instance id, "
            "the Python version, the platform and DOCSGPT_DISTRIBUTION (when set) to gptcloud.arc53.com when it "
            "starts and every 7 hours (reusing a recent cached answer), and logs any advisory. Set false to turn "
            "it off."
        ),
    )
    DOCSGPT_DISTRIBUTION: Optional[str] = Field(
        default=None,
        description=(
            "How this install was made, e.g. digitalocean for the DigitalOcean 1-Click App, which sets it. "
            "Sent with the version check (VERSION_CHECK) so installs can be counted by where they come from; "
            "unset sends nothing extra."
        ),
    )
    PUBLIC_API_BASE_URL: Optional[str] = Field(
        default=None,
        description=(
            "Public base URL for user-facing endpoint references in prompts, and the prefix of the artifact "
            "download URLs API responses carry (relative paths when unset)."
        ),
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
