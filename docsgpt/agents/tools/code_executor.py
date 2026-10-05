"""Code Executor tool: run sandboxed code in a semi-persistent session and capture produced files as artifacts."""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from docsgpt.agents.tools.artifact_ref import resolve_artifact_id
from docsgpt.agents.tools.attachment_bridge import (
    AttachmentBridgeError,
    bridge_attachment,
    match_attachment,
    too_large_message,
)
from docsgpt.agents.tools.base import Tool
from docsgpt.core.settings import settings
from docsgpt.llm.tool_images import image_ref
from docsgpt.sandbox.artifacts_capture import (
    MAX_CAPTURED_FILES,
    QuotaExceeded,
    capture_artifacts,
    persist_artifact,
    snapshot_signatures,
    unique_input_path,
)
from docsgpt.sandbox.artifacts_capture import (
    infer_mime as _infer_mime,
)
from docsgpt.sandbox.artifacts_capture import (
    kind_for_mime as _kind_for_mime,
)
from docsgpt.sandbox.base import ExecResult
from docsgpt.sandbox.sandbox_creator import SandboxCreator
from docsgpt.storage.db.repositories.artifacts import ArtifactsRepository
from docsgpt.storage.db.session import db_readonly
from docsgpt.storage.storage_creator import StorageCreator
from docsgpt.utils import safe_filename

logger = logging.getLogger(__name__)

# Re-exported for back-compat: callers (and tests) import these mime helpers
# from this module; they now live in the shared capture helper.
__all__ = ["CodeExecutorTool", "_infer_mime", "_kind_for_mime", "_tail", "_OUTPUT_TAIL_BYTES"]

# Charts one run may show the model.
MAX_SHOWN_CHARTS = 4

# Maximum bytes of stdout/stderr returned to the LLM. The raw stream is never
# forwarded; only this tail keeps binary/runaway output out of the context.
_OUTPUT_TAIL_BYTES = 4000

# Session ids become a kernel workspace path component; the gateway only accepts
# [A-Za-z0-9_-]+, so any disallowed character is stripped before binding.
_SESSION_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")

# ``persist`` values (models often send strings) that ask to close the session.
_CLOSE_VALUES = frozenset({"false", "0", "no"})


def _tail(stream: Optional[str]) -> str:
    """Return the trailing slice of ``stream`` bounded by ``_OUTPUT_TAIL_BYTES``."""
    if not stream:
        return ""
    if len(stream) <= _OUTPUT_TAIL_BYTES:
        return stream
    return stream[-_OUTPUT_TAIL_BYTES:]


class CodeExecutorTool(Tool):
    """Code Executor
    Run code in a sandboxed session; files it writes become downloadable artifacts.
    """

    def __init__(self, tool_config: Optional[Dict[str, Any]] = None, user_id: Optional[str] = None) -> None:
        """Bind the tool to the invoker and its conversation/run-scoped sandbox session."""
        self.config: Dict[str, Any] = tool_config or {}
        self.user_id: Optional[str] = user_id
        self.tool_id: Optional[str] = self.config.get("tool_id")
        self.conversation_id: Optional[str] = self.config.get("conversation_id")
        self.workflow_run_id: Optional[str] = self.config.get("workflow_run_id")
        self.message_id: Optional[str] = self.config.get("message_id")
        # Static, deployment-level approval gate (mirrors the action metadata flag).
        self._require_approval: bool = bool(self.config.get("require_approval", False))
        self._last_artifact_id: Optional[str] = None
        self._last_artifacts: List[Dict[str, Any]] = []
        # Charts the last run displayed, for the model to see (``drain_native_parts``).
        self._native_queue: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Tool ABC
    # ------------------------------------------------------------------
    @staticmethod
    def _environment_note() -> str:
        """Backend-specific note on what the sandbox has preinstalled.

        Without this the model discovers the environment by failing: importing
        pandas on a bare image, or pip-installing libraries that are already
        baked in. Keep the package lists in sync with deployment/sandbox/Dockerfile
        (jupyter) and scripts/build_daytona_snapshot.py (daytona snapshot).
        """
        backend = str(settings.SANDBOX_BACKEND or "jupyter").lower()
        if backend == "daytona":
            if settings.DAYTONA_SNAPSHOT:
                return (
                    "Preinstalled beyond the stdlib: pandas, matplotlib, openpyxl, python-pptx, "
                    "python-docx, reportlab, lxml, pillow. If an import fails, pip install the package from "
                    "within the code; pip install anything else the same way before importing it."
                )
            return (
                "Only the Python stdlib is preinstalled. pip install any third-party "
                "package (pandas, python-docx, ...) from within the code before importing it."
            )
        return (
            "Preinstalled beyond the stdlib: pandas, matplotlib, python-pptx, python-docx, "
            "openpyxl, reportlab. pip install anything else from within the code before "
            "importing it."
        )

    @staticmethod
    def _persistence_note() -> str:
        """Backend-specific note on what survives from one ``run_code`` call to the next.

        The Jupyter runner keeps one kernel per session, so interpreter state
        carries over. Daytona runs every call in a new interpreter: only the
        sandbox filesystem (and so pip installs) outlives a call.
        """
        backend = str(settings.SANDBOX_BACKEND or "jupyter").lower()
        if backend == "daytona":
            return (
                "The session stays warm between calls until it idles out: files and pip-installed "
                "packages carry over to the next run_code call, but each call runs in a fresh Python "
                "interpreter, so variables and imports do NOT carry over. Re-import and re-load what "
                "you need in every call, and pass data between calls through files. "
            )
        return (
            "The session stays warm between calls until it idles out: variables, imports, files and "
            "installed packages carry over to the next run_code call. "
        )

    def get_actions_metadata(self) -> List[Dict[str, Any]]:
        """Return JSON metadata describing the ``run_code`` action for tool schemas."""
        return [
            {
                "name": "run_code",
                "description": (
                    "Execute Python in a sandboxed session bound to this conversation. Use it for real "
                    "computation, data processing, file parsing or conversion, and "
                    "charts rather than estimating or writing results by hand; each run is "
                    "time-limited, so start long work in the background and check on it with "
                    "another run. Do NOT use it for arithmetic you can do inline. "
                    + self._persistence_note()
                    + "Every result has a `session` field: `new` means a fresh session where nothing "
                    "from earlier calls exists, so rebuild what you need; `reused` means what earlier calls "
                    "left is still there. "
                    "Files the code writes in the workspace (the working directory) are saved as "
                    "downloadable artifacts, and saving a file again under the same name adds a new "
                    "version of it. Put previews, test renders and intermediate files under `scratch/`, "
                    "which is never saved, or pass `outputs` to save only specific files. Absolute paths "
                    "such as /tmp are outside the workspace: files there are never saved, so do not rely on "
                    "them later. "
                    "Only a compact summary (output tail + artifact references) is returned, never raw bytes. "
                    "Charts the code displays (plt.show()) are shown to you as images when you can read "
                    "images: show a chart to check it yourself, and savefig the chart the user should get. "
                    "A displayed chart is saved for the user only when the run saved no image file. "
                    "Each saved file appears to the user as a download button: name it in your answer, "
                    "never write a link or sandbox path to it. "
                    "Each call is capped at ~60s of wall-clock; for longer work, start it in the "
                    "background and poll with additional run_code calls. "
                    + self._environment_note()
                ),
                "active": True,
                "require_approval": self._require_approval,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Python source to execute in the session. Install packages from "
                            "within the code itself (e.g. subprocess pip install) if needed.",
                        },
                        "inputs": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Files to materialize into the workspace; each accepts the short "
                            "ref like `A1` returned by a previous artifact action, a full artifact id, or "
                            "a file the user attached to this conversation by its ref like `F3` (or its "
                            "name). Each is staged at `inputs/<filename>` before the code runs — read it "
                            "from that path (the result's `inputs_loaded` echoes the exact staged paths).",
                        },
                        "outputs": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filenames or globs (e.g. `report.pdf`, `*.csv`) to save as "
                            "downloadable artifacts. When set, only matching files are saved; when omitted, "
                            "every produced file is saved except scratch paths under `scratch/`.",
                        },
                        "ttl": {
                            "type": "integer",
                            "description": "Keep-alive lifetime (seconds) for the session; clamped by SANDBOX_MAX_TTL.",
                        },
                        "persist": {
                            "type": "boolean",
                            "description": (
                                "Keep the session warm after this call (default: true), so the next "
                                "run_code call finds its files and installed packages. Pass false only "
                                "when no more code will run in this conversation: the session is then "
                                "closed and everything in it discarded."
                            ),
                        },
                        "capture_artifacts": {
                            "type": "boolean",
                            "description": "Save produced workspace files as downloadable artifacts "
                            "(default: true). Set false for setup or install-only steps that write nothing "
                            "worth keeping.",
                        },
                    },
                    "required": ["code"],
                },
            }
        ]

    def get_config_requirements(self) -> Dict[str, Any]:
        """Return configuration requirements (none; approval is an action-level flag,
        and the sandbox backend is a deployment-level setting)."""
        return {}

    def get_artifact_id(self, action_name: str, **kwargs: Any) -> Optional[str]:
        """Return the primary produced artifact id so the UI artifact rail lights up."""
        return self._last_artifact_id

    def get_artifacts(self, action_name: str, **kwargs: Any) -> List[Dict[str, Any]]:
        """Return every artifact this call produced, with display names.

        A single ``run_code`` can write several files. Reporting only the first
        left the others reachable by API but invisible in the UI, and gave the
        one button the tool's name rather than the file's.
        """
        return list(self._last_artifacts)

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
        self._last_artifacts = []
        self._native_queue = []
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
        outputs = self._normalize_outputs(kwargs.get("outputs"))
        ttl = self._coerce_int(kwargs.get("ttl"))
        keep_alive = self._keep_alive(kwargs.get("persist"), ttl)
        # Keeping the session asks for the full idle TTL: a reuse only ever extends a
        # session's TTL when one is passed, and a session another tool opened first
        # (artifact_generator opens at the exec timeout) would be reaped early.
        open_ttl = ttl if ttl is not None else (float(settings.SANDBOX_MAX_TTL) if keep_alive else None)
        timeout = self._exec_timeout()
        inputs = kwargs.get("inputs") or []

        manager = SandboxCreator.get_manager()
        try:
            opened = manager.open_session(session_id, ttl=open_ttl)
        except Exception as exc:
            logger.exception("code_executor: failed to open sandbox session")
            return {"status": "error", "error": f"sandbox unavailable: {type(exc).__name__}: {exc}"}
        # Tells the model whether earlier files/installs/variables can still be there.
        session_state = "new" if opened.created else "reused"

        try:
            materialized = self._materialize_inputs(manager, session_id, inputs)
            if materialized.get("error"):
                return {"status": "error", "error": materialized["error"], "session": session_state}

            pre_signatures: Dict[str, Tuple[int, Optional[str]]] = {}
            if should_capture:
                pre_signatures = self._snapshot_signatures(manager, session_id)

            try:
                result = manager.exec(session_id, code, timeout=timeout)
            except Exception as exc:
                logger.exception("code_executor: exec raised")
                return {
                    "status": "error",
                    "error": f"execution failed: {type(exc).__name__}: {exc}",
                    "session": session_state,
                }

            # Capture even on error/timeout while the runtime remains reachable
            # so partial outputs aren't lost; capture never masks the run status.
            artifacts: List[Dict[str, Any]] = []
            if should_capture and not result.runtime_invalidated:
                try:
                    artifacts = self._capture_artifacts(manager, session_id, pre_signatures, outputs)
                except Exception:
                    logger.exception("code_executor: artifact capture failed")
            # A run that saved an image file (savefig) already gave the user its chart;
            # saving the displayed copy as well left a duplicate ``chart-<sha8>.png``.
            saved_image = any(str(a.get("mime_type") or "").startswith("image/") for a in artifacts)
            charts = self._show_charts(result, should_capture and not saved_image)

            payload = self._shape_payload(
                result, artifacts + charts, materialized.get("loaded", []), session=session_state
            )
            if self._native_queue:
                payload["charts_shown"] = [part["label"] for part in self._native_queue]
            return payload
        finally:
            if not keep_alive:
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
        # Two inputs whose current versions share a filename would clobber each other at
        # the same ``inputs/{name}`` path; track used paths and disambiguate deterministically.
        used_paths: set = set()
        for raw_id in inputs:
            raw = str(raw_id).strip()
            if not raw:
                continue
            artifact_id: Optional[str] = raw
            try:
                with db_readonly() as conn:
                    repo = ArtifactsRepository(conn)
                    # A short ref (A1/A2/...) resolves to an id within this parent
                    # only; the resolved id still passes through the parent-scoped
                    # gate so a ref can never reach another tenant.
                    artifact_id = resolve_artifact_id(
                        repo,
                        raw,
                        conversation_id=self.conversation_id,
                        workflow_run_id=self.workflow_run_id,
                    )
                    artifact = (
                        repo.get_artifact_in_parent(
                            artifact_id,
                            conversation_id=self.conversation_id,
                            workflow_run_id=self.workflow_run_id,
                        )
                        if artifact_id is not None
                        else None
                    )
                    if artifact is None:
                        # Conversation scope only: a raw ref that is not an artifact
                        # may name a chat attachment; bridge it on demand. Workflows
                        # bridge attachments up front, so never double-bridge there.
                        bridged_id = self._bridge_chat_attachment(raw)
                        if isinstance(bridged_id, dict):
                            return bridged_id  # error payload
                        if bridged_id is None:
                            return {"error": f"input artifact {raw} not found in this conversation/run."}
                        artifact_id = bridged_id
                        artifact = repo.get_artifact_in_parent(artifact_id, conversation_id=self.conversation_id)
                        if artifact is None:
                            return {"error": f"input artifact {raw} not found in this conversation/run."}
                    version = repo.get_version(artifact_id, artifact["current_version"])
            except Exception:
                logger.exception("code_executor: failed to load input artifact")
                return {"error": f"failed to load input artifact {artifact_id}."}

            if not version or not version.get("storage_path"):
                return {"error": f"input artifact {artifact_id} has no stored content."}

            # Reject an oversize input BEFORE buffering it: the declared ``size``
            # avoids pulling a huge file into worker memory, and the bounded read
            # below backstops a missing/lying size column.
            max_bytes = int(settings.SANDBOX_MAX_INPUT_BYTES or 0)
            declared_size = version.get("size")
            if max_bytes and isinstance(declared_size, (int, float)) and declared_size > max_bytes:
                return {"error": f"input artifact {artifact_id} exceeds the {max_bytes}-byte sandbox input limit."}

            filename = safe_filename(version.get("filename") or artifact_id)
            try:
                file_obj = storage.get_file(version["storage_path"])
                try:
                    data = file_obj.read(max_bytes + 1) if max_bytes else file_obj.read()
                finally:
                    close = getattr(file_obj, "close", None)
                    if callable(close):
                        close()
            except Exception:
                logger.exception("code_executor: failed to read input artifact bytes")
                return {"error": f"failed to read input artifact {artifact_id}."}
            if max_bytes and len(data) > max_bytes:
                return {"error": f"input artifact {artifact_id} exceeds the {max_bytes}-byte sandbox input limit."}
            rel_path = unique_input_path(f"inputs/{filename}", used_paths)
            try:
                manager.put_file(session_id, rel_path, data)
            except Exception:
                logger.exception("code_executor: put_file failed for input artifact")
                return {"error": f"failed to stage input artifact {artifact_id} into the workspace."}
            loaded.append(rel_path)
        return {"loaded": loaded}

    def _bridge_chat_attachment(self, raw: str) -> Any:
        """Bridge a referenced chat attachment to a conversation artifact id; None on miss, error dict on failure.

        A file over ``SANDBOX_MAX_INPUT_BYTES`` is refused here, before it is copied into an artifact
        that staging would then reject anyway.
        """
        if not self.conversation_id or not self.user_id:
            return None
        attachment = match_attachment(self.config.get("attachments"), raw, self.user_id)
        if attachment is None:
            return None
        max_bytes = int(settings.SANDBOX_MAX_INPUT_BYTES or 0)
        size = attachment.get("size")
        if max_bytes and isinstance(size, (int, float)) and size > max_bytes:
            return {
                "error": f"{raw}: {too_large_message(attachment, max_bytes)} for files loaded into the "
                "sandbox, so it was not loaded. Work from the file's text instead."
            }
        try:
            return bridge_attachment(
                attachment, user_id=self.user_id, conversation_id=self.conversation_id, max_bytes=max_bytes
            )
        except AttachmentBridgeError as exc:
            return {"error": f"failed to load {raw} into the sandbox: {exc}"}

    # Cap the per-run capture work so a workspace full of pre-existing files
    # can't turn one exec into an unbounded read+persist sweep.
    _MAX_CAPTURED_FILES = MAX_CAPTURED_FILES

    def _snapshot_signatures(self, manager: Any, session_id: str) -> Dict[str, Tuple[int, Optional[str]]]:
        """Map each non-input workspace file to a (size, sha256) signature for change detection."""
        return snapshot_signatures(manager, session_id)

    @staticmethod
    def _normalize_outputs(raw: Any) -> Optional[List[str]]:
        """Coerce the ``outputs`` arg to a list of non-empty glob strings, or None.

        Tolerates a bare string (some models pass one instead of an array); an empty
        or non-list value means "no allow-list" (auto-capture).
        """
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            return None
        patterns = [str(p).strip() for p in raw if isinstance(p, str) and str(p).strip()]
        return patterns or None

    def _capture_artifacts(
        self,
        manager: Any,
        session_id: str,
        pre_signatures: Dict[str, Tuple[int, Optional[str]]],
        outputs: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Persist produced workspace files (only ``outputs`` globs when given)."""
        captured = capture_artifacts(
            manager,
            session_id,
            pre_signatures,
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            workflow_run_id=self.workflow_run_id,
            message_id=self.message_id,
            produced_by={
                "tool": "code_executor",
                "action": "run_code",
                "session_id": session_id,
            },
            outputs=outputs,
        )
        if captured:
            self._last_artifact_id = captured[0]["artifact_id"]
            self._last_artifacts = [
                # ``ref`` is the model-facing handle (``A1``); the UI needs it to
                # resolve a ref the model typed into its answer.
                {"id": a["artifact_id"], "filename": a.get("filename"), "ref": a.get("ref")}
                for a in captured
                if a.get("artifact_id")
            ]
        return captured

    def _show_charts(self, result: ExecResult, save: bool) -> List[Dict[str, Any]]:
        """Queue the charts the run displayed for the model to see, saving each as an artifact.

        A chart is saved through ``persist_artifact`` like a captured file. Its name is
        derived from its bytes, so showing the same chart again reuses its artifact.

        Args:
            result: The run's result; ``plots`` holds the displayed charts.
            save: Save them as artifacts. False when the call turned capture off, or
                when the run already saved an image file of its own.

        Returns:
            The saved charts' artifact references.
        """
        saved: List[Dict[str, Any]] = []
        for plot in result.plots[:MAX_SHOWN_CHARTS]:
            try:
                raw = base64.b64decode(plot.content_base64)
            except (binascii.Error, ValueError):
                continue
            filename = f"chart-{hashlib.sha256(raw).hexdigest()[:8]}.{plot.format or 'png'}"
            ref = None
            if save:
                try:
                    ref = persist_artifact(
                        filename,
                        raw,
                        user_id=self.user_id,
                        conversation_id=self.conversation_id,
                        workflow_run_id=self.workflow_run_id,
                        message_id=self.message_id,
                        produced_by={"tool": "code_executor", "action": "run_code", "display": True},
                    )
                except QuotaExceeded:
                    save = False
                except Exception:
                    logger.exception("code_executor: saving a displayed chart failed")
            if ref is not None:
                saved.append(ref)
                self._last_artifacts.append({"id": ref["artifact_id"], "filename": filename, "ref": ref.get("ref")})
                self._last_artifact_id = self._last_artifact_id or ref["artifact_id"]
            label = f"{ref['ref']} {filename}" if ref and ref.get("ref") else filename
            try:
                self._native_queue.append(image_ref(raw, label))
            except ValueError:
                logger.info("code_executor: a displayed chart is not an image that can be shown")
        return saved

    def drain_native_parts(self) -> List[Dict[str, Any]]:
        """Charts the last run displayed, emptied as they are taken."""
        parts, self._native_queue = self._native_queue, []
        return parts

    def _shape_payload(
        self,
        result: ExecResult,
        artifacts: List[Dict[str, Any]],
        inputs_loaded: List[str],
        session: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build the compact LLM-facing payload; raw bytes never appear here.

        Args:
            result: The run's result.
            artifacts: References of the files and charts the run saved.
            inputs_loaded: Workspace paths the inputs were staged at.
            session: ``"new"`` or ``"reused"``, reported right after the status.

        Returns:
            The payload the model sees.
        """
        status = "ok" if result.ok else "error"
        payload: Dict[str, Any] = {"status": status}
        if session is not None:
            payload["session"] = session
        payload["stdout_tail"] = _tail(result.stdout)
        payload["artifacts"] = artifacts
        stderr_tail = _tail(result.stderr)
        if stderr_tail:
            payload["stderr_tail"] = stderr_tail
        if not result.ok:
            if self._is_timeout(result):
                cap = int(self._exec_timeout())
                payload["error"] = (
                    f"Execution timed out. Each run_code call is capped at {cap}s and the limit "
                    "cannot be raised. For long-running work, start it in the background (e.g. launch a "
                    "subprocess or `nohup ... &` and write progress to a file) and return immediately, "
                    "then poll with additional run_code calls to check on it. The session, with the "
                    "background process and its files, stays alive between calls unless you pass "
                    "persist=false."
                )
            else:
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

    @staticmethod
    def _exec_timeout() -> float:
        """Return the fixed per-run wall-clock cap (SANDBOX_EXEC_TIMEOUT; not caller-adjustable)."""
        return float(settings.SANDBOX_EXEC_TIMEOUT)

    @staticmethod
    def _is_timeout(result: ExecResult) -> bool:
        """True when a failed exec looks like a wall-clock timeout (any backend's naming/message)."""
        blob = f"{result.error_name or ''} {result.error_value or ''}".lower()
        return "timeout" in blob or "timed out" in blob

    @staticmethod
    def _keep_alive(persist: Any, ttl: Optional[int]) -> bool:
        """Whether to keep the session warm after the call.

        Keeping it is the default: models write a file or pip install in one call
        and use it in the next, and closing deleted the Daytona sandbox after every
        run. Idle sessions are still retired by the manager's TTL (and Daytona's
        auto-stop), so only an explicit ``persist=false`` without a positive ttl
        closes the session now.

        Args:
            persist: The call's ``persist`` argument: None, a bool, or a string such
                as ``"false"``.
            ttl: The call's positive ``ttl``, or None.

        Returns:
            False only when the agent asked to close the session.
        """
        if ttl is not None and ttl > 0:
            return True
        if persist is None:
            return True
        if isinstance(persist, str):
            return persist.strip().lower() not in _CLOSE_VALUES
        return bool(persist)
