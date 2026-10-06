"""Code Executor tool: run sandboxed code in a semi-persistent session and capture produced files as artifacts."""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import math
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from docsgpt.agents.tools.artifact_ref import resolve_artifact_id
from docsgpt.agents.tools.attachment_bridge import (
    AttachmentBridgeError,
    bridge_attachment,
    match_attachment,
    too_large_message,
)
from docsgpt.agents.tools.base import Tool
from docsgpt.agents.tools.code_executor_hints import (
    GENERIC_ERROR_NAMES,
    MAX_HINTS,
    REPEATED_FAILURE_HINT,
    FailureMemory,
    RunFacts,
    clean_output,
    error_signature,
    exception_of,
    fix_hints,
)
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
from docsgpt.sandbox import manifest
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

# Longest error message returned to the model; the full output is in the tails.
_ERROR_MAX_CHARS = 1000

# Hosts that only answer on a given port when they appear in a deployment URL:
# sandbox code may run its own server on localhost.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})  # nosec B104 - matched, never bound

# The last failure of each session, to notice the same failure twice in a row.
# Process-wide because a tool instance lives for one request only.
_FAILURES = FailureMemory()


def _tail(stream: Optional[str]) -> str:
    """Return the trailing slice of ``stream`` bounded by ``_OUTPUT_TAIL_BYTES``."""
    if not stream:
        return ""
    if len(stream) <= _OUTPUT_TAIL_BYTES:
        return stream
    return stream[-_OUTPUT_TAIL_BYTES:]


# Characters of the submitted code a detached run keeps for the fix hints.
_STATE_CODE_MAX_CHARS = 20_000


def detached_marker() -> Any:
    """The value ``execute_action`` returns when a background job took the run over."""
    from docsgpt.background.handoff import DETACHED

    return DETACHED


@dataclass
class PreparedRun:
    """A run_code call once its session is open and its inputs staged.

    Serializable (``to_state`` / ``from_state``) so a background job's poller
    in another process can finish a detached run exactly as the turn would.
    """

    session_id: str
    code: str
    timeout: float
    clamped: bool = False
    asked_timeout: Optional[int] = None
    should_capture: bool = True
    outputs: Optional[List[str]] = None
    pre_signatures: Dict[str, Tuple[int, Optional[str]]] = field(default_factory=dict)
    inputs_loaded: List[str] = field(default_factory=list)
    session_created: bool = False
    keep_alive: bool = True
    # The run is in a turn that can hand calls off: a timeout points to background=true.
    background_capable: bool = False
    # The run is a background job (asked for, or handed off): a timeout is reported, never re-run unasked.
    background: bool = False

    def to_state(self) -> Dict[str, Any]:
        """A JSON-safe copy (the code is kept to ``_STATE_CODE_MAX_CHARS`` for the hints)."""
        state = asdict(self)
        state["code"] = self.code[:_STATE_CODE_MAX_CHARS]
        state["pre_signatures"] = {path: list(sig) for path, sig in self.pre_signatures.items()}
        return state

    @classmethod
    def from_state(cls, state: Dict[str, Any]) -> "PreparedRun":
        """Rebuild a run from ``to_state``."""
        fields = dict(state)
        fields["pre_signatures"] = {
            path: (int(sig[0]), sig[1]) for path, sig in (state.get("pre_signatures") or {}).items()
        }
        return cls(**fields)


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
    def _backend() -> str:
        """Return the configured sandbox backend, ``jupyter`` or ``daytona``."""
        return str(settings.SANDBOX_BACKEND or "jupyter").lower()

    @classmethod
    def _full_image(cls) -> bool:
        """True when the sandbox runs the manifest's image; a Daytona sandbox without a snapshot is bare Python."""
        return not (cls._backend() == "daytona" and not settings.DAYTONA_SNAPSHOT)

    @staticmethod
    def _idle_minutes() -> int:
        """Minutes of inactivity after which a session is closed (SANDBOX_MAX_TTL)."""
        return max(1, round(int(settings.SANDBOX_MAX_TTL) / 60))

    @classmethod
    def _environment_note(cls) -> str:
        """Backend-specific note on what the sandbox has preinstalled.

        Without this the model discovers the environment by failing: importing
        pandas on a bare image, or pip-installing libraries that are already
        baked in. The lists come from docsgpt/sandbox/manifest.py, which both the
        runner image (deployment/sandbox/Dockerfile) and the Daytona snapshot
        (scripts/build_daytona_snapshot.py) are built from. Font paths and command
        usage are left to the new-session ``environment`` summary.
        """
        if not cls._full_image():
            return (
                "Only the Python stdlib is preinstalled: pip install third-party packages (pandas, python-docx, "
                "...) in the same code before importing them."
            )
        return (
            manifest.description_note()
            + " A new session's first result lists fonts and command usage in `environment`."
        )

    @classmethod
    def _persistence_note(cls) -> str:
        """Backend-specific note on what survives from one ``run_code`` call to the next.

        The Jupyter runner keeps one kernel per session, so interpreter state
        carries over. Daytona runs every call in a new interpreter: only the
        sandbox filesystem (and so pip installs) outlives a call.
        """
        if cls._backend() == "daytona":
            return (
                "files and installed packages persist while warm; each call is a fresh interpreter, so "
                "re-import and re-load from files every call."
            )
        return "variables, imports, files and installed packages persist while warm."

    @classmethod
    def _closing_rule(cls) -> str:
        """The install rule that ends the description, per image."""
        if not cls._full_image():
            return ""
        if cls._backend() == "daytona":
            # The snapshot is whatever the operator built; an older one lacks newer packages.
            return (
                "Prefer a listed library over installing another; pip-install a listed one only if its import "
                "fails; don't apt-get."
            )
        return "Prefer a listed library over installing another; never pip-install a listed one; don't apt-get."

    @classmethod
    def _description(cls) -> str:
        """Return the ``run_code`` description.

        It depends only on deployment settings and the manifest, never on the call
        or conversation, so providers can cache the tool schema.
        """
        python = f"Python {manifest.PYTHON_SERIES}" if cls._full_image() else "Python"
        timeout = int(cls._exec_timeout())
        max_timeout = int(cls._max_exec_timeout())
        lines = [
            (
                f"Run {python} in this conversation's sandbox for real computation, parsing, data work, charts and "
                "files; not for arithmetic you can do inline."
            ),
            (
                f"Session: {cls._persistence_note()} After {cls._idle_minutes()} min idle or a restart it resets and "
                "the result says `session: new`: rebuild what you need."
            ),
            (
                "Files: the working directory is the workspace; every file written there, except under `scratch/`, "
                "becomes a download for the user; files elsewhere (e.g. /tmp) are never saved. Save each deliverable "
                "once under its final name (re-saving that name adds a new version). Put previews, test renders and "
                "intermediate data in `scratch/`."
            ),
            (
                "Charts: plt.show() to look at one yourself; savefig() what the user should get. In your answer name "
                "saved files; never write links or sandbox paths."
            ),
            (
                "Inputs: pass an earlier artifact or upload by ref (`A1`, `F3`) in `inputs`; it appears at "
                "`inputs/<name>`. Artifact and app URLs can't be downloaded from inside the sandbox."
            ),
            (
                f"Limits: {timeout}s per call by default; pass `timeout` up to {max_timeout}s for long jobs (video, "
                "OCR of many pages, big conversions); prefer splitting work. Network: usually open for pip and "
                "public sites."
            ),
            cls._environment_note(),
            "Documents the user will keep editing fit artifact_generator (if available) better.",
            cls._closing_rule(),
        ]
        return "\n".join(line for line in lines if line)

    def _environment_summary(self) -> str:
        """Return the compact environment summary a new session's first result carries."""
        timeout = int(self._exec_timeout())
        max_timeout = int(self._max_exec_timeout())
        idle = self._idle_minutes()
        if self._full_image():
            return manifest.environment_summary(timeout=timeout, idle_minutes=idle, max_timeout=max_timeout)
        return (
            "Python with only the stdlib preinstalled; pip install what you need. Working directory = workspace: "
            "files there become downloads, except scratch/; inputs/ holds passed files; /tmp is not kept. "
            f"Limits: {timeout}s per call by default, `timeout` up to {max_timeout}s; resets after {idle} min idle."
        )

    def get_actions_metadata(self) -> List[Dict[str, Any]]:
        """Return JSON metadata describing the ``run_code`` action for tool schemas."""
        return [
            {
                "name": "run_code",
                "description": self._description(),
                "active": True,
                "require_approval": self._require_approval,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Python source to run in the session. If a package really is "
                            "missing, pip install it from within this code (e.g. with subprocess) before importing it.",
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
                        "timeout": {
                            "type": "integer",
                            "description": self._timeout_parameter_description(),
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

    @classmethod
    def _timeout_parameter_description(cls) -> str:
        """Describe the ``timeout`` argument, with rough budgets so the model can pick a value."""
        return (
            f"Wall-clock seconds for this call (default {int(cls._exec_timeout())}, max "
            f"{int(cls._max_exec_timeout())}). Raise it only for long jobs; rough budgets: pip install of a big "
            "package ~120, office-convert of a large deck ~120, OCR ~2-3 per page, video render scales with frames."
        )

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
        timeout, clamped = self._requested_timeout(kwargs.get("timeout"))
        inputs = kwargs.get("inputs") or []

        manager = SandboxCreator.get_manager()
        try:
            opened = manager.open_session(session_id, ttl=open_ttl)
        except Exception as exc:
            logger.exception("code_executor: failed to open sandbox session")
            return {"status": "error", "error": f"sandbox unavailable: {type(exc).__name__}: {exc}"}
        # Tells the model whether earlier files/installs/variables can still be there.
        session_state = "new" if opened.created else "reused"
        if opened.created:
            self._make_scratch_dir(manager, session_id)

        detached_run = False
        try:
            materialized = self._materialize_inputs(manager, session_id, inputs)
            if materialized.get("error"):
                return {"status": "error", "error": materialized["error"], "session": session_state}

            pre_signatures: Dict[str, Tuple[int, Optional[str]]] = {}
            if should_capture:
                pre_signatures = self._snapshot_signatures(manager, session_id)

            run = PreparedRun(
                session_id=session_id,
                code=code,
                timeout=timeout,
                clamped=clamped,
                asked_timeout=self._timeout_number(kwargs.get("timeout")) if clamped else None,
                should_capture=bool(should_capture),
                outputs=outputs,
                pre_signatures=pre_signatures,
                inputs_loaded=list(materialized.get("loaded", [])),
                session_created=bool(opened.created),
                keep_alive=keep_alive,
            )
            call = self._background_call()
            run.background_capable = call is not None
            run.background = bool(call is not None and call.explicit)
            if call is not None and self._can_detach(manager, call):
                outcome = self._run_detached(manager, run, call)
                if outcome is detached_marker():
                    # A background job's poller finishes this run, and closes the session if asked.
                    detached_run = True
                    return outcome
                if isinstance(outcome, dict):
                    return outcome
                result = outcome
            else:
                try:
                    result = manager.exec(session_id, code, timeout=timeout)
                except Exception as exc:
                    logger.exception("code_executor: exec raised")
                    return {
                        "status": "error",
                        "error": f"execution failed: {type(exc).__name__}: {exc}",
                        "session": session_state,
                    }
            # A run the turn handed off while it ran is finished here, as a background job.
            if call is not None and call.handoff_requested():
                run.background = True
            return self.finish_run(manager, run, result)
        finally:
            if not keep_alive and not detached_run:
                try:
                    manager.close(session_id)
                except Exception:
                    logger.exception("code_executor: session close failed")

    def finish_run(self, files: Any, run: "PreparedRun", result: ExecResult) -> Dict[str, Any]:
        """Turn a finished run into the model's payload: capture its files, show its charts, add hints.

        Shared by a run that finished in the turn and one a background job's
        poller finished in another process, so both report the same payload.

        Args:
            files: The session's file access (the manager, or an adopted backend).
            run: The run as prepared.
            result: What the run returned.

        Returns:
            The payload the model sees.
        """
        # Capture even on error/timeout while the runtime remains reachable
        # so partial outputs aren't lost; capture never masks the run status.
        artifacts: List[Dict[str, Any]] = []
        if run.should_capture and not result.runtime_invalidated:
            try:
                artifacts = self._capture_artifacts(files, run.session_id, run.pre_signatures, run.outputs)
            except Exception:
                logger.exception("code_executor: artifact capture failed")
        # A run that saved an image file (savefig) already gave the user its chart;
        # saving the displayed copy as well left a duplicate ``chart-<sha8>.png``.
        saved_image = any(str(a.get("mime_type") or "").startswith("image/") for a in artifacts)
        charts = self._show_charts(result, run.should_capture and not saved_image)

        payload = self._shape_payload(
            result,
            artifacts + charts,
            run.inputs_loaded,
            session="new" if run.session_created else "reused",
            environment=self._environment_summary() if run.session_created else None,
            timeout=run.timeout,
            background_capable=run.background_capable,
            background=run.background,
        )
        if run.clamped:
            payload["timeout"] = f"ran with {int(run.timeout)}s, the maximum; {run.asked_timeout}s was asked for"
        if self._native_queue:
            payload["charts_shown"] = [part["label"] for part in self._native_queue]
        hints = self._hints(
            run.session_id,
            run.code,
            result,
            artifacts + charts,
            run.session_created,
            run.timeout,
            run.should_capture,
            background=run.background,
        )
        if hints:
            payload["hint"] = hints
        return payload

    # ------------------------------------------------------------------
    # Detached runs (background jobs)
    # ------------------------------------------------------------------
    @staticmethod
    def _background_call() -> Any:
        """The background call this run belongs to, when the turn may hand it off."""
        from docsgpt.background.handoff import current_call

        return current_call()

    def supports_detached(self) -> bool:
        """Whether this deployment's sandbox can run code detached (a background job survives the turn)."""
        try:
            return SandboxCreator.get_manager().supports_detached()
        except Exception:
            return False

    def _can_detach(self, manager: Any, call: Any) -> bool:
        """Run detached on Daytona always (no kernel state to lose); on Jupyter only for ``background``.

        A Jupyter run in the kernel keeps its variables for the next call, so
        only an explicit background run gives that up for a separate process.
        """
        if not manager.supports_detached():
            return False
        return self._backend() == "daytona" or bool(getattr(call, "explicit", False))

    def _run_detached(self, manager: Any, run: "PreparedRun", call: Any) -> Any:
        """Start the run detached and follow it until it ends or the turn hands it off.

        Args:
            manager: The sandbox manager.
            run: The prepared run.
            call: The background call handle.

        Returns:
            The ``ExecResult`` of a run that ended here, the detached marker when a
            background job took it over, or an error payload when it could not start.
        """
        try:
            handle = manager.start_detached(run.session_id, run.code, run.timeout, call.key)
        except Exception as exc:
            logger.exception("code_executor: detached start failed")
            return {
                "status": "error",
                "error": f"execution failed: {type(exc).__name__}: {exc}",
                "session": "new" if run.session_created else "reused",
            }
        # Tight polls first, so a short run returns about as soon as a foreground one would.
        interval = 0.05
        failures = 0
        # The wrapper enforces the run's own cap; this bounds a poll loop whose sandbox stopped answering.
        deadline = time.monotonic() + float(run.timeout) + 60
        while True:
            if call.handoff_requested() and call.detach(self._detached_state(run, handle)):
                return detached_marker()
            try:
                state = manager.poll_detached(run.session_id, handle)
                failures = 0
            except Exception:
                failures += 1
                logger.warning("code_executor: polling a detached run failed (%d)", failures, exc_info=True)
                if failures >= 5:
                    self._cancel_quietly(manager, run, handle)
                    return ExecResult(
                        status="error",
                        error_name="SandboxError",
                        error_value="lost contact with the sandbox while the code ran",
                        exit_code=-1,
                    )
            else:
                if state.done and state.result is not None:
                    return state.result
            if time.monotonic() > deadline:
                self._cancel_quietly(manager, run, handle)
                return ExecResult(
                    status="error", error_name="TimeoutError", error_value=f"execution exceeded {int(run.timeout)}s",
                    exit_code=-1,
                )
            call.wait(interval)
            interval = min(interval * 1.3, 1.0)

    @staticmethod
    def _cancel_quietly(manager: Any, run: "PreparedRun", handle: Dict[str, Any]) -> None:
        try:
            manager.cancel_detached(run.session_id, handle)
        except Exception:
            logger.warning("code_executor: stopping a detached run failed", exc_info=True)

    def _detached_state(self, run: "PreparedRun", handle: Dict[str, Any]) -> Dict[str, Any]:
        """What a poller in another process needs to finish this run: the handle, the run, this tool."""
        config = {
            key: self.config.get(key)
            for key in ("tool_id", "conversation_id", "workflow_run_id", "message_id", "require_approval")
            if self.config.get(key) is not None
        }
        return {
            "session_id": run.session_id,
            "run": handle,
            "finish": run.to_state(),
            "tool": {"config": config, "user_id": self.user_id},
        }

    @staticmethod
    def _make_scratch_dir(manager: Any, session_id: str) -> None:
        """Create ``scratch/`` in a new session's workspace.

        The description sends previews there, and commands such as pdftoppm fail
        on an output directory that does not exist.
        """
        try:
            manager.put_file(session_id, "scratch/.keep", b"")
        except Exception:
            logger.warning("code_executor: could not create scratch/ in the workspace", exc_info=True)

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

    def _hints(
        self,
        session_id: str,
        code: str,
        result: ExecResult,
        artifacts: List[Dict[str, Any]],
        session_new: bool,
        timeout: float,
        capture: Any,
        background: bool = False,
    ) -> List[str]:
        """Return the fix hints for this run, the repeated-failure warning first.

        Args:
            session_id: The sandbox session, which keys the repeated-failure memory.
            code: The submitted source.
            result: The run's result.
            artifacts: References of the files and charts the run saved.
            session_new: The call started a fresh session.
            timeout: The per-call cap in seconds.
            capture: The call's ``capture_artifacts`` flag.
            background: The run was a background job.

        Returns:
            At most ``MAX_HINTS`` short hints.
        """
        facts = RunFacts(
            code=code,
            result=result,
            artifacts=artifacts,
            session_new=session_new,
            backend=self._backend(),
            full_image=self._full_image(),
            timed_out=not result.ok and self._is_timeout(result),
            timeout=int(timeout),
            max_timeout=int(self._max_exec_timeout()),
            app_hosts=self._app_hosts(),
            capture=bool(capture),
            charts_shown=len(self._native_queue),
            background=background,
        )
        try:
            hints = fix_hints(facts)
        except Exception:
            logger.exception("code_executor: building fix hints failed")
            hints = []
        if _FAILURES.repeated(session_id, error_signature(result)):
            hints = [REPEATED_FAILURE_HINT, *hints]
        return hints[:MAX_HINTS]

    def _shape_payload(
        self,
        result: ExecResult,
        artifacts: List[Dict[str, Any]],
        inputs_loaded: List[str],
        session: Optional[str] = None,
        environment: Optional[str] = None,
        timeout: Optional[float] = None,
        background_capable: bool = False,
        background: bool = False,
    ) -> Dict[str, Any]:
        """Build the compact LLM-facing payload; raw bytes never appear here.

        Output is cleaned (colour codes and pip's routine lines removed) before it
        is tailed, so the tail holds what the model needs.

        Args:
            result: The run's result.
            artifacts: References of the files and charts the run saved.
            inputs_loaded: Workspace paths the inputs were staged at.
            session: ``"new"`` or ``"reused"``, reported right after the status.
            environment: The environment summary, given for a new session only.
            timeout: The cap this call ran with; the default cap when None.
            background_capable: The turn could hand the run off as a background job.
            background: The run was a background job.

        Returns:
            The payload the model sees.
        """
        status = "ok" if result.ok else "error"
        payload: Dict[str, Any] = {"status": status}
        if session is not None:
            payload["session"] = session
        if environment:
            payload["environment"] = environment
        payload["stdout_tail"] = _tail(clean_output(result.stdout))
        payload["artifacts"] = artifacts
        stderr_tail = _tail(clean_output(result.stderr))
        if stderr_tail:
            payload["stderr_tail"] = stderr_tail
        if not result.ok:
            if result.out_of_memory:
                payload["error"] = self._out_of_memory_text(result)
            elif self._is_timeout(result):
                payload["error"] = self._timeout_text(
                    timeout, background_capable=background_capable, background=background
                )
            else:
                payload["error"] = self._error_text(result)
        if inputs_loaded:
            payload["inputs_loaded"] = inputs_loaded
        return payload

    @classmethod
    def _timeout_text(
        cls, timeout: Optional[float], *, background_capable: bool = False, background: bool = False
    ) -> str:
        """Explain a run that hit its wall-clock cap, and how to give the work more room.

        A run that was already a background job is reported, not retried: it
        may have done part of its work, and nobody is in the turn to agree to
        a second run.

        Args:
            timeout: The cap the run had; the default cap when None.
            background_capable: The turn can run code as a background job, which
                beats a hand-rolled background process polled with more calls.
            background: The run was a background job.

        Returns:
            The error line the model sees.
        """
        cap = int(timeout if timeout is not None else cls._exec_timeout())
        most = int(cls._max_exec_timeout())
        if background:
            return (
                f"The background run hit its {cap}s timeout and was stopped; what it did before then may have "
                "taken effect. Tell the user how far it got; run it again only if the user asks, with a `timeout` "
                "above the expected duration."
            )
        if background_capable:
            background = (
                "run it again with background=true and a larger `timeout`: it then runs as a background job and "
                "you are resumed with its result when it ends."
            )
        else:
            background = (
                "start it in the background (e.g. launch a subprocess or `nohup ... &` and write progress to a "
                "file) and return immediately, then poll with additional run_code calls to check on it. The "
                "session, with the background process and its files, stays alive between calls unless you pass "
                "persist=false."
            )
        if cap < most:
            return (
                f"Execution timed out after {cap}s. If the work needs longer, pass a larger `timeout` (up to "
                f"{most}s); otherwise split it into smaller calls, or {background}"
            )
        return f"Execution timed out at the {cap}s maximum. Split the work into smaller calls, or {background}"

    @staticmethod
    def _out_of_memory_text(result: ExecResult) -> str:
        """Explain a run whose process the sandbox killed for using too much memory."""
        detail = clean_output(result.error_value).strip()
        text = "Out of memory: the process was killed because it used more memory than the sandbox allows."
        if detail:
            text += f" ({detail[:300]})"
        return text

    @staticmethod
    def _error_text(result: ExecResult) -> str:
        """Name a failed run's error in one bounded line.

        Daytona reports every failure as ``ExecutionError`` with the whole output as
        its message; the output is already in ``stdout_tail``, so the exception on
        its last traceback line is named instead.
        """
        if result.error_name in GENERIC_ERROR_NAMES:
            name, message = exception_of(result)
            if name and name not in GENERIC_ERROR_NAMES:
                text = f"{name}: {message}" if message else name
            else:
                text = f"{result.error_name}: exited with code {result.exit_code}"
        elif result.error_name:
            text = f"{result.error_name}: {clean_output(result.error_value)}"
        else:
            text = clean_output(result.error_value) or "execution error"
        text = text.strip()
        if len(text) > _ERROR_MAX_CHARS:
            text = text[:_ERROR_MAX_CHARS] + " [...]"
        return text

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
        """Return the default per-run wall-clock cap (SANDBOX_EXEC_TIMEOUT)."""
        return float(settings.SANDBOX_EXEC_TIMEOUT)

    @classmethod
    def _max_exec_timeout(cls) -> float:
        """Return the longest cap a call may ask for (SANDBOX_EXEC_MAX_TIMEOUT, never below the default)."""
        return max(float(settings.SANDBOX_EXEC_MAX_TIMEOUT), cls._exec_timeout())

    @classmethod
    def _requested_timeout(cls, value: Any) -> Tuple[float, bool]:
        """Turn the call's ``timeout`` argument into the cap the run gets.

        Models send integers, floats or numeric strings. Anything else, and any
        value that is not a positive finite number, falls back to the default.

        Args:
            value: The call's ``timeout`` argument, or None.

        Returns:
            The cap in whole seconds, and True when the request was above the
            maximum and was clamped to it.
        """
        default = cls._exec_timeout()
        requested = cls._timeout_number(value)
        if requested is None:
            return default, False
        most = cls._max_exec_timeout()
        if requested > most:
            return most, True
        return float(requested), False

    @staticmethod
    def _timeout_number(value: Any) -> Optional[int]:
        """Read a positive whole number of seconds from a ``timeout`` argument, or None."""
        if isinstance(value, bool):
            return None
        if isinstance(value, str):
            value = value.strip()
        if not isinstance(value, (int, float, str)) or value == "":
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number) or number < 1:
            return None
        return int(number)

    @staticmethod
    def _is_timeout(result: ExecResult) -> bool:
        """True when a failed exec hit the sandbox's wall-clock cap.

        The Jupyter runner names it ``TimeoutError`` and the Daytona SDK raises a
        ``Daytona...TimeoutError``. A process that failed on its own
        (``ExecutionError``) or a library's timeout such as requests' ``ReadTimeout``
        is not the cap, even though its output mentions timeouts.
        """
        name = result.error_name or ""
        if name:
            return name == "TimeoutError" or (name.startswith("Daytona") and "Timeout" in name)
        value = (result.error_value or "").lower()
        return "timeout" in value or "timed out" in value

    @staticmethod
    def _app_hosts() -> Tuple[str, ...]:
        """Return this deployment's own hosts, which sandbox code cannot fetch without the user's session.

        A loopback host is kept only with its port (``localhost:7091``): code may run
        a server of its own on localhost.
        """
        hosts: List[str] = []
        for name in ("API_URL", "PUBLIC_API_BASE_URL", "OIDC_FRONTEND_URL", "CONNECTOR_REDIRECT_BASE_URI"):
            url = getattr(settings, name, None)
            if not url:
                continue
            try:
                parts = urlsplit(str(url))
                host, port = (parts.hostname or "").lower(), parts.port
            except ValueError:
                continue
            if not host:
                continue
            if host in _LOOPBACK_HOSTS:
                if port is not None:
                    hosts.append(f"{host}:{port}")
            else:
                hosts.append(host)
        return tuple(dict.fromkeys(hosts))

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
