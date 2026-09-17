"""Code-execution sandbox: the Jupyter gateway runner or Daytona Cloud."""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from docsgpt.core.settings._shared import SettingsGroup


class SandboxSettings(SettingsGroup):
    """The app is a CLIENT of an always-on runner; defaults are safe so app import never fails unconfigured."""

    SANDBOX_BACKEND: str = Field(
        default="jupyter", description="Sandbox backend: jupyter (self-host) or daytona (Daytona Cloud)."
    )
    SANDBOX_GATEWAY_URL: str = Field(
        default="http://localhost:8888",
        description="URL of the Jupyter Kernel Gateway runner (the docsgpt-sandbox service).",
    )
    SANDBOX_GATEWAY_AUTH_TOKEN: Optional[str] = Field(default=None, description="Gateway auth token, if set.")
    SANDBOX_KERNEL_NAME: str = Field(
        default="docsgpt-python",
        description=(
            "Kernelspec per session. The env-scrubbing docsgpt-python spec keeps kernel code from reading the "
            "gateway token or operator secrets from os.environ; the stock python3 spec inherits the gateway env "
            "verbatim and must not be used with untrusted code."
        ),
    )
    SANDBOX_MAX_TTL: int = Field(default=1200, description="Hard cap (s) on agent-selectable keep-alive TTL.")
    SANDBOX_MAX_SESSIONS: int = Field(
        default=32,
        description=(
            "Concurrent live sessions per process, backend-agnostic; at the cap an LRU-idle session is evicted. "
            "0 or negative disables the cap."
        ),
    )
    SANDBOX_EXEC_TIMEOUT: int = Field(default=60, description="Default wall-clock cap (s) per exec call.")
    SANDBOX_HTTP_TIMEOUT: int = Field(
        default=10, description="Fixed cap (s) for REST control calls (create/delete/alive/interrupt)."
    )
    SANDBOX_MAX_OUTPUT_BYTES: int = Field(
        default=8 * 1024 * 1024, description="Cap on buffered stdout+stderr per exec."
    )
    SANDBOX_MAX_FILE_BYTES: int = Field(
        default=10 * 1024 * 1024, description="Cap on get_file size routed through stdout."
    )
    SANDBOX_MAX_INPUT_BYTES: int = Field(
        default=25 * 1024 * 1024, description="Cap on an input document staged into a sandbox session."
    )
    # Runner container caps, consumed by the docsgpt-sandbox compose service, not the app.
    SANDBOX_MEMORY: str = Field(
        default="1g",
        description=(
            "Docker mem_limit for the runner container. Consumed by the docsgpt-sandbox compose service, not "
            "the app; part of the untrusted-code security boundary."
        ),
    )
    SANDBOX_CPUS: str = Field(
        default="1.0",
        description=(
            "Docker CPU quota for the runner container. Consumed by the docsgpt-sandbox compose service, not "
            "the app; part of the untrusted-code security boundary."
        ),
    )

    # Daytona Cloud backend (SANDBOX_BACKEND=daytona). All knobs are optional so app import never fails
    # when the backend is unused.
    DAYTONA_API_KEY: Optional[str] = Field(default=None, description="Daytona Cloud API key (secret).")
    DAYTONA_API_URL: Optional[str] = Field(
        default=None, description="Override for the Daytona API base URL, if self-targeting."
    )
    DAYTONA_TARGET: Optional[str] = Field(default=None, description='Daytona region/target, e.g. "us".')
    DAYTONA_SNAPSHOT: Optional[str] = Field(
        default=None,
        description="Image for new sandboxes; render libs via scripts/build_daytona_snapshot.py.",
    )
    DAYTONA_LANGUAGE: str = Field(default="python", description="Default runtime language for created sandboxes.")
    DAYTONA_AUTO_STOP_INTERVAL: int = Field(
        default=15, description="Minutes idle before Daytona auto-stops a sandbox (0 disables)."
    )
    DAYTONA_AUTO_DELETE_INTERVAL: int = Field(
        default=60, description="Minutes after stop before Daytona auto-deletes a sandbox (-1 disables)."
    )
    DAYTONA_MAX_SANDBOXES: int = Field(
        default=50, description="Cap on concurrent live Daytona sandboxes (cost-DoS guard)."
    )
