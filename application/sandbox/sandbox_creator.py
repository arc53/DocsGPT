"""Factory + process-wide singleton selecting a sandbox backend from settings."""

from typing import Callable, Dict, Optional

from application.core.settings import settings
from application.sandbox.base import CodeSandbox
from application.sandbox.jupyter_gateway import JupyterKernelGatewaySandbox
from application.sandbox.manager import SandboxManager


def _make_jupyter() -> CodeSandbox:
    """Build the Jupyter Kernel Gateway backend from ``SANDBOX_*`` settings."""
    return JupyterKernelGatewaySandbox(
        gateway_url=settings.SANDBOX_GATEWAY_URL,
        auth_token=settings.SANDBOX_GATEWAY_AUTH_TOKEN,
        kernel_name=settings.SANDBOX_KERNEL_NAME,
        default_timeout=float(settings.SANDBOX_EXEC_TIMEOUT),
        http_timeout=float(settings.SANDBOX_HTTP_TIMEOUT),
        max_output_bytes=int(settings.SANDBOX_MAX_OUTPUT_BYTES),
        max_file_bytes=int(settings.SANDBOX_MAX_FILE_BYTES),
    )


def _make_daytona() -> CodeSandbox:
    """Build the Daytona Cloud backend from ``DAYTONA_*``/``SANDBOX_*`` settings."""
    from application.sandbox.daytona import DaytonaSandbox

    # Auto-delete is the only backstop against orphaned (paid) sandboxes, so a
    # never-expiring value (<= 0) is rejected and clamped to a safe default.
    auto_delete_interval = int(settings.DAYTONA_AUTO_DELETE_INTERVAL)
    if auto_delete_interval <= 0:
        auto_delete_interval = 60

    return DaytonaSandbox(
        api_key=settings.DAYTONA_API_KEY,
        api_url=settings.DAYTONA_API_URL,
        target=settings.DAYTONA_TARGET,
        snapshot=settings.DAYTONA_SNAPSHOT,
        language=settings.DAYTONA_LANGUAGE,
        default_timeout=float(settings.SANDBOX_EXEC_TIMEOUT),
        create_timeout=float(settings.SANDBOX_HTTP_TIMEOUT) * 6,
        auto_stop_interval=int(settings.DAYTONA_AUTO_STOP_INTERVAL),
        auto_delete_interval=auto_delete_interval,
        # Bounds only what the app propagates from a response: the Daytona SDK still
        # buffers the whole HTTP response before we see it, so a full in-sandbox cap
        # would need runner-side support. This is a partial but real mitigation.
        max_output_bytes=int(settings.SANDBOX_MAX_OUTPUT_BYTES),
        max_file_bytes=int(settings.SANDBOX_MAX_FILE_BYTES),
        max_sandboxes=int(settings.DAYTONA_MAX_SANDBOXES),
    )


class SandboxCreator:
    """Resolves ``SANDBOX_BACKEND`` to a backend and caches a single manager."""

    backends: Dict[str, Callable[[], CodeSandbox]] = {
        "jupyter": _make_jupyter,
        "daytona": _make_daytona,
    }

    _instance = None

    @classmethod
    def get_manager(cls) -> SandboxManager:
        """Return the process-wide ``SandboxManager``, building it on first use."""
        if cls._instance is None:
            backend = cls.create_backend(getattr(settings, "SANDBOX_BACKEND", "jupyter"))
            cls._instance = SandboxManager(
                backend=backend,
                max_ttl=float(settings.SANDBOX_MAX_TTL),
                max_sessions=int(settings.SANDBOX_MAX_SESSIONS),
            )
        return cls._instance

    @classmethod
    def peek_manager(cls) -> Optional[SandboxManager]:
        """Return the process-wide manager if already built, else None (never constructs one)."""
        return cls._instance

    @classmethod
    def create_backend(cls, type_name: str) -> CodeSandbox:
        """Instantiate the backend registered under ``type_name`` (case-insensitive)."""
        factory = cls.backends.get(type_name.lower())
        if not factory:
            raise ValueError(f"No sandbox backend found for type {type_name}")
        return factory()

    @classmethod
    def reset(cls) -> None:
        """Drop the cached singleton (test/teardown hook)."""
        cls._instance = None
