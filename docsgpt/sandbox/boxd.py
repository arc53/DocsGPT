"""boxd sandbox: one isolated boxd machine (a microVM) per session, through the ``boxd`` Python SDK."""

import base64
import json
import logging
import posixpath
import re
import secrets
import shlex
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from docsgpt.sandbox import detached
from docsgpt.sandbox.base import (
    CodeSandbox,
    DetachedState,
    ExecResult,
    FileTooLargeError,
    OpenedSession,
    SandboxGoneError,
)

logger = logging.getLogger(__name__)

# Per-session workspace root inside the machine. Relative file paths from LLM
# code and from put_file/get_file share this single directory.
_WORKSPACE_ROOT = "/home/boxd/docsgpt-sandbox"

# Session ids become filesystem path components and machine labels; restrict them.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Label key used to find/reattach the machine bound to a DocsGPT session.
_SESSION_LABEL = "docsgpt_session_id"

# Machine names: lowercase letters, digits and hyphens.
_NAME_PREFIX_RE = re.compile(r"[^a-z0-9-]+")

# Longest base64 script passed inline on a command line; Linux caps one
# argument at 128 KiB, so a longer script is uploaded instead.
_INLINE_SCRIPT_MAX_CHARS = 96_000

# Seconds the SDK call may outlast the in-machine ``timeout`` before the
# transport gives up on it.
_EXEC_MARGIN = 30

# Machine states that will never run code again.
_GONE_STATES = ("destroyed", "failed")

# The machine image's Python is the distribution's (PEP 668): pip installs
# into the user's site only with this set. Exported at the start of every
# command, so each process in a pipeline inherits it.
_RUN_ENV = "export PIP_BREAK_SYSTEM_PACKAGES=1 MPLBACKEND=Agg PYTHONUNBUFFERED=1; "

_JOB_BEGIN = "<<<DOCSGPT_JOB_BEGIN>>>"
_JOB_END = "<<<DOCSGPT_JOB_END>>>"


def _status(machine: object) -> str:
    """A machine's status as a plain lowercase string."""
    status = getattr(machine, "status", None)
    return str(getattr(status, "value", status) or "").lower()


# Most bytes of a run's merged output read back: the output cap plus room for
# the charts the run may print, which are taken out of the output before it is capped.
_CHART_ROOM = detached.MAX_CHARTS * (detached.MAX_CHART_BYTES * 4 // 3 + 64) + 64 * 1024


class _Handle:
    """Tracks the boxd machine id plus the workspace it executes in."""

    def __init__(self, machine_id: str, workspace: str) -> None:
        self.machine_id = machine_id
        self.workspace = workspace
        # When the machine's delete-after timer was last pushed forward (monotonic); 0 = never.
        self.kept_at = 0.0


class BoxdSandbox(CodeSandbox):
    """Drives boxd as an SDK client; one isolated machine per session.

    Exec is STATELESS per call, as on Daytona: each snippet runs in a fresh
    ``python3`` process, so Python variables and imports do NOT persist across
    ``exec`` calls. The machine's FILESYSTEM persists: the per-session workspace,
    files written there and ``pip install``-ed packages survive between calls.
    Matplotlib charts are captured as PNG plots through the shared chart prelude.

    Machines are created with ``isolated=True`` (the code is untrusted) and carry
    a ``docsgpt_session_id`` label, which ``open``/``attach`` read to reattach to
    a still-live machine after a process restart rather than creating a
    duplicate. A ``max_machines`` cap bounds concurrent machines as a cost guard.

    With ``delete_after`` set, every machine carries a boxd delete-after timer that
    each use pushes forward, so a machine no process uses any more (its session
    released, or its process gone) is deleted by boxd that long after its last use.
    """

    def __init__(
        self,
        api_key: str,
        org: Optional[str] = None,
        region: Optional[str] = None,
        name_prefix: str = "docsgpt",
        default_timeout: float = 60.0,
        create_timeout: float = 90.0,
        max_output_bytes: int = 0,
        max_file_bytes: int = 10 * 1024 * 1024,
        max_machines: int = 50,
        delete_after: int = 0,
    ) -> None:
        """Configure the boxd client; no machine is created until ``open``.

        Args:
            api_key: boxd API key (``BOXD_API_KEY``).
            org: Organization the machines are created in; the key's own when None.
            region: boxd region (``fra``, ``nyc``); the account default when None.
            name_prefix: Machine names start with this, followed by a random suffix.
            default_timeout: Wall-clock cap (s) of a run, and of control calls.
            create_timeout: Seconds to wait for a new machine to become ready.
            max_output_bytes: Cap on a run's merged output (0 disables).
            max_file_bytes: Cap on a file read back with ``get_file``.
            max_machines: Cap on machines this process holds at once.
            delete_after: Seconds after its last use that boxd deletes a machine; 0 disables.
        """
        if not api_key:
            raise ValueError("BOXD_API_KEY is required for the boxd sandbox backend")
        # Imported lazily so app import never depends on the SDK.
        from boxd import Boxd

        self._client = Boxd(api_key=api_key, region=region or None)
        self._org = org or None
        prefix = _NAME_PREFIX_RE.sub("-", (name_prefix or "docsgpt").lower())[:40].strip("-")
        self._name_prefix = prefix or "docsgpt"
        self._default_timeout = default_timeout
        self._create_timeout = create_timeout
        self._max_output_bytes = max_output_bytes
        self._max_file_bytes = max_file_bytes
        self._max_machines = max_machines
        self._delete_after = max(0, int(delete_after or 0))
        self._handles: Dict[str, _Handle] = {}
        self._lock = threading.Lock()
        # Session ids with a create/reattach in flight; a concurrent open() for the
        # same id waits here and reuses the result, so two threads never create two
        # machines for one session.
        self._creating: set[str] = set()
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

    def _machine_name(self) -> str:
        """A fresh machine name: the prefix and a random suffix (the session is in the label)."""
        return f"{self._name_prefix}-{secrets.token_hex(4)}"

    # -- Lifecycle -------------------------------------------------------

    def open(self, session_id: str) -> str:
        """Reattach to or create the machine for ``session_id``; see ``open_session``.

        Returns:
            str: The machine id, already registered for this session.
        """
        return self.open_session(session_id).handle

    def open_session(self, session_id: str) -> OpenedSession:
        """Reattach to or create the machine for ``session_id`` and prime its workspace.

        Reattach order: an in-memory handle, then (across process restarts) a live
        machine carrying the session label, and only then a fresh ``create``.

        Args:
            session_id: The session to open.

        Returns:
            OpenedSession: The machine id and ``created`` True only for a fresh machine.

        Raises:
            SandboxGoneError: The machine was confirmed gone before its workspace
                could be primed. Nothing is cached, so a retry cold-starts.
            RuntimeError: ``max_machines`` machines are already held.
        """
        self._validate_session_id(session_id)
        with self._create_cv:
            while session_id in self._creating:
                self._create_cv.wait()
            existing = self._handles.get(session_id)
            if existing is not None:
                return OpenedSession(existing.machine_id, False)
            self._creating.add(session_id)
        try:
            reattached = self._reattach_existing(session_id)
            if reattached is not None:
                self._keep(reattached, force=True)
                if self._prime(reattached):
                    return OpenedSession(reattached.machine_id, False)
                logger.warning(
                    "Reattached boxd machine %s for session %s is gone; creating a fresh one",
                    reattached.machine_id,
                    session_id,
                )
                self._forget_handle(session_id, reattached)

            with self._lock:
                if len(self._handles) >= self._max_machines:
                    raise RuntimeError(
                        f"boxd machine cap reached ({self._max_machines} live); refusing to create another"
                    )

            machine_id = self._create_machine(session_id)
            handle = _Handle(machine_id, _WORKSPACE_ROOT)
            handle.kept_at = time.monotonic() if self._delete_after else 0.0
            with self._lock:
                self._handles[session_id] = handle
            if not self._prime(handle):
                self._forget_handle(session_id, handle)
                raise SandboxGoneError(f"boxd machine {machine_id} vanished during workspace prime")
            return OpenedSession(machine_id, True)
        finally:
            with self._create_cv:
                self._creating.discard(session_id)
                self._create_cv.notify_all()

    def _create_machine(self, session_id: str) -> str:
        """Create an isolated machine labelled for ``session_id`` and wait until it runs code.

        A machine that does not become ready is deleted again, so a failed open
        never leaves one behind.

        Returns:
            str: The new machine's id.
        """
        machine = self._client.machines.create(
            self._machine_name(),
            org=self._org,
            isolated=True,
            labels={_SESSION_LABEL: session_id},
            # Idle time is measured on network traffic, and a long CPU-bound run
            # has none; the session TTL decides when the machine goes away.
            auto_suspend_timeout=0,
            **({"delete_after": self._delete_after} if self._delete_after else {}),
        )
        machine_id = machine.id
        try:
            self._client.machines.wait_until_ready(machine_id, timeout=self._create_timeout)
        except Exception:
            self._delete_machine_by_id(machine_id)
            raise
        logger.info("Created boxd machine %s for session %s", machine_id, session_id)
        return machine_id

    def _reattach_existing(self, session_id: str) -> Optional[_Handle]:
        """Find a live machine labelled for ``session_id`` and rebuild a handle from it.

        Returns ``None`` when no usable machine matches; listing never blocks an open.
        """
        try:
            matches = list(self._client.machines.list(org=self._org, labels={_SESSION_LABEL: session_id}))
        except Exception as exc:  # noqa: BLE001 - listing must never block opening a session
            logger.warning("boxd list for session %s failed; will create fresh: %s", session_id, exc)
            return None
        for machine in matches:
            if (getattr(machine, "labels", None) or {}).get(_SESSION_LABEL) != session_id:
                continue
            if _status(machine) in _GONE_STATES:
                continue
            handle = _Handle(machine.id, _WORKSPACE_ROOT)
            with self._lock:
                self._handles[session_id] = handle
            logger.info("Reattached to existing boxd machine %s for session %s", machine.id, session_id)
            return handle
        return None

    def _ensure_running(self, handle: _Handle) -> bool:
        """Start a stopped machine (or wake a paused one). True only if it had to be started.

        Hibernated and standby machines also wake on their own when a call reaches
        them; this covers a machine that was stopped.
        """
        try:
            machine = self._client.machines.get(handle.machine_id)
        except Exception as exc:  # noqa: BLE001 - a failed refresh just means we don't retry
            logger.warning("boxd get for %s failed while ensuring it runs: %s", handle.machine_id, exc)
            return False
        status = _status(machine)
        if status == "running" or status in _GONE_STATES:
            return False
        try:
            if status == "stopped":
                self._client.machines.start(handle.machine_id)
            elif status == "hibernated":
                self._client.machines.wake(handle.machine_id)
            elif status == "suspended":
                self._client.machines.resume(handle.machine_id)
            self._client.machines.wait_until_ready(handle.machine_id, timeout=self._create_timeout)
            return True
        except Exception as exc:  # noqa: BLE001 - a machine we can't start is unusable
            logger.warning("Failed to start boxd machine %s: %s", handle.machine_id, exc)
            return False

    def _machine_gone(self, handle: _Handle) -> bool:
        """True when the machine behind ``handle`` no longer exists (deleted, or failed for good)."""
        from boxd.errors import NotFoundError

        try:
            machine = self._client.machines.get(handle.machine_id)
        except NotFoundError:
            return True
        except Exception:  # noqa: BLE001 - unreachable is not gone: keep the handle
            return False
        return _status(machine) in _GONE_STATES

    def _forget_handle(self, session_id: str, handle: _Handle) -> None:
        """Drop the cached handle if it is still the registered one (ABA-safe)."""
        with self._lock:
            if self._handles.get(session_id) is handle:
                self._handles.pop(session_id, None)

    def _keep(self, handle: _Handle, force: bool = False) -> None:
        """Push the machine's delete-after timer forward, at most every quarter of its length.

        Best-effort: a failed refresh is logged and retried on the next use.
        """
        if not self._delete_after:
            return
        now = time.monotonic()
        if not force and handle.kept_at and now - handle.kept_at < self._delete_after / 4:
            return
        try:
            self._client.machines.set_delete_after(handle.machine_id, self._delete_after)
            handle.kept_at = now
        except Exception as exc:  # noqa: BLE001 - the next use tries again
            logger.warning("Refreshing the delete-after timer of boxd machine %s failed: %s", handle.machine_id, exc)

    def _prime(self, handle: _Handle) -> bool:
        """Create the per-session workspace and Python's user site directory inside the machine.

        Python puts the user site directory (where ``pip install`` writes) on
        ``sys.path`` only if it exists when the interpreter starts; creating it
        up front lets code import a package it pip-installed earlier in the same run.

        Retried once after making sure the machine runs. Returns False only when the
        machine no longer exists; a live machine that fails to prime stays usable,
        since every run and upload creates the workspace on demand.
        """
        command = f'mkdir -p {shlex.quote(handle.workspace)} "$(python3 -m site --user-site)"'
        for attempt in range(2):
            try:
                self._client.machines.exec(handle.machine_id, command, timeout=self._default_timeout)
                return True
            except Exception as exc:  # noqa: BLE001 - classify below
                logger.debug("Workspace prime attempt %d failed: %s", attempt + 1, exc)
                if attempt == 0:
                    self._ensure_running(handle)
        if self._machine_gone(handle):
            logger.warning("Workspace prime found boxd machine %s gone", handle.machine_id)
            return False
        return True

    def attach(self, session_id: str) -> str:
        """Reattach to the machine for ``session_id``; filesystem state is preserved."""
        self._validate_session_id(session_id)
        with self._lock:
            existing = self._handles.get(session_id)
        if existing is not None:
            return existing.machine_id
        logger.warning("No live handle for session %s; reattaching or opening a boxd machine", session_id)
        return self.open(session_id)

    def close(self, session_id: str) -> None:
        """Delete the machine for ``session_id``."""
        with self._lock:
            handle = self._handles.pop(session_id, None)
        if handle is None:
            return
        self._delete_machine_by_id(handle.machine_id)

    def close_handle(self, session_id: str, machine_id: str) -> None:
        """Delete the SPECIFIC machine captured at eviction time, never a re-opened one.

        A newer handle a concurrent ``open`` registered for the same session is left
        registered; only the captured machine is deleted.
        """
        with self._lock:
            current = self._handles.get(session_id)
            if current is not None and current.machine_id == machine_id:
                self._handles.pop(session_id, None)
        self._delete_machine_by_id(machine_id)

    def release_handle(self, session_id: str, machine_id: str) -> None:
        """Forget the local handle on ``machine_id`` without deleting the machine.

        Another process may have reattached the same machine by its label and still
        be using it; the manager deletes it separately once no process has used it
        for its TTL.
        """
        with self._lock:
            current = self._handles.get(session_id)
            if current is not None and current.machine_id == machine_id:
                self._handles.pop(session_id, None)

    def _delete_machine_by_id(self, machine_id: str) -> None:
        """Best-effort delete of a machine by id (never raises)."""
        try:
            self._client.machines.delete(machine_id)
        except Exception as exc:  # noqa: BLE001 - teardown is best-effort, never raise
            logger.warning("Failed to delete boxd machine %s: %s", machine_id, exc)

    def remove_path(self, session_id: str, path: str) -> None:
        """Best-effort recursive delete of a workspace-relative path; never raises."""
        try:
            handle = self._get_handle(session_id)
            remote = self._remote_path(handle.workspace, path)
            if remote == posixpath.normpath(handle.workspace):
                return  # refuse to delete the workspace root itself
            self._client.machines.files.delete(handle.machine_id, remote)
        except Exception as exc:  # noqa: BLE001 - cleanup is best-effort, never raise
            from boxd.errors import NotFoundError

            if isinstance(exc, (KeyError, NotFoundError)):
                # No live handle, or the path is already gone: nothing was left behind.
                logger.debug("remove_path found nothing to delete for %r: %s", path, exc)
            else:
                logger.warning("remove_path could not delete %r in session %s: %s", path, session_id, exc)

    # -- Execution -------------------------------------------------------

    def _shell(self, handle: _Handle, command: str, timeout: float) -> Tuple[str, int]:
        """Run ``command`` in the machine and return its merged output and exit code.

        A machine that is stopped is started and the command retried once. The
        delete-after timer is pushed forward before the command and again after
        it, so a session stays its full idle TTL after a long run.

        Raises:
            Exception: The SDK error of the last attempt.
        """
        self._keep(handle)
        command = _RUN_ENV + command
        try:
            result = self._client.machines.exec(handle.machine_id, command, timeout=timeout)
        except Exception:
            # Retrying is safe: _ensure_running returns True only when the machine was
            # not running and had to be started, so the first attempt never ran the
            # command. A failure on a running machine is raised as is, not retried.
            if not self._ensure_running(handle):
                raise
            result = self._client.machines.exec(handle.machine_id, command, timeout=timeout)
        self._keep(handle)
        return (result.stdout or "") + (result.stderr or ""), int(result.exit_code)

    @staticmethod
    def _python_pipeline(script: bytes, wall: int) -> str:
        """A shell pipeline feeding ``script`` to ``python3`` on stdin under ``timeout``.

        Like a Daytona run, the traceback names ``<stdin>``. stdout and stderr are
        merged in order.
        """
        encoded = base64.b64encode(script).decode("ascii")
        return f"echo {encoded} | base64 -d | timeout -k 5 {wall} python3 -u - 2>&1"

    def exec(self, session_id: str, code: str, timeout: Optional[float] = None) -> ExecResult:
        """Run ``code`` in a fresh ``python3`` process; the workspace filesystem persists."""
        from boxd.errors import NotFoundError

        handle = self._get_handle(session_id)
        wall = int(timeout or self._default_timeout)
        script = detached.script_for(handle.workspace, code).encode("utf-8")
        cleanup = None
        if len(base64.b64encode(script)) > _INLINE_SCRIPT_MAX_CHARS:
            directory = detached.job_dir(secrets.token_hex(8))
            remote = self._remote_path(handle.workspace, f"{directory}/main.py")
            try:
                self.put_file(session_id, f"{directory}/main.py", script)
            except IOError as exc:
                return self._error_result(exc, session_id, handle)
            run_python = f"timeout -k 5 {wall} python3 -u {shlex.quote(remote)} 2>&1"
            cleanup = posixpath.dirname(remote)
        else:
            run_python = self._python_pipeline(script, wall)
        workspace = shlex.quote(handle.workspace)
        command = f"mkdir -p {workspace} && cd {workspace} || exit 1; "
        if self._max_output_bytes:
            # Bound what comes back over the wire; the run's own exit status is kept.
            limit = self._max_output_bytes + _CHART_ROOM
            command += (
                f'out=$(mktemp) || exit 1; {{ {run_python}; }} > "$out"; rc=$?; '
                f'head -c {limit} "$out"; rm -f "$out"; '
            )
        else:
            command += f"{run_python}; rc=$?; "
        if cleanup:
            command += f"rm -rf {shlex.quote(cleanup)}; "
        command += "exit $rc"
        started = time.monotonic()
        try:
            output, exit_code = self._shell(handle, command, wall + _EXEC_MARGIN)
        except NotFoundError as exc:
            return self._error_result(exc, session_id, handle)
        except Exception as exc:  # noqa: BLE001 - any SDK/cloud error -> error result, never raise
            if time.monotonic() - started >= wall and not self._machine_gone(handle):
                self._keep(handle)
                return detached.finished_result("", detached.TIMEOUT_EXIT_CODE, elapsed=wall, wall=wall)
            return self._error_result(exc, session_id, handle)
        return detached.finished_result(
            output,
            exit_code,
            elapsed=time.monotonic() - started,
            wall=wall,
            max_output_bytes=self._max_output_bytes,
        )

    def _error_result(self, exc: BaseException, session_id: str, handle: _Handle) -> ExecResult:
        """The result of a run the machine could not take; a gone machine invalidates the session."""
        result = ExecResult(
            status="error",
            error_name=type(exc).__name__,
            error_value=str(exc) or "exec failed",
            exit_code=-1,
            sandbox_error=True,
        )
        if self._machine_gone(handle):
            self._forget_handle(session_id, handle)
            result.runtime_invalidated = True
        return result

    # -- Detached runs ---------------------------------------------------

    def start_detached(self, session_id: str, code: str, timeout: Optional[float], key: str) -> Dict[str, Any]:
        """Start ``code`` as its own process group in the machine and return at once.

        The script is written to ``scratch/jobs/<key>/main.py`` and run with
        ``setsid`` so it outlives the call that launched it. Output goes to
        ``out.log`` and the exit status to ``exit`` in the job directory.

        Args:
            session_id: The DocsGPT session (machine) to run in.
            code: The source.
            timeout: Wall-clock cap in seconds (the default exec cap when None).
            key: A unique key for this run.

        Returns:
            The run's handle: everything a poller in another process needs.

        Raises:
            SandboxGoneError: The machine no longer exists; its handle is forgotten.
            IOError: The machine could not take the run.
        """
        handle = self._get_handle(session_id)
        wall = int(timeout or self._default_timeout)
        directory = detached.job_dir(key)
        job = self._remote_path(handle.workspace, directory)
        self.put_file(session_id, f"{directory}/main.py", detached.script_for(handle.workspace, code).encode("utf-8"))
        inner = (
            f'timeout -k 5 {wall} python3 -u "$1/main.py" > "$1/out.log" 2>&1; '
            'echo $? > "$1/exit.tmp" && mv "$1/exit.tmp" "$1/exit"'
        )
        command = (
            f"cd {shlex.quote(handle.workspace)} && "
            f"setsid sh -c {shlex.quote(inner)} sh {shlex.quote(job)} </dev/null >/dev/null 2>&1 & "
            f"echo {shlex.quote(_JOB_BEGIN)}$!{shlex.quote(_JOB_END)}"
        )
        try:
            output, _ = self._shell(handle, command, self._default_timeout)
        except Exception as exc:
            if self._machine_gone(handle):
                self._forget_handle(session_id, handle)
                raise SandboxGoneError(f"start_detached failed: machine gone ({type(exc).__name__})") from exc
            raise IOError(f"start_detached failed: {type(exc).__name__}") from exc
        pid = detached.decode_marker_json(output, _JOB_BEGIN, _JOB_END)
        if not pid or not pid.strip().isdigit():
            raise IOError("start_detached failed: no process id")
        return {
            "backend": "boxd",
            "machine_id": handle.machine_id,
            "workspace": handle.workspace,
            "job_dir": directory,
            "pid": int(pid),
            "wall": wall,
            "started_at": time.time(),
        }

    def poll_detached(self, session_id: str, run: Dict[str, Any], *, with_output: bool = False) -> DetachedState:
        """Check a detached run; once it exited, read its output and remove its job directory.

        Args:
            session_id: The DocsGPT session the run belongs to.
            run: The handle ``start_detached`` returned.
            with_output: Also read the output of a run still going.

        Returns:
            The run's state. A machine that no longer exists ends the run with an error.

        Raises:
            Exception: A transient failure talking to the machine; poll again later.
        """
        handle = self._get_handle(session_id)
        job = self._remote_path(handle.workspace, run["job_dir"])
        probe = (
            "import json, os\n"
            f"d = {job!r}\n"
            "code = None\n"
            "done = os.path.exists(os.path.join(d, 'exit'))\n"
            "if done:\n"
            "    try:\n"
            "        code = int(open(os.path.join(d, 'exit')).read().strip() or '0')\n"
            "    except (OSError, ValueError):\n"
            "        code = -1\n"
            "else:\n"
            "    try:\n"
            f"        os.killpg({int(run['pid'])}, 0)\n"
            "    except ProcessLookupError:\n"
            "        done, code = True, 137\n"
            "        try:\n"
            "            code = int(open(os.path.join(d, 'exit')).read().strip() or '0')\n"
            "        except (OSError, ValueError):\n"
            "            pass\n"
            "    except PermissionError:\n"
            "        pass\n"
            "tail, size = '', 0\n"
            f"if done or {bool(with_output)!r}:\n"
            "    try:\n"
            "        with open(os.path.join(d, 'out.log'), 'rb') as f:\n"
            "            f.seek(0, 2)\n"
            "            size = f.tell()\n"
            f"            f.seek(max(0, size - {detached.RUNNING_OUTPUT_BYTES}))\n"
            "            tail = f.read().decode('utf-8', 'replace')\n"
            "    except OSError:\n"
            "        pass\n"
            f"print({_JOB_BEGIN!r} + json.dumps({{'done': done, 'exit': code, 'tail': tail, 'size': size}})"
            f" + {_JOB_END!r})\n"
        )
        try:
            output, _ = self._shell(handle, self._python_pipeline(probe.encode("utf-8"), 30), self._default_timeout)
        except Exception:
            if self._machine_gone(handle):
                self._forget_handle(session_id, handle)
                result = ExecResult(
                    status="error",
                    error_name="SandboxGoneError",
                    error_value="the sandbox running this job no longer exists",
                    exit_code=-1,
                    runtime_invalidated=True,
                    sandbox_error=True,
                )
                return DetachedState(done=True, result=result, gone=True)
            raise
        payload = detached.decode_marker_json(output, _JOB_BEGIN, _JOB_END)
        if payload is None:
            raise IOError("poll_detached failed: no state")
        state = json.loads(payload)
        if not state.get("done"):
            return DetachedState(
                done=False, output=detached.tail_bytes(state.get("tail") or ""), output_size=int(state.get("size") or 0)
            )
        try:
            text = self.get_file(session_id, f"{run['job_dir']}/out.log").decode("utf-8", "replace")
        except (IOError, ValueError):
            # Too large or unreadable: the tail is what the run reports.
            text = state.get("tail") or ""
        result = detached.finished_result(
            text,
            state.get("exit"),
            elapsed=time.time() - float(run.get("started_at") or 0),
            wall=float(run.get("wall") or self._default_timeout),
            max_output_bytes=self._max_output_bytes,
        )
        self.remove_path(session_id, run["job_dir"])
        return DetachedState(
            done=True, result=result, output=detached.tail_bytes(text), output_size=int(state.get("size") or 0)
        )

    def cancel_detached(self, session_id: str, run: Dict[str, Any]) -> None:
        """Stop a detached run: SIGTERM every process in the session ``setsid`` started.

        ``timeout`` moves itself and the script into a process group of their own,
        so the run is matched by its session, which they all keep.
        """
        handle = self._get_handle(session_id)
        self._shell(handle, f"pkill -TERM -s {int(run['pid'])}; true", self._default_timeout)
        if run.get("job_dir"):
            self.remove_path(session_id, run["job_dir"])

    def refresh_activity(self, session_id: str) -> None:
        """No-op: machines are created without auto-suspend, so a long run is never paused."""
        return None

    def adopt(self, session_id: str, run: Dict[str, Any]) -> Dict[str, Any]:
        """Register the machine a detached run lives in, without priming or creating anything.

        Args:
            session_id: The DocsGPT session.
            run: The run's handle (``machine_id``, ``workspace``).

        Returns:
            Handle fields to persist (none for boxd).
        """
        with self._lock:
            self._handles[session_id] = _Handle(run["machine_id"], run.get("workspace") or _WORKSPACE_ROOT)
        return {}

    def release_adopted(self, session_id: str, run: Dict[str, Any]) -> None:
        """Drop an adopted handle without touching the machine."""
        with self._lock:
            handle = self._handles.get(session_id)
            if handle is not None and handle.machine_id == run.get("machine_id"):
                self._handles.pop(session_id, None)

    # -- File transfer ---------------------------------------------------

    def put_file(self, session_id: str, dest_path: str, data: bytes) -> None:
        """Upload ``data`` to ``dest_path`` under the session workspace (parent dirs are created)."""
        handle = self._get_handle(session_id)
        remote = self._remote_path(handle.workspace, dest_path)
        self._keep(handle)
        try:
            self._upload(handle, remote, data)
        except Exception as exc:  # noqa: BLE001 - classified below
            if self._ensure_running(handle):
                try:
                    self._upload(handle, remote, data)
                    return
                except Exception:  # noqa: BLE001 - second failure -> classified below
                    pass
            self._raise_file_error("put_file", dest_path, session_id, handle, exc)

    def _upload(self, handle: _Handle, remote: str, data: bytes) -> None:
        """Write ``data`` to the absolute path ``remote``; an empty file is created with a shell command."""
        if data:
            self._client.machines.files.upload(handle.machine_id, remote, data)
            return
        parent = shlex.quote(posixpath.dirname(remote))
        output, exit_code = self._shell(handle, f"mkdir -p {parent} && : > {shlex.quote(remote)}", self._default_timeout)
        if exit_code != 0:
            raise IOError(f"creating an empty file exited with {exit_code}: {output.strip()[:200]}")

    def get_file(self, session_id: str, path: str) -> bytes:
        """Download ``path`` from the session workspace as bytes, capped at ``max_file_bytes``."""
        handle = self._get_handle(session_id)
        remote = self._remote_path(handle.workspace, path)
        # -L follows a symlink, so the size checked is the size of what is read.
        command = f"stat -L -c '%F/%s' -- {shlex.quote(remote)}"
        try:
            output, exit_code = self._shell(handle, command, self._default_timeout)
        except Exception as exc:  # noqa: BLE001 - classified below
            self._raise_file_error("get_file", path, session_id, handle, exc)
        kind, _, size = output.strip().rpartition("/")
        if exit_code != 0 or not size.isdigit():
            raise FileNotFoundError(f"get_file: no such file {path!r}")
        if not kind.startswith("regular"):
            raise IOError(f"get_file: {path!r} is not a regular file")
        if int(size) > self._max_file_bytes:
            raise FileTooLargeError(int(size), self._max_file_bytes)
        try:
            data = self._client.machines.files.download(handle.machine_id, remote)
        except Exception as exc:  # noqa: BLE001 - classified below
            self._raise_file_error("get_file", path, session_id, handle, exc)
        data = data if isinstance(data, bytes) else bytes(data)
        if len(data) > self._max_file_bytes:
            raise FileTooLargeError(len(data), self._max_file_bytes)
        return data

    def list_files(self, session_id: str) -> List[str]:
        """List workspace-relative file paths for ``session_id`` (recursive, never escapes the workspace)."""
        handle = self._get_handle(session_id)
        root = posixpath.normpath(handle.workspace)
        command = f"mkdir -p {shlex.quote(root)} && find {shlex.quote(root)} -type f -printf '%P\\0'"
        try:
            output, exit_code = self._shell(handle, command, self._default_timeout)
        except Exception as exc:  # noqa: BLE001 - classified below
            self._raise_file_error("list_files", ".", session_id, handle, exc)
        if exit_code != 0:
            raise IOError(f"list_files failed: exit code {exit_code}")
        out: List[str] = []
        for rel in output.split("\0"):
            if not rel:
                continue
            resolved = posixpath.normpath(posixpath.join(root, rel))
            if resolved != root and resolved.startswith(root + "/"):
                out.append(rel)
        return out

    def _raise_file_error(self, op: str, path: str, session_id: str, handle: _Handle, exc: Exception) -> None:
        """Classify and raise a failed file op: ``SandboxGoneError`` vs ``IOError``.

        A gone machine drops the handle so the next ``open`` creates a fresh one.
        Error text carries only the exception type, never backend payloads.
        """
        logger.warning("%s failed for %r: %s", op, path, exc)
        if self._machine_gone(handle):
            self._forget_handle(session_id, handle)
            raise SandboxGoneError(f"{op} failed: sandbox gone ({type(exc).__name__})") from exc
        if isinstance(exc, IOError):
            raise exc
        raise IOError(f"{op} failed: {type(exc).__name__}") from exc
