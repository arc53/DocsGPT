"""Factory + process-wide singleton selecting a sandbox backend from settings."""

from typing import Callable, Dict

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


class SandboxCreator:
    """Resolves ``SANDBOX_BACKEND`` to a backend and caches a single manager."""

    # Seam for a future "daytona" backend (Apache-2.0 SDK); not implemented here.
    backends: Dict[str, Callable[[], CodeSandbox]] = {
        "jupyter": _make_jupyter,
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
            )
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
