"""Jupyter Kernel Gateway sandbox: stateful in-process kernels over REST + WebSocket."""

import base64
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import requests
import websocket

from docsgpt.sandbox import detached
from docsgpt.sandbox.base import (
    CodeSandbox,
    DetachedState,
    DisplayData,
    ExecResult,
    OpenedSession,
    Plot,
    SandboxGoneError,
)

logger = logging.getLogger(__name__)

# Per-session workspace root inside the runner container. The kernel sets its
# cwd here so relative paths from LLM code and file in/out share one directory.
_WORKSPACE_ROOT = "/tmp/docsgpt-sandbox"  # nosec B108 - controlled per-session sandbox workspace dir

# Marker the get_file helper prints around the base64 payload so we can extract
# it from interleaved stdout without a contents API (the gateway has none).
_FILE_BEGIN = "<<<DOCSGPT_FILE_BEGIN>>>"
_FILE_END = "<<<DOCSGPT_FILE_END>>>"

# Session ids become filesystem path components; allow only safe characters.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Kernel-side helper that resolves a workspace-relative path and rejects any
# absolute path or one that escapes the per-session workspace (path traversal).
_CONTAINMENT_SNIPPET = (
    "def _resolve(_base, _rel):\n"
    "    import os as _os\n"
    "    if _os.path.isabs(_rel):\n"
    "        raise ValueError('absolute paths are not allowed')\n"
    "    _root = _os.path.realpath(_base)\n"
    "    _rp = _os.path.realpath(_os.path.join(_root, _rel))\n"
    "    if _rp != _root and not _rp.startswith(_root + _os.sep):\n"
    "        raise ValueError('path escapes the session workspace')\n"
    "    return _rp\n"
)


# Where a container's cgroup counts its OOM kills: cgroup v2, then v1. The
# counter covers every process in the runner container.
_OOM_COUNTER_PATHS = ("/sys/fs/cgroup/memory.events", "/sys/fs/cgroup/memory/memory.oom_control")
_OOM_MARKER_RE = re.compile(r"<<<DOCSGPT_OOM_KILLS:(-?\d+)>>>")

# Kernel-side program that prints the container's OOM-kill count, or -1 when no
# counter is readable (not in a container, or a cgroup layout without one).
_OOM_KILLS_SNIPPET = (
    "_docsgpt_n = -1\n"
    f"for _docsgpt_p in {_OOM_COUNTER_PATHS!r}:\n"
    "    try:\n"
    "        with open(_docsgpt_p) as _docsgpt_f:\n"
    "            for _docsgpt_l in _docsgpt_f:\n"
    "                if _docsgpt_l.startswith('oom_kill '):\n"
    "                    _docsgpt_n = int(_docsgpt_l.split()[1])\n"
    "    except (OSError, ValueError, IndexError):\n"
    "        pass\n"
    "    if _docsgpt_n >= 0:\n"
    "        break\n"
    "print('<<<DOCSGPT_OOM_KILLS:%d>>>' % _docsgpt_n)\n"
    "del _docsgpt_n, _docsgpt_p\n"
)

# ``status`` values the gateway sends, with no parent message, when the kernel
# process died: ``restarting`` (it starts a fresh process under the same kernel
# id) or ``dead`` (it could not).
_KERNEL_DEATH_STATES = frozenset({"restarting", "dead"})


def _parse_oom_kills(stdout: str) -> Optional[int]:
    """Read the OOM-kill count ``_OOM_KILLS_SNIPPET`` printed; None when it had none."""
    match = _OOM_MARKER_RE.search(stdout or "")
    if not match:
        return None
    count = int(match.group(1))
    return count if count >= 0 else None


class _Kernel:
    """Tracks one gateway kernel plus the per-session workspace it executes in."""

    def __init__(
        self, kernel_id: str, workspace: str, session_id: Optional[str] = None
    ) -> None:
        self.kernel_id = kernel_id
        self.workspace = workspace
        self.session_id = session_id
        self.initialized = False


class JupyterKernelGatewaySandbox(CodeSandbox):
    """Drives one always-on Jupyter Kernel Gateway, one stateful kernel per session."""

    # Raw-byte chunk size for a staged upload: each execute_request carries one
    # chunk's base64 (~4 MB at 3 MB raw), well under the gateway's 10 MiB websocket
    # frame cap. The 3-byte boundary keeps every base64 block self-contained.
    _PUT_CHUNK_BYTES = 3 * 1024 * 1024

    def __init__(
        self,
        gateway_url: str,
        auth_token: Optional[str] = None,
        kernel_name: str = "python3",
        default_timeout: float = 60.0,
        http_timeout: float = 10.0,
        max_output_bytes: int = 8 * 1024 * 1024,
        max_file_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        """Configure the client; no kernel is created until ``open`` is called."""
        self._base_url = gateway_url.rstrip("/")
        self._auth_token = auth_token
        self._kernel_name = kernel_name
        self._default_timeout = default_timeout
        self._http_timeout = http_timeout
        self._max_output_bytes = max_output_bytes
        self._max_file_bytes = max_file_bytes
        self._kernels: Dict[str, _Kernel] = {}
        # Timed-out kernels whose DELETE could not yet be confirmed. Immutable
        # ids stay retryable here and are never reused as active runtimes.
        self._quarantined_kernels: Dict[str, Optional[str]] = {}
        # The container's OOM-kill count when each kernel was primed (None when
        # unreadable). A kernel that dies after the count rose was OOM-killed.
        self._oom_baseline: Dict[str, Optional[int]] = {}
        self._lock = threading.Lock()
        # Session ids with a create in flight; a second open() for the same id
        # waits on this CV and reuses the result instead of double-creating a
        # kernel (the idempotency contract SandboxManager.open relies on).
        self._creating: set = set()
        self._create_cv = threading.Condition(self._lock)

    # -- HTTP helpers ----------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"token {self._auth_token}"
        return headers

    def _ws_url(self, kernel_id: str) -> str:
        # The token is sent only via the Authorization header (_ws_headers); keeping it
        # out of the URL query avoids leaking it into gateway/proxy access logs.
        parsed = urlparse(self._base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path = f"/api/kernels/{kernel_id}/channels"
        return urlunparse((scheme, parsed.netloc, path, "", "", ""))

    def _get_kernel(self, session_id: str) -> _Kernel:
        # A manager may cache a replacement handle, so normal traffic is also
        # an opportunity to retire an older quarantined kernel.
        self._retry_quarantined_kernels(session_id)
        with self._lock:
            kernel = self._kernels.get(session_id)
        if kernel is None:
            raise KeyError(f"No sandbox session open for {session_id!r}")
        return kernel

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        """Reject session ids that would not be a safe filesystem path component."""
        if not _SESSION_ID_RE.match(session_id):
            raise ValueError(f"Invalid session id {session_id!r}: expected [A-Za-z0-9_-]+")

    # -- Lifecycle -------------------------------------------------------

    def open(self, session_id: str) -> str:
        """Start (or reuse) the kernel for ``session_id``; see ``open_session``."""
        return self.open_session(session_id).handle

    def open_session(self, session_id: str) -> OpenedSession:
        """Start a fresh kernel for ``session_id`` and prime its workspace cwd.

        Idempotent under concurrency: if another thread is already creating a kernel
        for this session, wait for it and reuse the result rather than POSTing a
        second kernel that would orphan on the gateway.

        Returns:
            OpenedSession: The kernel id, and ``created`` True only when this call
            started the kernel. A new kernel also starts on an emptied workspace
            (see ``_prime``), so nothing from an earlier kernel survives.
        """
        self._validate_session_id(session_id)
        with self._create_cv:
            while session_id in self._creating:
                self._create_cv.wait()
            existing = self._kernels.get(session_id)
            has_quarantine = any(
                owner == session_id for owner in self._quarantined_kernels.values()
            )
            if existing is not None and not has_quarantine:
                return OpenedSession(existing.kernel_id, False)
            self._creating.add(session_id)
        try:
            unresolved = self._retry_quarantined_kernels(session_id)
            with self._lock:
                # A replacement may already exist. It is safe to use even when
                # deletion of an older exact id remains pending.
                existing = self._kernels.get(session_id)
            if existing is not None:
                return OpenedSession(existing.kernel_id, False)
            if unresolved:
                raise RuntimeError(
                    f"Previous timed-out kernel for {session_id!r} could not be terminated"
                )
            resp = requests.post(
                f"{self._base_url}/api/kernels",
                headers=self._headers(),
                data=json.dumps({"name": self._kernel_name}),
                timeout=self._http_timeout,
            )
            resp.raise_for_status()
            kernel_id = resp.json()["id"]
            workspace = f"{_WORKSPACE_ROOT}/{session_id}"
            kernel = _Kernel(kernel_id, workspace, session_id)
            with self._lock:
                self._kernels[session_id] = kernel
            self._prime(kernel)
            return OpenedSession(kernel_id, True)
        finally:
            with self._create_cv:
                self._creating.discard(session_id)
                self._create_cv.notify_all()

    def attach(self, session_id: str) -> str:
        """Reattach to a still-running kernel for ``session_id``; open a cold one if gone."""
        self._validate_session_id(session_id)
        unresolved = self._retry_quarantined_kernels(session_id)
        with self._lock:
            existing = self._kernels.get(session_id)
        if existing is not None and self._kernel_alive(existing.kernel_id):
            return existing.kernel_id
        if existing is not None:
            with self._lock:
                self._kernels.pop(session_id, None)
        if unresolved:
            raise RuntimeError(
                f"Previous timed-out kernel for {session_id!r} could not be terminated"
            )
        logger.warning("Re-attaching session %s to a cold kernel; previous state is lost", session_id)
        return self.open(session_id)

    def close(self, session_id: str) -> None:
        """Sweep the session workspace (best-effort) then delete its kernel and registry entry."""
        with self._lock:
            kernel = self._kernels.pop(session_id, None)
        if kernel is None:
            return
        self._cleanup_workspace(kernel)
        self._delete_kernel(kernel.kernel_id)

    def _cleanup_workspace(self, kernel: _Kernel) -> None:
        """Best-effort rmtree of the per-session workspace while the kernel is still alive."""
        if not kernel.initialized:
            return
        code = "import shutil as _sh\n" f"_sh.rmtree({kernel.workspace!r}, ignore_errors=True)\n"
        try:
            self._run(kernel, code, self._http_timeout)
        except Exception:  # noqa: BLE001 - teardown is best-effort and must never raise
            logger.warning("Failed to sweep workspace for kernel %s", kernel.kernel_id, exc_info=True)

    def close_handle(self, session_id: str, kernel_id: str) -> None:
        """Delete the SPECIFIC kernel captured at eviction time, never a re-opened one.

        When the manager evicts a session, a concurrent ``open`` of the same id may have
        already started a fresh kernel; this deletes only the kernel whose id was captured
        and pops the registry entry only when it still points at that same kernel, so the
        new kernel survives.
        """
        with self._lock:
            current = self._kernels.get(session_id)
            if current is not None and current.kernel_id == kernel_id:
                self._kernels.pop(session_id, None)
        self._delete_kernel(kernel_id)

    def _delete_kernel(self, kernel_id: str) -> bool:
        """Best-effort DELETE of a gateway kernel, retrying once and never raising."""
        with self._lock:
            self._oom_baseline.pop(kernel_id, None)
        last_error = "unknown error"
        for _attempt in range(2):
            try:
                resp = requests.delete(
                    f"{self._base_url}/api/kernels/{kernel_id}",
                    headers=self._headers(),
                    timeout=self._http_timeout,
                )
            except requests.RequestException as exc:  # teardown is best-effort
                last_error = str(exc)
                continue
            # A missing kernel is already in the desired state.
            if 200 <= resp.status_code < 300 or resp.status_code == 404:
                return True
            last_error = f"HTTP {resp.status_code}"
        logger.warning("Failed to delete kernel %s after retry: %s", kernel_id, last_error)
        return False

    def _kernel_alive(self, kernel_id: str) -> bool:
        try:
            resp = requests.get(
                f"{self._base_url}/api/kernels/{kernel_id}",
                headers=self._headers(),
                timeout=self._http_timeout,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def _interrupt(self, kernel_id: str) -> None:
        """Best-effort interrupt so a timed-out/runaway kernel becomes reusable."""
        try:
            requests.post(
                f"{self._base_url}/api/kernels/{kernel_id}/interrupt",
                headers=self._headers(),
                timeout=self._http_timeout,
            )
        except requests.RequestException as exc:
            logger.warning("Failed to interrupt kernel %s: %s", kernel_id, exc)

    def _interrupt_and_drain(self, ws: websocket.WebSocket, msg_id: str, kernel_id: str) -> bool:
        """Interrupt and drain the request, returning whether matching idle was observed."""
        self._interrupt(kernel_id)
        drain_deadline = time.monotonic() + self._http_timeout
        while time.monotonic() < drain_deadline:
            try:
                ws.settimeout(max(0.05, drain_deadline - time.monotonic()))
                raw = ws.recv()
            except (websocket.WebSocketTimeoutException, websocket.WebSocketConnectionClosedException):
                return False
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("parent_header", {}).get("msg_id") != msg_id:
                continue
            msg_type = msg.get("msg_type") or msg.get("header", {}).get("msg_type")
            if msg_type == "status" and msg.get("content", {}).get("execution_state") == "idle":
                return True
        return False

    def _retry_quarantined_kernels(self, session_id: str) -> List[str]:
        """Retry pending exact-id deletes for this session; return unresolved ids."""
        with self._lock:
            pending = [
                (kernel_id, owner)
                for kernel_id, owner in self._quarantined_kernels.items()
                if owner == session_id
            ]
        unresolved: List[str] = []
        for kernel_id, owner in pending:
            if self._delete_kernel(kernel_id):
                with self._lock:
                    if (
                        kernel_id in self._quarantined_kernels
                        and self._quarantined_kernels[kernel_id] == owner
                    ):
                        self._quarantined_kernels.pop(kernel_id, None)
            else:
                unresolved.append(kernel_id)
        return unresolved

    def _invalidate_kernel(
        self, kernel_id: str, session_id: Optional[str] = None
    ) -> bool:
        """Quarantine and hard-delete one exact kernel without touching a replacement."""
        with self._lock:
            stale_sessions = [
                session_id
                for session_id, kernel in self._kernels.items()
                if kernel.kernel_id == kernel_id
            ]
            owner = session_id or (stale_sessions[0] if len(stale_sessions) == 1 else None)
            # Register before eviction so a failed DELETE never loses the only
            # retryable reference to this runaway kernel id.
            self._quarantined_kernels[kernel_id] = owner
            for session_id in stale_sessions:
                self._kernels.pop(session_id, None)
        deleted = self._delete_kernel(kernel_id)
        if deleted:
            with self._lock:
                self._quarantined_kernels.pop(kernel_id, None)
        return deleted

    def _forget_kernel(self, kernel_id: str) -> None:
        """Drop registry entries still bound to ``kernel_id``; a replacement kernel is kept."""
        with self._lock:
            for session_id, registered in list(self._kernels.items()):
                if registered.kernel_id == kernel_id:
                    self._kernels.pop(session_id, None)

    @staticmethod
    def _file_op_error(op: str, result: ExecResult) -> IOError:
        """Build the error for a failed file op; a lost runtime is a ``SandboxGoneError``."""
        if result.runtime_invalidated:
            return SandboxGoneError(f"{op} failed: kernel gone ({result.error_name})")
        return IOError(f"{op} failed: {result.error_value}")

    def _prime(self, kernel: _Kernel) -> None:
        """Create the per-session workspace (mode 0700) and chdir the kernel into it."""
        # 0700 on the root and the per-session dir is defense-in-depth only: every
        # kernel runs under one shared uid here, so this is not a cross-session
        # boundary (that needs distinct uids / per-session VMs -- the Daytona backend).
        # A fresh kernel always starts on a clean workspace: rmtree any stale dir a
        # prior kernel for the same session id left behind (else artifacts_capture
        # would re-read those files every exec). Only genuine new-kernel creation
        # reaches here -- open() on a live kernel returns early -- so a warm
        # session is never wiped mid-computation.
        setup = (
            "import os as _os, shutil as _sh\n"
            f"_os.makedirs({_WORKSPACE_ROOT!r}, mode=0o700, exist_ok=True)\n"
            f"_os.chmod({_WORKSPACE_ROOT!r}, 0o700)\n"
            f"_sh.rmtree({kernel.workspace!r}, ignore_errors=True)\n"
            f"_os.makedirs({kernel.workspace!r}, mode=0o700, exist_ok=True)\n"
            f"_os.chmod({kernel.workspace!r}, 0o700)\n"
            f"_os.chdir({kernel.workspace!r})\n"
            + _OOM_KILLS_SNIPPET
        )
        result = self._run(kernel, setup, self._default_timeout)
        if not result.ok:
            raise RuntimeError(f"Sandbox workspace setup failed: {result.error_value}")
        with self._lock:
            self._oom_baseline[kernel.kernel_id] = _parse_oom_kills(result.stdout)
        kernel.initialized = True

    # -- Execution -------------------------------------------------------

    def exec(self, session_id: str, code: str, timeout: Optional[float] = None) -> ExecResult:
        """Run ``code`` in the session's persistent kernel; state carries across calls."""
        kernel = self._get_kernel(session_id)
        return self._run(kernel, code, timeout or self._default_timeout)

    def _run(
        self,
        kernel: _Kernel,
        code: str,
        timeout: float,
        max_output_bytes: Optional[int] = None,
    ) -> ExecResult:
        """Execute one ``execute_request`` over the WS channel and assemble the reply.

        ``max_output_bytes`` overrides the default output budget for this call only
        (file-transfer execs raise it so a multi-MB base64 payload is not truncated).
        """
        try:
            # The handshake is bounded by the default exec cap, not a long run's
            # timeout: it waits only for the gateway to answer (and for a
            # starting kernel's info reply), never for the code. ``_collect``
            # sets each read's timeout from the run's own deadline.
            ws = websocket.create_connection(
                self._ws_url(kernel.kernel_id),
                timeout=min(timeout, max(self._default_timeout, self._http_timeout)),
                header=self._ws_headers(),
            )
        except Exception as exc:  # noqa: BLE001 - connect failure -> error result, never raise
            if isinstance(exc, websocket.WebSocketBadStatusException) and exc.status_code == 404:
                # The gateway no longer has this kernel: culled after idling, or lost
                # with a gateway restart. Retrying the cached id would fail the same
                # way on every call, so forget it and let the next open start fresh.
                self._forget_kernel(kernel.kernel_id)
                result = _error_result(
                    "KernelGoneError", "the session's kernel no longer exists; the next call starts a new session"
                )
                result.runtime_invalidated = True
                return result
            return _error_result(type(exc).__name__, str(exc) or "failed to open kernel channel")
        try:
            msg_id = uuid.uuid4().hex
            ws.send(json.dumps(self._execute_request(msg_id, code)))
            return self._collect(
                ws,
                msg_id,
                timeout,
                kernel.kernel_id,
                max_output_bytes,
                session_id=kernel.session_id,
            )
        finally:
            try:
                ws.close()
            except Exception:  # noqa: BLE001 - closing a socket must not mask results
                pass

    def _ws_headers(self) -> List[str]:
        if self._auth_token:
            return [f"Authorization: token {self._auth_token}"]
        return []

    @staticmethod
    def _execute_request(msg_id: str, code: str) -> dict:
        """Build a Jupyter ``execute_request`` wire message for the shell channel."""
        return {
            "header": {
                "msg_id": msg_id,
                "username": "docsgpt",
                "session": uuid.uuid4().hex,
                "msg_type": "execute_request",
                "version": "5.3",
            },
            "parent_header": {},
            "metadata": {},
            "content": {
                "code": code,
                "silent": False,
                "store_history": True,
                "user_expressions": {},
                "allow_stdin": False,
                "stop_on_error": True,
            },
            "channel": "shell",
        }

    def _collect(
        self,
        ws: websocket.WebSocket,
        msg_id: str,
        timeout: float,
        kernel_id: str,
        max_output_bytes: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> ExecResult:
        """Read iopub/shell frames until ``execute_reply``/idle, a wall-clock deadline, or a closed socket."""
        effective = max_output_bytes if max_output_bytes is not None else self._max_output_bytes
        result = ExecResult()
        stdout_parts: List[str] = []
        stderr_parts: List[str] = []
        buffered = 0
        truncated = False
        reply_seen = False
        idle_seen = False
        deadline = time.monotonic() + timeout

        while not (reply_seen and idle_seen):
            now = time.monotonic()
            remaining = deadline - now
            if remaining <= 0:
                self._fail(result, "TimeoutError", f"execution exceeded {timeout}s")
                if not self._interrupt_and_drain(ws, msg_id, kernel_id):
                    self._invalidate_kernel(kernel_id, session_id)
                    result.runtime_invalidated = True
                break
            try:
                ws.settimeout(remaining)
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                self._fail(result, "TimeoutError", f"execution exceeded {timeout}s")
                if not self._interrupt_and_drain(ws, msg_id, kernel_id):
                    self._invalidate_kernel(kernel_id, session_id)
                    result.runtime_invalidated = True
                break
            except websocket.WebSocketConnectionClosedException:
                self._fail(result, "KernelDiedError", "kernel channel closed before completion")
                break
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError as exc:
                self._fail(result, "ProtocolError", f"malformed kernel frame: {exc}")
                break
            msg_type = msg.get("msg_type") or msg.get("header", {}).get("msg_type")
            content = msg.get("content", {})
            if msg.get("parent_header", {}).get("msg_id") != msg_id:
                if msg_type == "status" and content.get("execution_state") in _KERNEL_DEATH_STATES:
                    # The kernel process died mid-run. The reply will never
                    # come, so stop now instead of waiting out the deadline.
                    self._kernel_died(result, content.get("execution_state"), kernel_id, session_id)
                    break
                continue

            if msg_type == "stream":
                if not truncated:
                    text = content.get("text", "")
                    buffered += len(text.encode("utf-8", "ignore"))
                    if buffered > effective:
                        truncated = True
                        self._interrupt_and_drain(ws, msg_id, kernel_id)  # runaway output: stop and drain
                        break
                    elif content.get("name") == "stderr":
                        stderr_parts.append(text)
                    else:
                        stdout_parts.append(text)
            elif msg_type in ("execute_result", "display_data"):
                # Rich outputs (results/display_data/plots) count against the SAME
                # byte budget as streams: untrusted code can emit a huge DataFrame /
                # IPython.display.HTML / many large images that the backend would
                # otherwise buffer unbounded. Drop and truncate once over budget.
                if not truncated:
                    buffered += self._rich_payload_bytes(content)
                    if buffered > effective:
                        truncated = True
                        self._interrupt_and_drain(ws, msg_id, kernel_id)
                        break
                    self._capture_rich(result, msg_type, content)
            elif msg_type == "error":
                result.status = "error"
                result.exit_code = 1
                result.error_name = content.get("ename")
                result.error_value = content.get("evalue")
                result.traceback = content.get("traceback", [])
            elif msg_type == "execute_reply":
                reply_seen = True
                result.execution_count = content.get("execution_count")
                if content.get("status") == "error":
                    result.status = "error"
                    result.exit_code = result.exit_code or 1
                    result.error_name = result.error_name or content.get("ename")
                    result.error_value = result.error_value or content.get("evalue")
                    if not result.traceback:
                        result.traceback = content.get("traceback", [])
            elif msg_type == "status":
                if content.get("execution_state") == "idle":
                    idle_seen = True

        if truncated:
            stderr_parts.append(f"\n[output truncated at {effective} bytes]")
            result.truncated = True  # surface the cut without flipping status off "ok"
        result.stdout = "".join(stdout_parts)
        result.stderr = "".join(stderr_parts)
        return result

    def _kernel_died(
        self, result: ExecResult, state: str, kernel_id: str, session_id: Optional[str]
    ) -> None:
        """Fail a run whose kernel process died, and retire the kernel.

        The gateway restarts a dead kernel under the same id, but the new
        process has none of the session's variables and is no longer in the
        session's workspace, so the kernel is deleted and the next call opens a
        new session. When the container's OOM-kill count rose since the kernel
        was primed, the run is marked out of memory.

        Args:
            result: The run's result, failed in place.
            state: The status the gateway sent, ``restarting`` or ``dead``.
            kernel_id: The kernel that died.
            session_id: The session it served, for the quarantine record.
        """
        with self._lock:
            baseline = self._oom_baseline.pop(kernel_id, None)
        oom_killed = False
        if state == "restarting" and baseline is not None:
            now = self._oom_kills_now(kernel_id, session_id)
            oom_killed = now is not None and now > baseline
        if oom_killed:
            message = "the kernel was killed for using more memory than the sandbox allows"
        else:
            message = (
                "the kernel process died while running this code (most often because it ran out of memory)"
            )
        self._fail(result, "KernelDiedError", message + "; the next call starts a new session")
        result.out_of_memory = oom_killed
        logger.warning(
            "Kernel %s died mid-run (%s, oom_killed=%s); retiring it", kernel_id, state, oom_killed
        )
        self._invalidate_kernel(kernel_id, session_id)
        result.runtime_invalidated = True

    def _oom_kills_now(self, kernel_id: str, session_id: Optional[str]) -> Optional[int]:
        """Read the container's OOM-kill count through the restarted kernel; None when unreadable."""
        try:
            probe = self._run(_Kernel(kernel_id, _WORKSPACE_ROOT, session_id), _OOM_KILLS_SNIPPET, self._http_timeout)
        except Exception:  # noqa: BLE001 - the probe is best-effort
            logger.debug("OOM-kill probe failed for kernel %s", kernel_id, exc_info=True)
            return None
        return _parse_oom_kills(probe.stdout) if probe.ok else None

    @staticmethod
    def _fail(result: ExecResult, name: str, value: str) -> None:
        """Mark ``result`` as a failed exec with the given error name/value."""
        result.status = "error"
        result.error_name = name
        result.error_value = value
        result.exit_code = -1

    @staticmethod
    def _rich_payload_bytes(content: dict) -> int:
        """Approximate the serialized byte size of a rich-output bundle's data payloads."""
        total = 0
        for value in (content.get("data") or {}).values():
            if isinstance(value, str):
                total += len(value.encode("utf-8", "ignore"))
            else:
                try:
                    total += len(json.dumps(value, default=str).encode("utf-8", "ignore"))
                except Exception:
                    total += len(str(value).encode("utf-8", "ignore"))
        return total

    @staticmethod
    def _capture_rich(result: ExecResult, msg_type: str, content: dict) -> None:
        """Sort a rich output into results/display_data and pull out any image plots."""
        data = content.get("data", {}) or {}
        metadata = content.get("metadata", {}) or {}
        bundle = DisplayData(data=data, metadata=metadata)
        if msg_type == "execute_result":
            result.results.append(bundle)
        else:
            result.display_data.append(bundle)
        for mime, payload in data.items():
            if mime.startswith("image/"):
                result.plots.append(Plot(format=mime.split("/", 1)[1], content_base64=payload))

    # -- File transfer ---------------------------------------------------

    def _file_transfer_budget(self) -> int:
        """Output budget for a file-transfer exec: max file bytes inflated by base64 plus marker slack."""
        return self._max_file_bytes * 4 // 3 + 4096

    def put_file(self, session_id: str, dest_path: str, data: bytes) -> None:
        """Decode ``data`` inside the kernel and write it under the session workspace.

        The upload is chunked so no single ``execute_request`` exceeds the gateway's
        websocket message-size cap: the first chunk creates/truncates the file (``wb``)
        and each later chunk appends (``ab``). Every chunk program re-resolves the path
        -- kernel globals are not relied on to survive between execs.
        """
        kernel = self._get_kernel(session_id)
        offset = 0
        first = True
        # Loop at least once so an empty file is still created (a single wb write of b"").
        while first or offset < len(data):
            chunk = data[offset:offset + self._PUT_CHUNK_BYTES]
            encoded = base64.b64encode(chunk).decode("ascii")
            if first:
                body = (
                    f"_p = _resolve({kernel.workspace!r}, {dest_path!r})\n"
                    "_os.makedirs(_os.path.dirname(_p) or '.', exist_ok=True)\n"
                    f"_f = open(_p, 'wb'); _f.write(_b64.b64decode({encoded!r})); _f.close()\n"
                )
            else:
                body = (
                    f"_p = _resolve({kernel.workspace!r}, {dest_path!r})\n"
                    f"_f = open(_p, 'ab'); _f.write(_b64.b64decode({encoded!r})); _f.close()\n"
                )
            code = "import base64 as _b64, os as _os\n" + _CONTAINMENT_SNIPPET + body
            result = self._run(kernel, code, self._default_timeout)
            if not result.ok:
                raise self._file_op_error("put_file", result)
            offset += self._PUT_CHUNK_BYTES
            first = False

    def get_file(self, session_id: str, path: str) -> bytes:
        """Read ``path`` inside the kernel and stream its base64 (with a length tag) over stdout."""
        kernel = self._get_kernel(session_id)
        code = (
            "import base64 as _b64, hashlib as _hl, os as _os\n"
            + _CONTAINMENT_SNIPPET
            + f"_p = _resolve({kernel.workspace!r}, {path!r})\n"
            f"_sz = _os.path.getsize(_p)\n"
            f"if _sz > {self._max_file_bytes}:\n"
            f"    raise ValueError('file too large: %d > {self._max_file_bytes} bytes' % _sz)\n"
            "_d = open(_p, 'rb').read()\n"
            "_h = _hl.sha256(_d).hexdigest()\n"
            f"print({_FILE_BEGIN!r} + str(len(_d)) + ':' + _h + ':'"
            f" + _b64.b64encode(_d).decode('ascii') + {_FILE_END!r})\n"
        )
        result = self._run(kernel, code, self._default_timeout, max_output_bytes=self._file_transfer_budget())
        if not result.ok:
            raise self._file_op_error("get_file", result)
        out = result.stdout
        start = out.find(_FILE_BEGIN)
        end = out.find(_FILE_END)
        if start == -1 or end == -1:
            raise IOError(f"get_file produced no payload for {path!r}")
        payload = out[start + len(_FILE_BEGIN):end]
        expected_len_s, expected_sha, encoded = payload.split(":", 2)
        decoded = base64.b64decode(encoded)
        if len(decoded) != int(expected_len_s) or hashlib.sha256(decoded).hexdigest() != expected_sha:
            raise IOError(f"get_file integrity check failed for {path!r} (payload truncated)")
        return decoded

    def list_files(self, session_id: str) -> List[str]:
        """Walk the session workspace inside the kernel and return relative paths."""
        kernel = self._get_kernel(session_id)
        code = (
            "import os as _os, json as _json\n"
            f"_root = {kernel.workspace!r}\n"
            "_out = []\n"
            "for _dp, _dn, _fn in _os.walk(_root):\n"
            "    for _name in _fn:\n"
            "        _out.append(_os.path.relpath(_os.path.join(_dp, _name), _root))\n"
            f"print({_FILE_BEGIN!r} + _json.dumps(_out) + {_FILE_END!r})\n"
        )
        result = self._run(kernel, code, self._default_timeout, max_output_bytes=self._file_transfer_budget())
        if not result.ok:
            raise self._file_op_error("list_files", result)
        out = result.stdout
        start = out.find(_FILE_BEGIN)
        end = out.find(_FILE_END)
        if start == -1 or end == -1:
            return []
        return json.loads(out[start + len(_FILE_BEGIN):end])


    # -- Detached runs ---------------------------------------------------

    _JOB_BEGIN = "<<<DOCSGPT_JOB_BEGIN>>>"
    _JOB_END = "<<<DOCSGPT_JOB_END>>>"

    def start_detached(self, session_id: str, code: str, timeout: Optional[float], key: str) -> Dict[str, Any]:
        """Start ``code`` as a separate Python process in the runner and return at once.

        The process runs ``scratch/jobs/<key>/main.py`` from the session
        workspace under ``timeout``, in its own session (``setsid``) so it
        outlives the kernel call that launched it. It does NOT share the
        kernel's variables or imports, only the workspace files. Output goes to
        ``out.log`` and the exit status to ``exit`` in the job directory.

        Args:
            session_id: The session whose workspace and kernel launch the run.
            code: The source.
            timeout: Wall-clock cap in seconds (the default exec cap when None).
            key: A unique key for this run.

        Returns:
            The run's handle.

        Raises:
            IOError: The launch failed.
        """
        kernel = self._get_kernel(session_id)
        wall = int(timeout or self._default_timeout)
        directory = detached.job_dir(key)
        self.put_file(session_id, f"{directory}/main.py", detached.script_for(kernel.workspace, code).encode("utf-8"))
        launcher = (
            "import json as _json, os as _os, subprocess as _sp, sys as _sys\n"
            f"_job = _os.path.join({kernel.workspace!r}, {directory!r})\n"
            "_cmd = ('timeout -k 5 ' + str(" + str(wall) + ") + ' \"$0\" -u \"$1/main.py\" > \"$1/out.log\" 2>&1; '\n"
            "        'echo $? > \"$1/exit.tmp\" && mv \"$1/exit.tmp\" \"$1/exit\"')\n"
            "_p = _sp.Popen(['sh', '-c', _cmd, _sys.executable, _job], "
            f"cwd={kernel.workspace!r}, start_new_session=True, "
            "stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)\n"
            # Reap the run when it exits, so a cancelled one does not linger as a zombie.
            "__import__('threading').Thread(target=_p.wait, daemon=True).start()\n"
            f"print({self._JOB_BEGIN!r} + _json.dumps({{'pid': _p.pid}}) + {self._JOB_END!r})\n"
        )
        result = self._run(kernel, launcher, self._default_timeout)
        payload = detached.decode_marker_json(result.stdout, self._JOB_BEGIN, self._JOB_END) if result.ok else None
        if payload is None:
            raise self._file_op_error("start_detached", result)
        return {
            "backend": "jupyter",
            "kernel_id": kernel.kernel_id,
            "workspace": kernel.workspace,
            "job_dir": directory,
            "pid": int(json.loads(payload)["pid"]),
            "wall": wall,
            "started_at": time.time(),
        }

    def poll_detached(self, session_id: str, run: Dict[str, Any], *, with_output: bool = False) -> DetachedState:
        """Check a detached run through the session's (or an adopted observer) kernel.

        Args:
            session_id: The session the run belongs to.
            run: The handle ``start_detached`` returned.
            with_output: Also read the output of a run still going.

        Returns:
            The run's state; once it exited, its full result.

        Raises:
            IOError: The kernel could not be reached; poll again later.
        """
        kernel = self._get_kernel(session_id)
        probe = (
            "import json as _json, os as _os\n"
            f"_d = _os.path.join({kernel.workspace!r}, {run['job_dir']!r})\n"
            "_code = None\n"
            "_done = _os.path.exists(_os.path.join(_d, 'exit'))\n"
            "if _done:\n"
            "    try:\n"
            "        _code = int(open(_os.path.join(_d, 'exit')).read().strip() or '0')\n"
            "    except (OSError, ValueError):\n"
            "        _code = -1\n"
            "else:\n"
            "    try:\n"
            f"        _os.killpg({int(run['pid'])}, 0)\n"
            "    except ProcessLookupError:\n"
            "        _done, _code = True, 137\n"
            "    except PermissionError:\n"
            "        pass\n"
            "_tail, _size = '', 0\n"
            f"if _done or {bool(with_output)!r}:\n"
            "    try:\n"
            "        with open(_os.path.join(_d, 'out.log'), 'rb') as _f:\n"
            "            _f.seek(0, 2)\n"
            "            _size = _f.tell()\n"
            f"            _f.seek(max(0, _size - {detached.RUNNING_OUTPUT_BYTES}))\n"
            "            _tail = _f.read().decode('utf-8', 'replace')\n"
            "    except OSError:\n"
            "        pass\n"
            "print(" + repr(self._JOB_BEGIN) + " + _json.dumps({'done': _done, 'exit': _code, 'tail': _tail, "
            "'size': _size}) + " + repr(self._JOB_END) + ")\n"
        )
        result = self._run(kernel, probe, self._default_timeout)
        payload = detached.decode_marker_json(result.stdout, self._JOB_BEGIN, self._JOB_END) if result.ok else None
        if payload is None:
            raise self._file_op_error("poll_detached", result)
        state = json.loads(payload)
        if not state.get("done"):
            return DetachedState(
                done=False, output=detached.tail_bytes(state.get("tail") or ""), output_size=int(state.get("size") or 0)
            )
        try:
            output = self.get_file(session_id, f"{run['job_dir']}/out.log").decode("utf-8", "replace")
        except (IOError, ValueError):
            # Too large or unreadable: the tail is what the run reports.
            output = state.get("tail") or ""
        result = detached.finished_result(
            output,
            state.get("exit"),
            elapsed=time.time() - float(run.get("started_at") or 0),
            wall=float(run.get("wall") or self._default_timeout),
            max_output_bytes=self._max_output_bytes,
        )
        self._remove_job_dir(kernel, run)
        return DetachedState(
            done=True, result=result, output=detached.tail_bytes(output), output_size=int(state.get("size") or 0)
        )

    def _remove_job_dir(self, kernel: _Kernel, run: Dict[str, Any]) -> None:
        """Delete a finished run's job directory (best-effort)."""
        code = (
            "import os as _os, shutil as _sh\n"
            f"_sh.rmtree(_os.path.join({kernel.workspace!r}, {run['job_dir']!r}), ignore_errors=True)\n"
        )
        try:
            self._run(kernel, code, self._http_timeout)
        except Exception:  # noqa: BLE001 - cleanup is best-effort
            logger.debug("removing job dir %s failed", run.get("job_dir"), exc_info=True)

    def cancel_detached(self, session_id: str, run: Dict[str, Any]) -> None:
        """Stop a detached run: SIGTERM its process group (the ``timeout`` wrapper escalates to SIGKILL)."""
        kernel = self._get_kernel(session_id)
        code = (
            "import os as _os, signal as _sig\n"
            "try:\n"
            f"    _os.killpg({int(run['pid'])}, _sig.SIGTERM)\n"
            "except (ProcessLookupError, PermissionError):\n"
            "    pass\n"
        )
        self._run(kernel, code, self._http_timeout)

    def refresh_activity(self, session_id: str) -> None:
        """No-op: a polled kernel counts as active on the gateway."""
        return None

    def adopt(self, session_id: str, run: Dict[str, Any]) -> Dict[str, Any]:
        """Reach a detached run from another process through an observer kernel.

        The session's own kernel belongs to the process that opened it, and
        executing in it from here would queue behind (and on a timeout,
        interrupt) the user's next run. A separate observer kernel reads the
        session workspace by path instead; it is never primed, so the
        workspace is never wiped. Its id is kept on the run so later polls
        reuse it.

        Args:
            session_id: The session the run belongs to.
            run: The run's handle; ``observer_kernel_id`` when one exists.

        Returns:
            ``{"observer_kernel_id": ...}`` when a new observer was started.
        """
        observer = run.get("observer_kernel_id")
        created: Dict[str, Any] = {}
        if not observer or not self._kernel_alive(observer):
            resp = requests.post(
                f"{self._base_url}/api/kernels",
                headers=self._headers(),
                data=json.dumps({"name": self._kernel_name}),
                timeout=self._http_timeout,
            )
            resp.raise_for_status()
            observer = resp.json()["id"]
            created["observer_kernel_id"] = observer
        with self._lock:
            self._kernels[session_id] = _Kernel(observer, run.get("workspace") or "", session_id)
        return created

    def release_adopted(self, session_id: str, run: Dict[str, Any]) -> None:
        """Delete the observer kernel once its run is over (never the session's own kernel)."""
        observer = run.get("observer_kernel_id")
        with self._lock:
            kernel = self._kernels.get(session_id)
            if kernel is not None and kernel.kernel_id == observer:
                self._kernels.pop(session_id, None)
        if observer and observer != run.get("kernel_id"):
            self._delete_kernel(observer)


def _error_result(name: str, value: str) -> ExecResult:
    """Build a failed ExecResult carrying the given error name/value."""
    return ExecResult(status="error", error_name=name, error_value=value, exit_code=-1)
