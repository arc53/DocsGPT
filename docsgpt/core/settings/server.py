"""The API process itself."""

from __future__ import annotations

from typing import Annotated, Optional

from pydantic import Field
from pydantic_settings import NoDecode

from docsgpt.core.settings._shared import EnvList, SettingsGroup


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
            "the Python version and the platform to gptcloud.arc53.com when it starts and every 7 hours (reusing a "
            "recent cached answer), and logs any advisory. Set false to turn it off."
        ),
    )
    PUBLIC_API_BASE_URL: Optional[str] = Field(
        default=None,
        description=(
            "Public base URL for user-facing endpoint references in prompts, and the prefix of the artifact "
            "download URLs API responses carry (relative paths when unset)."
        ),
    )
    SAFE_URL_ALLOWED_HOSTS: Annotated[list[str], NoDecode, EnvList()] = Field(
        default_factory=list,
        description=(
            "Private-network hosts that user-supplied URLs (API and MCP tools, read_webpage, monitors, custom model "
            "base URLs, the API tool a personal access token makes) may reach, as a comma list or JSON list. An "
            "entry is an exact hostname (`wiki.corp.example`, not its subdomains), which passes for any private "
            "address it resolves to, or an IP or CIDR range (`10.16.0.0/16`), which passes the addresses inside "
            "it. Loopback passes only through an IP entry (`127.0.0.1`), never a name. Link-local and cloud "
            "metadata addresses (`169.254.0.0/16`, `fd00:ec2::254`, `fd20:ce::254`, `metadata.google.internal`) and `0.0.0.0` "
            "are refused whatever is listed. Empty, every private address is refused."
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
