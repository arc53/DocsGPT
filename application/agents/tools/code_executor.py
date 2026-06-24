"""Code Executor tool: run sandboxed code in a semi-persistent session and capture produced files as artifacts."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from application.agents.tools.base import Tool
from application.core.settings import settings
from application.sandbox.artifacts_capture import (
    MAX_CAPTURED_FILES,
    capture_artifacts,
    infer_mime as _infer_mime,
    kind_for_mime as _kind_for_mime,
    snapshot_signatures,
)
from application.sandbox.base import ExecResult
from application.sandbox.sandbox_creator import SandboxCreator
from application.storage.db.repositories.artifacts import ArtifactsRepository
from application.storage.db.session import db_readonly
from application.storage.storage_creator import StorageCreator
from application.utils import safe_filename

logger = logging.getLogger(__name__)

# Re-exported for back-compat: callers (and tests) import these mime helpers
# from this module; they now live in the shared capture helper.
__all__ = ["CodeExecutorTool", "_infer_mime", "_kind_for_mime", "_tail", "_OUTPUT_TAIL_BYTES"]

# Maximum bytes of stdout/stderr returned to the LLM. The raw stream is never
# forwarded; only this tail keeps binary/runaway output out of the context.
_OUTPUT_TAIL_BYTES = 4000

# Session ids become a kernel workspace path component; the gateway only accepts
# [A-Za-z0-9_-]+, so any disallowed character is stripped before binding.
_SESSION_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _tail(stream: Optional[str]) -> str:
    """Return the trailing slice of ``stream`` bounded by ``_OUTPUT_TAIL_BYTES``."""
    if not stream:
        return ""
    if len(stream) <= _OUTPUT_TAIL_BYTES:
        return stream
    return stream[-_OUTPUT_TAIL_BYTES:]


class CodeExecutorTool(Tool):
    """Code Executor
    Run Python (or other) code in a sandboxed, semi-persistent session and capture produced files as artifacts.
    """

    def __init__(self, tool_config: Optional[Dict[str, Any]] = None, user_id: Optional[str] = None) -> None:
        """Bind the tool to the invoker and its conversation/run-scoped sandbox session."""
        self.config: Dict[str, Any] = tool_config or {}
        self.user_id: Optional[str] = user_id
        self.tool_id: Optional[str] = self.config.get("tool_id")
        self.conversation_id: Optional[str] = self.config.get("conversation_id")
        self.workflow_run_id: Optional[str] = self.config.get("workflow_run_id")
        # Static, deployment-level approval gate (mirrors the action metadata flag).
        self._require_approval: bool = bool(self.config.get("require_approval", False))
        self._last_artifact_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Tool ABC
    # ------------------------------------------------------------------
    def get_actions_metadata(self) -> List[Dict[str, Any]]:
        """Return JSON metadata describing the ``run_code`` action for tool schemas."""
        return [
            {
                "name": "run_code",
                "description": (
                    "Execute code in a sandboxed, stateful session bound to this conversation. "
                    "Files written by the code are captured as downloadable artifacts; only a "
                    "compact summary (output tail + artifact references) is returned, never raw bytes."
                ),
                "active": True,
                "require_approval": self._require_approval,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Source code to execute in the session.",
                        },
                        "language": {
                            "type": "string",
                            "description": "Programming language (default: python).",
                        },
                        "libraries": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Packages to ensure are installed before running.",
                        },
                        "inputs": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Artifact ids (from this conversation/run) to materialize into the workspace.",
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Wall-clock timeout in seconds for this execution.",
                        },
                        "ttl": {
                            "type": "integer",
                            "description": "Keep-alive lifetime (seconds) for the session; clamped by SANDBOX_MAX_TTL.",
                        },
                        "persist": {
                            "type": "boolean",
                            "description": (
                                "Keep the session warm after the call (state survives the next run). "
                                "The session is kept alive when this is true or a positive ttl is given "
                                "(clamped by SANDBOX_MAX_TTL); otherwise it is closed after the run."
                            ),
                        },
                        "capture_artifacts": {
                            "type": "boolean",
                            "description": "Capture newly written workspace files as artifacts (default: true).",
                        },
                    },
                    "required": ["code"],
                },
            }
        ]

    def get_config_requirements(self) -> Dict[str, Any]:
        """Return configuration requirements (approval gate + backend selection)."""
        return {
            "require_approval": {
                "type": "boolean",
                "label": "Require approval",
                "description": "Pause for human approval before each code execution.",
                "required": False,
            },
            "sandbox_backend": {
                "type": "string",
                "label": "Sandbox backend",
                "description": "Code-execution backend (defaults to the SANDBOX_BACKEND setting).",
                "required": False,
            },
        }

    def get_artifact_id(self, action_name: str, **kwargs: Any) -> Optional[str]:
        """Return the primary produced artifact id so the UI artifact rail lights up."""
        return self._last_artifact_id

    def preview_decision(self, action_name: str, params: dict) -> Tuple[bool, bool]:
        """Return ``(requires_approval, denylist_forced)`` for the approval gate; never denylist-forced here."""
        if action_name != "run_code":
            return True, False
        return self._require_approval, False

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def execute_action(self, action_name: str, **kwargs: Any) -> Dict[str, Any]:
        """Dispatch a tool action; only ``run_code`` is supported."""
        if action_name != "run_code":
            return {"status": "error", "error": f"unknown action: {action_name}"}
        self._last_artifact_id = None
        return self._run_code(**kwargs)

    def _run_code(self, **kwargs: Any) -> Dict[str, Any]:
        """Bind a session, materialize inputs, execute, and capture produced artifacts."""
        if not self.user_id:
            return {"status": "error", "error": "code_executor requires a valid user_id."}

        session_id = self._resolve_session_id()
        if session_id is None:
            return {"status": "error", "error": "code_executor requires a conversation_id or workflow_run_id."}

        code = kwargs.get("code")
        if not isinstance(code, str) or not code.strip():
            return {"status": "error", "error": "code is required."}

        should_capture = kwargs.get("capture_artifacts", True)
        ttl = self._coerce_int(kwargs.get("ttl"))
        timeout = self._resolve_timeout(kwargs.get("timeout"))
        inputs = kwargs.get("inputs") or []

        manager = SandboxCreator.get_manager()
        try:
            manager.open(session_id, ttl=ttl)
        except Exception as exc:
            logger.exception("code_executor: failed to open sandbox session")
            return {"status": "error", "error": f"sandbox unavailable: {type(exc).__name__}: {exc}"}

        try:
            materialized = self._materialize_inputs(manager, session_id, inputs)
            if materialized.get("error"):
                return {"status": "error", "error": materialized["error"]}

            pre_signatures: Dict[str, Tuple[int, Optional[str]]] = {}
            if should_capture:
                pre_signatures = self._snapshot_signatures(manager, session_id)

            try:
                result = manager.exec(session_id, code, timeout=timeout)
            except Exception as exc:
                logger.exception("code_executor: exec raised")
                return {"status": "error", "error": f"execution failed: {type(exc).__name__}: {exc}"}

            # Capture even on error/timeout so partial outputs aren't lost; a
            # capture failure must never mask the run's real status.
            artifacts: List[Dict[str, Any]] = []
            if should_capture:
                try:
                    artifacts = self._capture_artifacts(manager, session_id, pre_signatures)
                except Exception:
                    logger.exception("code_executor: artifact capture failed")

            return self._shape_payload(result, artifacts, materialized.get("loaded", []))
        finally:
            if not self._keep_alive(kwargs.get("persist"), ttl):
                try:
                    manager.close(session_id)
                except Exception:
                    logger.exception("code_executor: session close failed")

    # ------------------------------------------------------------------
    # Inputs / outputs
    # ------------------------------------------------------------------
    def _materialize_inputs(self, manager: Any, session_id: str, inputs: List[Any]) -> Dict[str, Any]:
        """Fetch parent-scoped input artifacts and copy their current-version bytes into the workspace."""
        loaded: List[str] = []
        if not inputs:
            return {"loaded": loaded}
        storage = StorageCreator.get_storage()
        for raw_id in inputs:
            artifact_id = str(raw_id).strip()
            if not artifact_id:
                continue
            try:
                with db_readonly() as conn:
                    repo = ArtifactsRepository(conn)
                    artifact = repo.get_artifact_in_parent(
                        artifact_id,
                        conversation_id=self.conversation_id,
                        workflow_run_id=self.workflow_run_id,
                    )
                    if artifact is None:
                        return {"error": f"input artifact {artifact_id} not found in this conversation/run."}
                    version = repo.get_version(artifact_id, artifact["current_version"])
            except Exception:
                logger.exception("code_executor: failed to load input artifact")
                return {"error": f"failed to load input artifact {artifact_id}."}

            if not version or not version.get("storage_path"):
                return {"error": f"input artifact {artifact_id} has no stored content."}

            filename = safe_filename(version.get("filename") or artifact_id)
            try:
                file_obj = storage.get_file(version["storage_path"])
                data = file_obj.read()
            except Exception:
                logger.exception("code_executor: failed to read input artifact bytes")
                return {"error": f"failed to read input artifact {artifact_id}."}
            try:
                manager.put_file(session_id, f"inputs/{filename}", data)
            except Exception:
                logger.exception("code_executor: put_file failed for input artifact")
                return {"error": f"failed to stage input artifact {artifact_id} into the workspace."}
            loaded.append(f"inputs/{filename}")
        return {"loaded": loaded}

    # Cap the per-run capture work so a workspace full of pre-existing files
    # can't turn one exec into an unbounded read+persist sweep.
    _MAX_CAPTURED_FILES = MAX_CAPTURED_FILES

    def _snapshot_signatures(self, manager: Any, session_id: str) -> Dict[str, Tuple[int, Optional[str]]]:
        """Map each non-input workspace file to a (size, sha256) signature for change detection."""
        return snapshot_signatures(manager, session_id)

    def _capture_artifacts(
        self, manager: Any, session_id: str, pre_signatures: Dict[str, Tuple[int, Optional[str]]]
    ) -> List[Dict[str, Any]]:
        """Persist each non-input workspace file that is new or whose content changed."""
        captured = capture_artifacts(
            manager,
            session_id,
            pre_signatures,
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            workflow_run_id=self.workflow_run_id,
            produced_by={
                "tool": "code_executor",
                "action": "run_code",
                "session_id": session_id,
            },
        )
        if captured:
            self._last_artifact_id = captured[0]["artifact_id"]
        return captured

    def _shape_payload(
        self, result: ExecResult, artifacts: List[Dict[str, Any]], inputs_loaded: List[str]
    ) -> Dict[str, Any]:
        """Build the compact LLM-facing payload; raw bytes never appear here."""
        status = "ok" if result.ok else "error"
        payload: Dict[str, Any] = {
            "status": status,
            "stdout_tail": _tail(result.stdout),
            "artifacts": artifacts,
        }
        stderr_tail = _tail(result.stderr)
        if stderr_tail:
            payload["stderr_tail"] = stderr_tail
        if not result.ok:
            payload["error"] = (
                f"{result.error_name}: {result.error_value}"
                if result.error_name
                else (result.error_value or "execution error")
            )
        if inputs_loaded:
            payload["inputs_loaded"] = inputs_loaded
        return payload

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _resolve_session_id(self) -> Optional[str]:
        """Derive a sandbox session id from the bound conversation/run; sanitize to the gateway charset."""
        raw = self.conversation_id or self.workflow_run_id
        if not raw:
            return None
        sanitized = _SESSION_ID_RE.sub("-", str(raw))
        return sanitized or None

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        """Coerce a value to a positive int, or None when absent/invalid."""
        if value is None:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _resolve_timeout(self, requested: Any) -> float:
        """Return the stricter of the requested timeout and the sandbox's default cap."""
        cap = float(getattr(settings, "SANDBOX_EXEC_TIMEOUT", 60))
        parsed = self._coerce_int(requested)
        if parsed is None:
            return cap
        return float(min(parsed, cap))

    @staticmethod
    def _keep_alive(persist: Any, ttl: Optional[int]) -> bool:
        """True when the agent asked to keep the session warm after the call."""
        return bool(persist) or (ttl is not None and ttl > 0)
