"""The API process itself."""

from __future__ import annotations

from typing import Annotated, Optional

from pydantic import Field, field_validator
from pydantic_settings import NoDecode

from docsgpt.core.settings._shared import EnvList, SettingsGroup
from docsgpt.security.client_ip import expand_trusted_proxies


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
    TRUSTED_PROXIES: Annotated[list[str], NoDecode, EnvList(none_is_empty=True)] = Field(
        default=["private"],
        description=(
            "Proxies whose X-Forwarded-For and X-Forwarded-Proto the API believes, as a comma list or JSON list "
            "of IPs and CIDR ranges plus two keywords: private (loopback, 10.0.0.0/8, 172.16.0.0/12, "
            "192.168.0.0/16, fc00::/7) and cloudflare (Cloudflare's published ranges). The client IP recorded in "
            "the audit log and access log is the rightmost X-Forwarded-For entry outside this list, so a client "
            "cannot spoof it. Add cloudflare, or your load balancer's range, when one sits in front of a private "
            "hop. * trusts every peer and takes the leftmost entry, which any client can forge. none trusts no "
            "one and records the peer's address."
        ),
    )
    TRUST_CF_CONNECTING_IP: bool = Field(
        default=False,
        description=(
            "Take the client IP from Cloudflare's CF-Connecting-IP header when the request reaches the API from a "
            "Cloudflare address, directly or through TRUSTED_PROXIES. The header is ignored from any other "
            "address, so a request that bypasses Cloudflare cannot set it."
        ),
    )

    @field_validator("TRUSTED_PROXIES")
    @classmethod
    def _check_trusted_proxies(cls, value: list[str]) -> list[str]:
        expand_trusted_proxies(value)
        return value

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
