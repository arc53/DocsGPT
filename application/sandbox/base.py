"""Backend-agnostic code-execution sandbox interface and result types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DisplayData:
    """A single rich (non-stream) kernel output keyed by MIME bundle."""

    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Plot:
    """An image/plot output captured from execution, base64-encoded by format."""

    format: str
    content_base64: str


@dataclass
class ExecResult:
    """Outcome of one ``exec`` call against a sandbox session."""

    status: str = "ok"  # "ok" | "error"
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    execution_count: Optional[int] = None
    error_name: Optional[str] = None
    error_value: Optional[str] = None
    traceback: List[str] = field(default_factory=list)
    results: List[DisplayData] = field(default_factory=list)
    display_data: List[DisplayData] = field(default_factory=list)
    plots: List[Plot] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when the execution completed without raising."""
        return self.status == "ok"


class CodeSandbox(ABC):
    """Common interface every sandbox backend (Jupyter, Daytona, ...) implements."""

    @abstractmethod
    def open(self, session_id: str) -> str:
        """Create the underlying runtime for ``session_id`` and return its handle id."""

    @abstractmethod
    def attach(self, session_id: str) -> str:
        """Reattach to ``session_id``'s runtime; MAY return a cold kernel (state not guaranteed)."""

    @abstractmethod
    def close(self, session_id: str) -> None:
        """Tear down the runtime bound to ``session_id``, freeing all resources."""

    @abstractmethod
    def exec(self, session_id: str, code: str, timeout: Optional[float] = None) -> ExecResult:
        """Execute ``code`` in ``session_id``'s stateful runtime and return its result."""

    @abstractmethod
    def put_file(self, session_id: str, dest_path: str, data: bytes) -> None:
        """Write ``data`` to ``dest_path``; precondition: a relative path contained in the workspace."""

    @abstractmethod
    def get_file(self, session_id: str, path: str) -> bytes:
        """Read ``path`` from the workspace; precondition: a relative path contained in the workspace."""

    @abstractmethod
    def list_files(self, session_id: str) -> List[str]:
        """List workspace-relative file paths for ``session_id`` (never escapes the workspace)."""
