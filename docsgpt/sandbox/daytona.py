"""Daytona Cloud sandbox: managed, strongly isolated runtimes via the Apache-2.0 Daytona SDK."""

import base64
import contextlib
import logging
import posixpath
import re
import shlex
import threading
import time
from typing import Any, Dict, Iterator, List, Optional

from docsgpt.sandbox import detached
from docsgpt.sandbox.base import (
    CodeSandbox,
    DetachedState,
    ExecResult,
    OpenedSession,
    SandboxGoneError,
)

logger = logging.getLogger(__name__)

# Per-session workspace root inside the Daytona sandbox. Relative file paths
# from LLM code and from put_file/get_file share this single directory.
_WORKSPACE_ROOT = "/home/daytona/docsgpt-sandbox"

# Session ids become filesystem path components and Daytona labels; restrict them.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Label key used to find/reattach the Daytona sandbox bound to a DocsGPT session.
_SESSION_LABEL = "docsgpt_session_id"

# Run before the code: once the code imports pyplot, ``plt.show()`` prints each
# open figure as a PNG between chart markers and closes it. Daytona's own chart
# extraction (behind the backend's show) drops bar charts and fails every run
# that shows a chart on matplotlib < 3.10; this replaces it. Shared with
# detached runs (docsgpt/sandbox/detached.py), which read charts the same way.
MAX_CHARTS = detached.MAX_CHARTS
MAX_CHART_PIXELS = detached.MAX_CHART_PIXELS
MAX_CHART_BYTES = detached.MAX_CHART_BYTES
_CHART_PRELUDE = detached.CHART_PRELUDE
_CHART_RE = detached.CHART_RE


# What the toolbox daemon answers when a code_run outlives its timeout: HTTP 408
# with this code in the body. The SDK does not wrap it, so the raw toolbox
# ApiException reaches the caller.
_EXEC_TIMEOUT_CODE = "PROCESS_EXECUTION_TIMEOUT"

# Exit codes of a process killed by SIGKILL: 128 + 9 through a shell, -9 from
# the process itself. In the sandbox that is the kernel's OOM killer; the
# timeout path answers 408 instead.
_SIGKILL_EXIT_CODES = detached.SIGKILL_EXIT_CODES

# Longest base64 script passed inline on a detached run's command line; Linux
# caps one argument at 128 KiB, so a longer script is uploaded instead.
_INLINE_SCRIPT_MAX_CHARS = 96_000


def _is_exec_timeout(exc: BaseException) -> bool:
    """True when a code_run failed because it outlived its timeout."""
    if _EXEC_TIMEOUT_CODE in str(getattr(exc, "body", "") or ""):
        return True
    return getattr(exc, "status", None) == 408


def _activity_interval(auto_stop_minutes: int) -> float:
    """Seconds between activity refreshes during a long run: a third of the auto-stop window, at least 30."""
    return max(30.0, auto_stop_minutes * 60 / 3)


class _Handle:
    """Tracks the Daytona sandbox object plus the workspace it executes in."""

    def __init__(self, sandbox: object, sandbox_id: str, workspace: str) -> None:
        self.sandbox = sandbox
        self.sandbox_id = sandbox_id
        self.workspace = workspace


class DaytonaSandbox(CodeSandbox):
    """Drives Daytona Cloud as a REST client; one managed sandbox per session.

    Exec is STATELESS per call: Daytona's ``process.code_run`` runs each snippet
    in a fresh Python interpreter, so Python variables and imports do NOT persist
    across ``exec`` calls (unlike the Jupyter backend's stateful kernel). What
    DOES persist is the sandbox FILESYSTEM: the per-session workspace and any
    files written there survive between calls, so ``put_file``/``get_file`` and
    files produced by one ``exec`` are visible to the next. ``attach`` therefore
    always returns the same warm sandbox (filesystem state intact, interpreter
    state lost). Matplotlib charts emitted by ``code_run`` are captured as PNG
    plots. The app is a CLIENT of Daytona Cloud, authenticated by an API key.

    Each cloud sandbox carries a ``docsgpt_session_id`` label. ``open``/``attach``
    read that label to reattach to a still-live sandbox after a process restart
    rather than creating a duplicate and orphaning the old (paid) one. A
    ``max_sandboxes`` cap bounds concurrent live sandboxes as a cost-DoS guard.
    """

    def __init__(
        self,
        api_key: str,
        api_url: Optional[str] = None,
        target: Optional[str] = None,
        snapshot: Optional[str] = None,
        language: str = "python",
        default_timeout: float = 60.0,
        create_timeout: float = 60.0,
        auto_stop_interval: int = 15,
        auto_delete_interval: int = 60,
        max_output_bytes: int = 0,
        max_file_bytes: int = 10 * 1024 * 1024,
        max_sandboxes: int = 50,
    ) -> None:
        """Configure the Daytona client; no cloud sandbox is created until ``open``."""
        if not api_key:
            raise ValueError("DAYTONA_API_KEY is required for the daytona sandbox backend")
        # Imported lazily so app import never depends on the optional SDK.
        from daytona import Daytona, DaytonaConfig

        config_kwargs: Dict[str, object] = {"api_key": api_key}
        if api_url:
            config_kwargs["api_url"] = api_url
        if target:
            config_kwargs["target"] = target
        self._client = Daytona(DaytonaConfig(**config_kwargs))
        self._snapshot = snapshot
        self._language = language
        self._default_timeout = default_timeout
        self._create_timeout = create_timeout
        self._auto_stop_interval = auto_stop_interval
        self._auto_delete_interval = auto_delete_interval
        self._max_output_bytes = max_output_bytes
        self._max_file_bytes = max_file_bytes
        self._max_sandboxes = max_sandboxes
        self._handles: Dict[str, _Handle] = {}
        self._lock = threading.Lock()
        # Session ids with a create/reattach in flight; a concurrent open() for the
        # same id waits here and reuses the result, so two threads never create (and
        # pay for) two cloud sandboxes for one session.
        self._creating: set = set()
        self._create_cv = threading.Condition(self._lock)

    # -- Helpers ---------------------------------------------------------

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        """Reject session ids that would not be a safe path component or label value."""
        if not _SESSION_ID_RE.match(session_id):
            raise ValueError(f"Invalid session id {session_id!r}: expected [A-Za-z0-9_-]+")

    def _get_handle(self, session_id: str) -> _Handle:
        with self._lock:
            handle = self._handles.get(session_id)
        if handle is None:
            raise KeyError(f"No sandbox session open for {session_id!r}")
        return handle

    @staticmethod
    def _remote_path(workspace: str, rel_path: str) -> str:
        """Join a workspace-relative path, rejecting absolute paths, NUL/control chars, or traversal."""
        if any(ord(ch) < 0x20 or ch == "\x7f" for ch in rel_path):
            raise ValueError("path contains NUL or control characters")
        if rel_path.startswith("/"):
            raise ValueError("absolute paths are not allowed")
        root = posixpath.normpath(workspace)
        resolved = posixpath.normpath(posixpath.join(root, rel_path))
        if resolved != root and not resolved.startswith(root + "/"):
            raise ValueError("path escapes the session workspace")
        return resolved

    # -- Lifecycle -------------------------------------------------------

    def open(self, session_id: str) -> str:
        """Reattach to or create the Daytona sandbox for ``session_id``; see ``open_session``.

        Returns:
            str: The live sandbox id, already registered for this session.
        """
        return self.open_session(session_id).handle

    def open_session(self, session_id: str) -> OpenedSession:
        """Reattach to or create the Daytona sandbox for ``session_id`` and prime its workspace.

        Reattach order: an in-memory handle, then (across process restarts) a live cloud
        sandbox carrying the session label, and only then a fresh ``create``. Enforces
        ``max_sandboxes`` so a flood of sessions cannot run up unbounded paid resources.

        Returns:
            OpenedSession: The live sandbox id, already registered for this session, and
            ``created`` True only for a fresh ``create``. A cached or reattached sandbox
            keeps its filesystem, so it counts as reused even though every ``exec``
            starts a new interpreter.

        Raises:
            SandboxGoneError: The sandbox was confirmed gone before its workspace
                could be primed. Nothing is cached, so a retry cold-starts.
            RuntimeError: ``max_sandboxes`` live sandboxes already exist.
        """
        self._validate_session_id(session_id)
        # Wait out any in-flight create/reattach for this session, then reuse its
        # handle; otherwise claim the in-flight slot so we are the sole creator.
        with self._create_cv:
            while session_id in self._creating:
                self._create_cv.wait()
            existing = self._handles.get(session_id)
            if existing is not None:
                return OpenedSession(existing.sandbox_id, False)
            self._creating.add(session_id)
        try:
            # Cross-restart reattach: an earlier process may have created (and labelled)
            # a sandbox for this session that is still live in the cloud. Reuse it
            # instead of leaking it behind a brand-new create.
            reattached = self._reattach_existing(session_id)
            if reattached is not None:
                if self._prime(reattached):
                    return OpenedSession(reattached.sandbox_id, False)
                # The labelled sandbox is gone in the cloud (deleted between the
                # list and its first use — seen in prod as toolbox 404 "it has
                # been deleted"). Forget it and fall through to a fresh create.
                logger.warning(
                    "Reattached Daytona sandbox %s for session %s is gone; creating a fresh one",
                    reattached.sandbox_id,
                    session_id,
                )
                self._forget_handle(session_id, reattached)

            with self._lock:
                if len(self._handles) >= self._max_sandboxes:
                    raise RuntimeError(
                        f"Daytona sandbox cap reached ({self._max_sandboxes} live); refusing to create another"
                    )

            sandbox = self._create_sandbox(session_id)
            # Crash-safe register: if anything between create and registration raises,
            # delete the just-created sandbox so it cannot orphan as a paid resource.
            try:
                sandbox_id = sandbox.id
                handle = _Handle(sandbox, sandbox_id, _WORKSPACE_ROOT)
                with self._lock:
                    self._handles[session_id] = handle
            except Exception:
                try:
                    self._client.delete(sandbox)
                except Exception as del_exc:  # noqa: BLE001 - cleanup is best-effort
                    logger.warning("Failed to delete orphaned Daytona sandbox during open: %s", del_exc)
                raise
            if not self._prime(handle):
                # ``_prime`` only reports False once ``_sandbox_gone`` confirms it.
                # Caching a dead handle would be worse than failing here: ``open``
                # returns cached handles without revalidating them, so every later
                # open for this session would replay the same dead id. Forgetting
                # it does not strand a paid resource even if the classification was
                # a false positive -- the sandbox carries the session label, so
                # ``_reattach_existing`` picks it up on the next open.
                self._forget_handle(session_id, handle)
                logger.warning(
                    "Freshly created Daytona sandbox %s for session %s was gone before "
                    "its workspace could be primed; not caching it",
                    sandbox_id,
                    session_id,
                )
                raise SandboxGoneError(
                    f"Daytona sandbox {sandbox_id} vanished during workspace prime"
                )
            return OpenedSession(sandbox_id, True)
        finally:
            with self._create_cv:
                self._creating.discard(session_id)
                self._create_cv.notify_all()

    def _reattach_existing(self, session_id: str) -> Optional["_Handle"]:
        """Find a live cloud sandbox labelled for ``session_id`` and rebuild a handle from it.

        Reads the ``docsgpt_session_id`` label written at create time so a process
        restart reuses the existing sandbox rather than orphaning it. Returns ``None``
        when no live sandbox matches.
        """
        try:
            from daytona import ListSandboxesQuery, SandboxState

            query = ListSandboxesQuery(
                labels={_SESSION_LABEL: session_id},
                states=[SandboxState.STARTED, SandboxState.STOPPED],
            )
            matches = list(self._client.list(query, request_timeout=self._default_timeout))
        except Exception as exc:  # noqa: BLE001 - listing must never block opening a session
            logger.warning("Daytona list for session %s failed; will create fresh: %s", session_id, exc)
            return None

        for sandbox in matches:
            if getattr(sandbox, "labels", {}).get(_SESSION_LABEL) != session_id:
                continue
            if self._wake_if_stopped(sandbox) is None:
                continue
            handle = _Handle(sandbox, sandbox.id, _WORKSPACE_ROOT)
            with self._lock:
                self._handles[session_id] = handle
            logger.info("Reattached to existing Daytona sandbox %s for session %s", sandbox.id, session_id)
            return handle
        return None

    def _wake_if_stopped(self, sandbox: object) -> Optional[object]:
        """Start a stopped sandbox so it can serve exec/file ops; return None if it can't be woken."""
        state = getattr(sandbox, "state", None)
        state_value = getattr(state, "value", state)
        if state_value == "started":
            return sandbox
        try:
            self._client.start(sandbox, timeout=self._create_timeout)
            return sandbox
        except Exception as exc:  # noqa: BLE001 - a sandbox we can't start is unusable
            logger.warning("Failed to start stopped Daytona sandbox %s: %s", getattr(sandbox, "id", "?"), exc)
            return None

    def _ensure_started(self, handle: "_Handle") -> bool:
        """Refresh the handle's sandbox; start it if auto-stopped. True only if it was woken."""
        try:
            fresh = self._client.get(handle.sandbox_id, request_timeout=self._default_timeout)
        except Exception as exc:  # noqa: BLE001 - a failed refresh just means we don't retry
            logger.warning("Daytona get for %s failed while ensuring started: %s", handle.sandbox_id, exc)
            return False
        state = getattr(fresh, "state", None)
        state_value = getattr(state, "value", state)
        if state_value == "started":
            handle.sandbox = fresh
            return False
        if self._wake_if_stopped(fresh) is None:
            return False
        handle.sandbox = fresh
        return True

    def _create_sandbox(self, session_id: str):
        """Create a fresh Daytona sandbox labelled for ``session_id``."""
        from daytona import CreateSandboxFromSnapshotParams

        params_kwargs: Dict[str, object] = {
            "language": self._language,
            "labels": {_SESSION_LABEL: session_id},
            "auto_stop_interval": self._auto_stop_interval,
            "auto_delete_interval": self._auto_delete_interval,
        }
        if self._snapshot:
            params_kwargs["snapshot"] = self._snapshot
        params = CreateSandboxFromSnapshotParams(**params_kwargs)
        return self._client.create(params, timeout=self._create_timeout)

    def attach(self, session_id: str) -> str:
        """Reattach to the sandbox for ``session_id``; filesystem state is preserved.

        Prefers the in-memory handle, then a live labelled cloud sandbox (so a process
        restart does not orphan it), and only opens a fresh one as a last resort.
        """
        self._validate_session_id(session_id)
        with self._lock:
            existing = self._handles.get(session_id)
        if existing is not None:
            return existing.sandbox_id
        logger.warning("No live handle for session %s; reattaching or opening a Daytona sandbox", session_id)
        return self.open(session_id)

    def close(self, session_id: str) -> None:
        """Delete the Daytona sandbox for ``session_id`` so no cloud resource leaks."""
        with self._lock:
            handle = self._handles.pop(session_id, None)
        if handle is None:
            return
        self._delete_sandbox(handle)

    def close_handle(self, session_id: str, sandbox_id: str) -> None:
        """Delete the SPECIFIC sandbox captured at eviction time, never a re-opened one.

        Used when the manager evicts a session and a concurrent ``open`` of the same id
        may have already created a fresh sandbox: this tears down only the sandbox whose
        id was captured, leaving any newer registered handle untouched. Falls back to the
        registry only when nothing matches the captured id.
        """
        with self._lock:
            current = self._handles.get(session_id)
            if current is not None and current.sandbox_id == sandbox_id:
                # Captured handle is still the registered one: pop and delete it.
                self._handles.pop(session_id, None)
                victim = current
            else:
                # A concurrent re-open replaced the handle (or it is already gone); do
                # NOT touch the registry. Delete the captured sandbox by id directly so
                # the freshly created one survives.
                victim = None
        if victim is not None:
            self._delete_sandbox(victim)
        else:
            self._delete_sandbox_by_id(sandbox_id)

    def _delete_sandbox(self, handle: "_Handle") -> None:
        """Best-effort delete of the sandbox behind ``handle`` (never raises)."""
        try:
            self._client.delete(handle.sandbox)
        except Exception as exc:  # noqa: BLE001 - teardown is best-effort, never raise
            logger.warning("Failed to delete Daytona sandbox %s: %s", handle.sandbox_id, exc)

    def _delete_sandbox_by_id(self, sandbox_id: str) -> None:
        """Best-effort delete a sandbox by its id when no live handle is held (never raises).

        ``client.delete`` needs a ``Sandbox`` object, so fetch it by id first; this is the
        evict-then-concurrent-reopen path where only the captured id is still known.
        """
        try:
            sandbox = self._client.get(sandbox_id, request_timeout=self._default_timeout)
            self._client.delete(sandbox)
        except Exception as exc:  # noqa: BLE001 - teardown is best-effort, never raise
            logger.warning("Failed to delete Daytona sandbox by id %s: %s", sandbox_id, exc)

    def remove_path(self, session_id: str, path: str) -> None:
        """Best-effort delete a workspace-relative path (per-render scratch dir); never raises.

        The tools pass a token DIRECTORY (e.g. ``artifacts/{token}``), so the delete is
        recursive — ``fs.delete_file`` with ``recursive=True`` removes a folder and its
        contents (daytona==0.203.0).
        """
        try:
            handle = self._get_handle(session_id)
            remote = self._remote_path(handle.workspace, path)
            if remote == posixpath.normpath(handle.workspace):
                return  # refuse to delete the workspace root itself
            self._delete_remote(handle, remote)
        except Exception as exc:  # noqa: BLE001 - cleanup is best-effort, never raise
            logger.debug("remove_path best-effort delete returned for %r: %s", path, exc)

    def _delete_remote(self, handle: "_Handle", remote: str) -> None:
        """Recursively delete ``remote`` inside the sandbox, with a contained-command fallback."""
        try:
            handle.sandbox.fs.delete_file(remote, recursive=True, request_timeout=self._default_timeout)
            return
        except TypeError:
            # Older SDK without the recursive kwarg: fall back to a contained rm -rf.
            pass
        try:
            handle.sandbox.fs.delete_file(remote)
        except Exception:  # noqa: BLE001 - directory delete may need a recursive remove
            quoted = "'" + remote.replace("'", "'\\''") + "'"
            handle.sandbox.process.exec(f"rm -rf {quoted}", timeout=int(self._default_timeout))

    def _prime(self, handle: _Handle) -> bool:
        """Create the per-session workspace directory inside the sandbox (bounded).

        The toolbox proxy of a just-created/just-woken sandbox can accept a
        request and never answer (no container IP registered yet), and the SDK
        default is NO client timeout — in prod one hung ``create_folder`` here
        pinned a stream for ~16 minutes until the idle auto-stop dropped the
        connection. Bound the call, refresh/wake the sandbox, and retry once.

        ``create_folder`` is idempotent on an existing directory (verified
        against Daytona 0.205.1), so any failure here is real. Returns False
        when the sandbox no longer exists in the cloud — the caller must
        discard the handle and start fresh. A still-alive sandbox that fails
        to prime stays usable (True): ``exec`` prepends ``makedirs`` and
        ``put_file`` creates parent dirs, so the workspace materializes on
        first use anyway.
        """
        try:
            handle.sandbox.fs.create_folder(handle.workspace, "755", request_timeout=self._default_timeout)
            return True
        except Exception as exc:  # noqa: BLE001 - hang/transport/stopped: refresh and retry once
            logger.debug("Workspace folder prime failed; refreshing sandbox and retrying once: %s", exc)
        self._ensure_started(handle)  # refreshes the handle; wakes an auto-stopped sandbox
        try:
            handle.sandbox.fs.create_folder(handle.workspace, "755", request_timeout=self._default_timeout)
            return True
        except Exception as exc:  # noqa: BLE001 - classify gone-vs-degraded below
            if self._sandbox_gone(handle):
                logger.warning("Workspace prime found sandbox %s gone: %s", handle.sandbox_id, exc)
                return False
            logger.warning(
                "Workspace prime failed twice for live sandbox %s "
                "(continuing; exec/put_file create the workspace on demand): %s",
                handle.sandbox_id,
                exc,
            )
            return True

    # -- Execution -------------------------------------------------------

    def exec(self, session_id: str, code: str, timeout: Optional[float] = None) -> ExecResult:
        """Run ``code`` via Daytona ``code_run``; per-call interpreter, persistent filesystem."""
        handle = self._get_handle(session_id)
        wall = int(timeout or self._default_timeout)
        wrapped = self._with_workspace_cwd(handle.workspace, code)
        try:
            # code_run's own HTTP request timeout is ``wall`` plus a margin (SDK
            # 0.211, pinned by a test), so a long run never waits unbounded.
            with self._kept_active(handle, wall):
                response = handle.sandbox.process.code_run(wrapped, timeout=wall)
        except Exception as exc:  # noqa: BLE001 - any SDK/cloud error -> error result, never raise
            if _is_exec_timeout(exc):
                return self._timeout_result(wall)
            # A cached handle may point at a sandbox Daytona auto-stopped; wake it and
            # retry once. Genuine code errors return a nonzero-exit response (they do
            # NOT raise), so this only retries transport/stopped faults.
            failure: Exception = exc
            if self._ensure_started(handle):
                try:
                    with self._kept_active(handle, wall):
                        return self._to_result(handle.sandbox.process.code_run(wrapped, timeout=wall))
                except Exception as retry_exc:  # noqa: BLE001 - second failure -> error result below
                    # The retry ran on the woken sandbox; its error (a timeout, say) is the one to report.
                    if _is_exec_timeout(retry_exc):
                        return self._timeout_result(wall)
                    failure = retry_exc
            result = ExecResult(
                status="error",
                error_name=type(failure).__name__,
                error_value=str(failure) or "code_run failed",
                exit_code=-1,
            )
            # An auto-DELETED sandbox (vs a merely stopped one, handled above) can't be
            # woken and would fail every retry on this cached handle. Drop the dead
            # handle and flag the runtime invalid so SandboxManager cold-starts a fresh
            # sandbox on the next call, rather than looping on the tombstone until the
            # idle-TTL reap. Mirrors the Jupyter backend's kernel-death handling.
            if self._sandbox_gone(handle):
                self._forget_handle(session_id, handle)
                result.runtime_invalidated = True
            return result
        return self._to_result(response)

    @staticmethod
    def _timeout_result(wall: int) -> ExecResult:
        """The result of a run the toolbox stopped at its timeout."""
        return ExecResult(
            status="error", error_name="TimeoutError", error_value=f"execution exceeded {wall}s", exit_code=-1
        )

    @contextlib.contextmanager
    def _kept_active(self, handle: "_Handle", wall: int) -> Iterator[None]:
        """Refresh the sandbox's activity while a run that could outlast the auto-stop timer is in flight.

        Daytona stops a sandbox after ``auto_stop_interval`` minutes without
        activity. Its docs count SDK calls as activity but say nothing about one
        request that stays open; a live probe (SDK 0.211.2, 1-minute auto-stop,
        a 200 s code_run) saw the sandbox stay up and its activity stamped mid-run.
        Since that is not documented, a run longer than half the window also
        refreshes the activity every third of the window. A failed refresh is
        logged and ignored.

        Args:
            handle: The session's sandbox.
            wall: The run's timeout in seconds.
        """
        window = self._auto_stop_interval * 60
        refresh = getattr(handle.sandbox, "refresh_activity", None)
        if not window or wall <= window / 2 or not callable(refresh):
            yield
            return
        stop = threading.Event()
        interval = _activity_interval(self._auto_stop_interval)

        def _beat() -> None:
            while not stop.wait(interval):
                try:
                    refresh(request_timeout=self._default_timeout)
                except Exception as exc:  # noqa: BLE001 - a missed refresh must not touch the run
                    logger.warning("Daytona activity refresh failed for %s: %s", handle.sandbox_id, exc)

        beat = threading.Thread(target=_beat, daemon=True, name=f"daytona-activity-{handle.sandbox_id[:8]}")
        beat.start()
        try:
            yield
        finally:
            stop.set()
            beat.join(timeout=1)

    def _sandbox_gone(self, handle: "_Handle") -> bool:
        """True when the sandbox behind ``handle`` no longer exists in the cloud.

        Separates an auto-DELETED sandbox (unrecoverable — a fresh one must be created)
        from a transient transport blip on a still-live sandbox (retryable on the same
        handle). A ``get`` that cannot resolve the id, or a terminal state, means gone.
        """
        try:
            fresh = self._client.get(handle.sandbox_id, request_timeout=self._default_timeout)
        except Exception:  # noqa: BLE001 - unresolvable id => the sandbox is gone
            return True
        state = getattr(fresh, "state", None)
        state_value = getattr(state, "value", state)
        return state_value in (None, "destroyed", "deleted", "error", "archived")

    def _forget_handle(self, session_id: str, handle: "_Handle") -> None:
        """Drop the cached handle if it is still the registered one (ABA-safe)."""
        with self._lock:
            if self._handles.get(session_id) is handle:
                self._handles.pop(session_id, None)

    @staticmethod
    def _with_workspace_cwd(workspace: str, code: str) -> str:
        """Prepend a chdir into the session workspace so relative paths resolve there.

        Leading ``from __future__`` imports are hoisted above the prelude so they stay
        the first statements of the module (Python rejects them anywhere else).
        """
        hoisted, rest = DaytonaSandbox._split_leading_future_imports(code)
        prelude = (
            "import os as _os\n"
            f"_os.makedirs({workspace!r}, exist_ok=True)\n"
            f"_os.chdir({workspace!r})\n"
            + _CHART_PRELUDE
        )
        return hoisted + prelude + rest

    @staticmethod
    def _split_leading_future_imports(code: str) -> tuple[str, str]:
        """Split leading ``from __future__`` imports (and the blank/comment lines around them) from the rest.

        A module docstring appearing BEFORE a future import is an unsupported edge (rare in
        generated snippets); the common ``from __future__ import annotations`` first-line case
        is handled. Everything from the first real statement onward stays in ``rest``.
        """
        return detached.split_leading_future_imports(code)

    def _to_result(self, response) -> ExecResult:
        """Map a Daytona ``ExecuteResponse`` into the shared ``ExecResult`` shape.

        Caps ``stdout`` at ``max_output_bytes`` (0 = disabled) BEFORE it is also reused as
        ``error_value`` so a huge buffered response cannot propagate unbounded downstream.
        """
        exit_code = getattr(response, "exit_code", 0) or 0
        artifacts = getattr(response, "artifacts", None)
        stdout = ""
        if artifacts is not None and getattr(artifacts, "stdout", None) is not None:
            stdout = artifacts.stdout
        else:
            stdout = getattr(response, "result", "") or ""
        extra = []
        if artifacts is not None:
            extra = [getattr(chart, "png", None) for chart in getattr(artifacts, "charts", None) or []]
        return detached.result_from_output(
            stdout, exit_code, max_output_bytes=self._max_output_bytes, extra_pngs=[png for png in extra if png]
        )

    # -- Detached runs ---------------------------------------------------

    def start_detached(self, session_id: str, code: str, timeout: Optional[float], key: str) -> Dict[str, Any]:
        """Start ``code`` as its own process in a Daytona session command and return at once.

        The script is fed to ``python3`` on stdin, as ``code_run`` does, so a
        traceback names ``<stdin>`` exactly as a foreground run's does; stdout
        and stderr are merged as ``code_run`` reports them. A script too long
        for one command line is uploaded to ``scratch/jobs/<key>/main.py``
        first. Each run gets its own process session, so cancelling it
        (``delete_session``) stops only this run.

        Args:
            session_id: The DocsGPT session (sandbox) to run in.
            code: The source.
            timeout: Wall-clock cap in seconds (the default exec cap when None).
            key: A unique key for this run (the job directory and process session name).

        Returns:
            The run's handle: everything a poller in another process needs.

        Raises:
            Exception: The sandbox could not take the run (after one wake-and-retry).
        """
        handle = self._get_handle(session_id)
        wall = int(timeout or self._default_timeout)
        directory = detached.job_dir(key)
        script = detached.script_for(handle.workspace, code).encode("utf-8")
        encoded = base64.b64encode(script).decode("ascii")
        uploaded = len(encoded) > _INLINE_SCRIPT_MAX_CHARS
        run_python = f"timeout -k 5 {wall} python3 -u -"
        if uploaded:
            self.put_file(session_id, f"{directory}/main.py", script)
            pipeline = f"{run_python} < {shlex.quote(directory + '/main.py')} 2>&1"
        else:
            pipeline = f"echo {encoded} | base64 -d | {run_python} 2>&1"
        command = f"cd {shlex.quote(handle.workspace)} && {pipeline}"
        process_session = f"docsgpt-job-{key}"
        try:
            cmd_id = self._launch(handle, process_session, command)
        except Exception:
            if not self._ensure_started(handle):
                raise
            cmd_id = self._launch(handle, process_session, command)
        return {
            "backend": "daytona",
            "sandbox_id": handle.sandbox_id,
            "workspace": handle.workspace,
            "process_session": process_session,
            "cmd_id": cmd_id,
            "job_dir": directory if uploaded else None,
            "wall": wall,
            "started_at": time.time(),
        }

    def _launch(self, handle: "_Handle", process_session: str, command: str) -> str:
        """Create the run's process session and start ``command`` in it asynchronously."""
        from daytona import SessionExecuteRequest

        process = handle.sandbox.process
        process.create_session(process_session, request_timeout=self._default_timeout)
        response = process.execute_session_command(
            process_session,
            SessionExecuteRequest(command=command, run_async=True),
            timeout=int(self._default_timeout),
        )
        return str(response.cmd_id)

    def poll_detached(self, session_id: str, run: Dict[str, Any], *, with_output: bool = False) -> DetachedState:
        """Check a detached run; once it exited, read its output and clean up its process session.

        Args:
            session_id: The DocsGPT session the run belongs to.
            run: The handle ``start_detached`` returned.
            with_output: Also read the output of a run still going (watch patterns).

        Returns:
            The run's state. A sandbox that no longer exists ends the run with an error.

        Raises:
            Exception: A transient failure talking to the sandbox; poll again later.
        """
        handle = self._get_handle(session_id)
        process = handle.sandbox.process
        try:
            command = process.get_session_command(
                run["process_session"], run["cmd_id"], request_timeout=self._default_timeout
            )
        except Exception:
            if self._sandbox_gone(handle):
                self._forget_handle(session_id, handle)
                result = ExecResult(
                    status="error",
                    error_name="SandboxGoneError",
                    error_value="the sandbox running this job no longer exists",
                    exit_code=-1,
                    runtime_invalidated=True,
                )
                return DetachedState(done=True, result=result, gone=True)
            raise
        exit_code = getattr(command, "exit_code", None)
        if exit_code is None:
            output = ""
            if with_output:
                output = self._command_output(process, run)
            return DetachedState(done=False, output=detached.tail_bytes(output))
        output = self._command_output(process, run)
        result = detached.finished_result(
            output,
            exit_code,
            elapsed=time.time() - float(run.get("started_at") or 0),
            wall=float(run.get("wall") or self._default_timeout),
            max_output_bytes=self._max_output_bytes,
        )
        # Off the reply path: the turn waiting on this run should not wait for its cleanup too.
        threading.Thread(
            target=self._cleanup_detached, args=(handle, run), daemon=True, name="daytona-job-cleanup"
        ).start()
        return DetachedState(done=True, result=result, output=detached.tail_bytes(output))

    def _command_output(self, process: Any, run: Dict[str, Any]) -> str:
        """The run's merged output so far (stdout carries stderr through ``2>&1``)."""
        logs = process.get_session_command_logs(
            run["process_session"], run["cmd_id"], request_timeout=self._default_timeout
        )
        stdout = getattr(logs, "stdout", None) or ""
        stderr = getattr(logs, "stderr", None) or ""
        return stdout + stderr

    def _cleanup_detached(self, handle: "_Handle", run: Dict[str, Any]) -> None:
        """Remove a finished run's process session and script directory (best-effort)."""
        try:
            handle.sandbox.process.delete_session(run["process_session"], request_timeout=self._default_timeout)
        except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
            logger.debug("Daytona: deleting job session %s failed: %s", run.get("process_session"), exc)
        if not run.get("job_dir"):
            return
        try:
            self._delete_remote(handle, self._remote_path(handle.workspace, run["job_dir"]))
        except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
            logger.debug("Daytona: removing job dir %s failed: %s", run.get("job_dir"), exc)

    def cancel_detached(self, session_id: str, run: Dict[str, Any]) -> None:
        """Stop a detached run: deleting its process session kills the process."""
        handle = self._get_handle(session_id)
        self._cleanup_detached(handle, run)

    def refresh_activity(self, session_id: str) -> None:
        """Count a detached run's poll as sandbox activity, so auto-stop does not cut it off."""
        handle = self._get_handle(session_id)
        refresh = getattr(handle.sandbox, "refresh_activity", None)
        if callable(refresh):
            refresh(request_timeout=self._default_timeout)

    def adopt(self, session_id: str, run: Dict[str, Any]) -> Dict[str, Any]:
        """Register the sandbox a detached run lives in, without priming or creating anything.

        A poller in another process reaches the run through an adopted handle;
        it never closes it, so the session's own process keeps owning the sandbox.

        Args:
            session_id: The DocsGPT session.
            run: The run's handle (``sandbox_id``, ``workspace``).

        Returns:
            Handle fields to persist (none for Daytona).
        """
        sandbox = self._client.get(run["sandbox_id"], request_timeout=self._default_timeout)
        with self._lock:
            self._handles[session_id] = _Handle(sandbox, run["sandbox_id"], run.get("workspace") or _WORKSPACE_ROOT)
        return {}

    def release_adopted(self, session_id: str, run: Dict[str, Any]) -> None:
        """Drop an adopted handle without touching the sandbox."""
        with self._lock:
            handle = self._handles.get(session_id)
            if handle is not None and handle.sandbox_id == run.get("sandbox_id"):
                self._handles.pop(session_id, None)

    # -- File transfer ---------------------------------------------------

    def put_file(self, session_id: str, dest_path: str, data: bytes) -> None:
        """Upload ``data`` to ``dest_path`` under the session workspace, creating parent dirs."""
        handle = self._get_handle(session_id)
        remote = self._remote_path(handle.workspace, dest_path)
        parent = posixpath.dirname(remote)
        try:
            self._upload(handle, remote, parent, data)
        except Exception as exc:  # noqa: BLE001 - log detail server-side, return a generic error
            # A cached handle may point at an auto-stopped sandbox; wake it and retry once.
            if self._ensure_started(handle):
                try:
                    self._upload(handle, remote, parent, data)
                    return
                except Exception:  # noqa: BLE001 - second failure -> generic IOError below
                    pass
            self._raise_file_error("put_file", dest_path, session_id, handle, exc)

    def _upload(self, handle: "_Handle", remote: str, parent: str, data: bytes) -> None:
        """Create the parent folder (best-effort) and upload ``data`` to ``remote``."""
        if parent and parent != handle.workspace:
            try:
                handle.sandbox.fs.create_folder(parent, "755", request_timeout=self._default_timeout)
            except Exception as folder_exc:  # noqa: BLE001 - folder may already exist
                logger.debug("put_file parent folder create returned: %s", folder_exc)
        handle.sandbox.fs.upload_file(data, remote, timeout=int(self._default_timeout))

    def get_file(self, session_id: str, path: str) -> bytes:
        """Download ``path`` from the session workspace as bytes, capped at ``max_file_bytes``."""
        handle = self._get_handle(session_id)
        remote = self._remote_path(handle.workspace, path)
        try:
            data = self._download(handle, remote)
        except IOError:
            raise
        except Exception as exc:  # noqa: BLE001 - log detail server-side, return a generic error
            # A cached handle may point at an auto-stopped sandbox; wake it and retry once.
            if not self._ensure_started(handle):
                self._raise_file_error("get_file", path, session_id, handle, exc)
            try:
                data = self._download(handle, remote)
            except IOError:
                raise
            except Exception:  # noqa: BLE001 - second failure -> classified below
                self._raise_file_error("get_file", path, session_id, handle, exc)
        if data is None:
            raise IOError(f"get_file produced no payload for {path!r}")
        data = data if isinstance(data, bytes) else bytes(data)
        # The pre-download size guard may be skipped when get_file_info has no size;
        # enforce the cap against the actual payload so an oversized file never slips through.
        if len(data) > self._max_file_bytes:
            raise IOError(f"file too large: {len(data)} > {self._max_file_bytes} bytes")
        return data

    def _raise_file_error(self, op: str, path: str, session_id: str, handle: "_Handle", exc: Exception) -> None:
        """Classify and raise a failed file op: ``SandboxGoneError`` vs plain ``IOError``.

        A deleted-but-cached sandbox (auto-delete, or a stale reattach candidate
        the cloud list still returned) would otherwise 404 every subsequent call
        on this handle. Forget the handle so the next ``open`` reattaches or
        creates fresh, and raise ``SandboxGoneError`` so the manager drops its
        session too (the file-op mirror of ``exec``'s ``runtime_invalidated``).
        A failure on a still-live sandbox stays a plain ``IOError`` and keeps
        the handle. Always raises; error text carries only the exception type,
        never backend URLs/payloads.
        """
        logger.warning("%s failed for %r: %s", op, path, exc)
        if self._sandbox_gone(handle):
            self._forget_handle(session_id, handle)
            raise SandboxGoneError(f"{op} failed: sandbox gone ({type(exc).__name__})") from exc
        if isinstance(exc, IOError):
            raise exc
        raise IOError(f"{op} failed: {type(exc).__name__}") from exc

    def _download(self, handle: "_Handle", remote: str) -> object:
        """Fetch ``remote``'s bytes, rejecting a file whose declared size exceeds the cap."""
        info = handle.sandbox.fs.get_file_info(remote, request_timeout=self._default_timeout)
        size = getattr(info, "size", None)
        if size is not None and size > self._max_file_bytes:
            raise IOError(f"file too large: {size} > {self._max_file_bytes} bytes")
        # download_file takes its timeout positionally and dispatches on
        # isinstance(arg, int): a float would be read as a destination path.
        return handle.sandbox.fs.download_file(remote, int(self._default_timeout))

    def list_files(self, session_id: str) -> List[str]:
        """List workspace-relative file paths for ``session_id`` (recursive, never escapes the workspace)."""
        handle = self._get_handle(session_id)
        try:
            return self._list_all(handle)
        except Exception as exc:  # noqa: BLE001 - transport/stopped fault: wake and retry once
            # A cached handle may point at an auto-stopped sandbox; wake it and retry once.
            if self._ensure_started(handle):
                try:
                    return self._list_all(handle)
                except Exception:  # noqa: BLE001 - second failure -> classified below
                    pass
            self._raise_file_error("list_files", ".", session_id, handle, exc)

    def _list_all(self, handle: "_Handle") -> List[str]:
        """Walk the workspace subtree for ``handle`` and return workspace-relative file paths."""
        out: List[str] = []
        self._walk(handle.sandbox, handle.workspace, "", out)
        return out

    def _walk(self, sandbox: object, root: str, rel_dir: str, out: List[str]) -> None:
        """Recurse one workspace subtree, appending workspace-relative file paths to ``out``."""
        abs_dir = posixpath.join(root, rel_dir) if rel_dir else root
        try:
            entries = sandbox.fs.list_files(abs_dir, request_timeout=self._default_timeout)
        except Exception as exc:  # noqa: BLE001 - log detail server-side, return a generic error
            logger.warning("list_files failed for %r: %s", rel_dir or ".", exc)
            raise IOError(f"list_files failed: {type(exc).__name__}") from exc
        for entry in entries or []:
            name = getattr(entry, "name", None)
            if not name:
                continue
            child_rel = posixpath.join(rel_dir, name) if rel_dir else name
            # Defend against a backend returning ".."/absolute entries that would escape root.
            resolved = posixpath.normpath(posixpath.join(root, child_rel))
            if resolved != root and not resolved.startswith(root + "/"):
                continue
            if getattr(entry, "is_dir", False):
                self._walk(sandbox, root, child_rel, out)
            else:
                out.append(child_rel)
