"""Jupyter Kernel Gateway sandbox: stateful in-process kernels over REST + WebSocket."""

import base64
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from typing import Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import requests
import websocket

from application.sandbox.base import (
    CodeSandbox,
    DisplayData,
    ExecResult,
    Plot,
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
        """Start a fresh kernel for ``session_id`` and prime its workspace cwd.

        Idempotent under concurrency: if another thread is already creating a kernel
        for this session, wait for it and reuse the result rather than POSTing a
        second kernel that would orphan on the gateway.
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
                return existing.kernel_id
            self._creating.add(session_id)
        try:
            unresolved = self._retry_quarantined_kernels(session_id)
            with self._lock:
                # A replacement may already exist. It is safe to use even when
                # deletion of an older exact id remains pending.
                existing = self._kernels.get(session_id)
            if existing is not None:
                return existing.kernel_id
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
            return kernel_id
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

    def _prime(self, kernel: _Kernel) -> None:
        """Create the per-session workspace (mode 0700) and chdir the kernel into it."""
        # 0700 on the root and the per-session dir is defense-in-depth only: every
        # kernel runs under one shared uid here, so this is not a cross-session
        # boundary (that needs distinct uids / per-session VMs -- the Daytona backend).
        # A fresh kernel always starts on a clean workspace: rmtree any stale dir a
        # prior kernel for the same session id left behind (else artifacts_capture
        # would re-read those files every exec). Only genuine new-kernel creation
        # reaches here -- open() on a live kernel returns early -- so a warm
        # persist=true session is never wiped mid-computation.
        setup = (
            "import os as _os, shutil as _sh\n"
            f"_os.makedirs({_WORKSPACE_ROOT!r}, mode=0o700, exist_ok=True)\n"
            f"_os.chmod({_WORKSPACE_ROOT!r}, 0o700)\n"
            f"_sh.rmtree({kernel.workspace!r}, ignore_errors=True)\n"
            f"_os.makedirs({kernel.workspace!r}, mode=0o700, exist_ok=True)\n"
            f"_os.chmod({kernel.workspace!r}, 0o700)\n"
            f"_os.chdir({kernel.workspace!r})\n"
        )
        result = self._run(kernel, setup, self._default_timeout)
        if not result.ok:
            raise RuntimeError(f"Sandbox workspace setup failed: {result.error_value}")
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
            ws = websocket.create_connection(
                self._ws_url(kernel.kernel_id),
                timeout=timeout,
                header=self._ws_headers(),
            )
        except Exception as exc:  # noqa: BLE001 - connect failure -> error result, never raise
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
            if msg.get("parent_header", {}).get("msg_id") != msg_id:
                continue

            msg_type = msg.get("msg_type") or msg.get("header", {}).get("msg_type")
            content = msg.get("content", {})

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
                raise IOError(f"put_file failed: {result.error_value}")
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
            raise IOError(f"get_file failed: {result.error_value}")
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
            raise IOError(f"list_files failed: {result.error_value}")
        out = result.stdout
        start = out.find(_FILE_BEGIN)
        end = out.find(_FILE_END)
        if start == -1 or end == -1:
            return []
        return json.loads(out[start + len(_FILE_BEGIN):end])


def _error_result(name: str, value: str) -> ExecResult:
    """Build a failed ExecResult carrying the given error name/value."""
    return ExecResult(status="error", error_name=name, error_value=value, exit_code=-1)
