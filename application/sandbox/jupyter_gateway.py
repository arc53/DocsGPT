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
from urllib.parse import urlencode, urlparse, urlunparse

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

    def __init__(self, kernel_id: str, workspace: str) -> None:
        self.kernel_id = kernel_id
        self.workspace = workspace
        self.initialized = False


class JupyterKernelGatewaySandbox(CodeSandbox):
    """Drives one always-on Jupyter Kernel Gateway, one stateful kernel per session."""

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
        self._lock = threading.Lock()

    # -- HTTP helpers ----------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"token {self._auth_token}"
        return headers

    def _ws_url(self, kernel_id: str) -> str:
        parsed = urlparse(self._base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path = f"/api/kernels/{kernel_id}/channels"
        query = urlencode({"token": self._auth_token}) if self._auth_token else ""
        return urlunparse((scheme, parsed.netloc, path, "", query, ""))

    def _get_kernel(self, session_id: str) -> _Kernel:
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
        """Start a fresh kernel for ``session_id`` and prime its workspace cwd."""
        self._validate_session_id(session_id)
        with self._lock:
            existing = self._kernels.get(session_id)
        if existing is not None:
            return existing.kernel_id

        resp = requests.post(
            f"{self._base_url}/api/kernels",
            headers=self._headers(),
            data=json.dumps({"name": self._kernel_name}),
            timeout=self._http_timeout,
        )
        resp.raise_for_status()
        kernel_id = resp.json()["id"]
        workspace = f"{_WORKSPACE_ROOT}/{session_id}"
        kernel = _Kernel(kernel_id, workspace)
        with self._lock:
            self._kernels[session_id] = kernel
        self._prime(kernel)
        return kernel_id

    def attach(self, session_id: str) -> str:
        """Reattach to a still-running kernel for ``session_id``; open a cold one if gone."""
        self._validate_session_id(session_id)
        with self._lock:
            existing = self._kernels.get(session_id)
        if existing is not None and self._kernel_alive(existing.kernel_id):
            return existing.kernel_id
        if existing is not None:
            with self._lock:
                self._kernels.pop(session_id, None)
        logger.warning("Re-attaching session %s to a cold kernel; previous state is lost", session_id)
        return self.open(session_id)

    def close(self, session_id: str) -> None:
        """Delete the gateway kernel for ``session_id`` and drop it from the registry."""
        with self._lock:
            kernel = self._kernels.pop(session_id, None)
        if kernel is None:
            return
        self._delete_kernel(kernel.kernel_id)

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

    def _delete_kernel(self, kernel_id: str) -> None:
        """Best-effort DELETE of a gateway kernel by id (teardown never raises)."""
        try:
            requests.delete(
                f"{self._base_url}/api/kernels/{kernel_id}",
                headers=self._headers(),
                timeout=self._http_timeout,
            )
        except requests.RequestException as exc:  # teardown is best-effort
            logger.warning("Failed to delete kernel %s: %s", kernel_id, exc)

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

    def _interrupt_and_drain(self, ws: websocket.WebSocket, msg_id: str, kernel_id: str) -> None:
        """Interrupt the kernel then drain frames until it idles, leaving the session reusable."""
        self._interrupt(kernel_id)
        drain_deadline = time.monotonic() + self._http_timeout
        while time.monotonic() < drain_deadline:
            try:
                ws.settimeout(max(0.05, drain_deadline - time.monotonic()))
                raw = ws.recv()
            except (websocket.WebSocketTimeoutException, websocket.WebSocketConnectionClosedException):
                return
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
                return

    def _prime(self, kernel: _Kernel) -> None:
        """Create the per-session workspace (mode 0700) and chdir the kernel into it."""
        # 0700 on the root and the per-session dir is defense-in-depth only: every
        # kernel runs under one shared uid here, so this is not a cross-session
        # boundary (that needs distinct uids / per-session VMs -- the Daytona backend).
        setup = (
            "import os as _os\n"
            f"_os.makedirs({_WORKSPACE_ROOT!r}, mode=0o700, exist_ok=True)\n"
            f"_os.chmod({_WORKSPACE_ROOT!r}, 0o700)\n"
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

    def _run(self, kernel: _Kernel, code: str, timeout: float) -> ExecResult:
        """Execute one ``execute_request`` over the WS channel and assemble the reply."""
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
            return self._collect(ws, msg_id, timeout, kernel.kernel_id)
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

    def _collect(self, ws: websocket.WebSocket, msg_id: str, timeout: float, kernel_id: str) -> ExecResult:
        """Read iopub/shell frames until ``execute_reply``/idle, a wall-clock deadline, or a closed socket."""
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
                self._interrupt_and_drain(ws, msg_id, kernel_id)
                break
            try:
                ws.settimeout(remaining)
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                self._fail(result, "TimeoutError", f"execution exceeded {timeout}s")
                self._interrupt_and_drain(ws, msg_id, kernel_id)
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
                    buffered += len(text)
                    if buffered > self._max_output_bytes:
                        truncated = True
                        self._interrupt_and_drain(ws, msg_id, kernel_id)  # runaway output: stop and drain
                        break
                    elif content.get("name") == "stderr":
                        stderr_parts.append(text)
                    else:
                        stdout_parts.append(text)
            elif msg_type in ("execute_result", "display_data"):
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
            stderr_parts.append(f"\n[output truncated at {self._max_output_bytes} bytes]")
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

    def put_file(self, session_id: str, dest_path: str, data: bytes) -> None:
        """Decode ``data`` inside the kernel and write it under the session workspace."""
        kernel = self._get_kernel(session_id)
        encoded = base64.b64encode(data).decode("ascii")
        code = (
            "import base64 as _b64, os as _os\n"
            + _CONTAINMENT_SNIPPET
            + f"_p = _resolve({kernel.workspace!r}, {dest_path!r})\n"
            "_os.makedirs(_os.path.dirname(_p) or '.', exist_ok=True)\n"
            f"_f = open(_p, 'wb'); _f.write(_b64.b64decode({encoded!r})); _f.close()\n"
        )
        result = self._run(kernel, code, self._default_timeout)
        if not result.ok:
            raise IOError(f"put_file failed: {result.error_value}")

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
        result = self._run(kernel, code, self._default_timeout)
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
        result = self._run(kernel, code, self._default_timeout)
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
