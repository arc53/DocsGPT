"""Daytona Cloud sandbox: managed, strongly isolated runtimes via the Apache-2.0 Daytona SDK."""

import logging
import posixpath
import re
import threading
from typing import Dict, List, Optional

from application.sandbox.base import (
    CodeSandbox,
    ExecResult,
    Plot,
)

logger = logging.getLogger(__name__)

# Per-session workspace root inside the Daytona sandbox. Relative file paths
# from LLM code and from put_file/get_file share this single directory.
_WORKSPACE_ROOT = "/home/daytona/docsgpt-sandbox"

# Session ids become filesystem path components and Daytona labels; restrict them.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Label key used to find/reattach the Daytona sandbox bound to a DocsGPT session.
_SESSION_LABEL = "docsgpt_session_id"


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
        """Reattach to or create the Daytona sandbox for ``session_id`` and prime its workspace.

        Reattach order: an in-memory handle, then (across process restarts) a live cloud
        sandbox carrying the session label, and only then a fresh ``create``. Enforces
        ``max_sandboxes`` so a flood of sessions cannot run up unbounded paid resources.
        """
        self._validate_session_id(session_id)
        # Wait out any in-flight create/reattach for this session, then reuse its
        # handle; otherwise claim the in-flight slot so we are the sole creator.
        with self._create_cv:
            while session_id in self._creating:
                self._create_cv.wait()
            existing = self._handles.get(session_id)
            if existing is not None:
                return existing.sandbox_id
            self._creating.add(session_id)
        try:
            # Cross-restart reattach: an earlier process may have created (and labelled)
            # a sandbox for this session that is still live in the cloud. Reuse it
            # instead of leaking it behind a brand-new create.
            reattached = self._reattach_existing(session_id)
            if reattached is not None:
                self._prime(reattached)
                return reattached.sandbox_id

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
            self._prime(handle)
            return sandbox_id
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
            matches = list(self._client.list(query))
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
            fresh = self._client.get(handle.sandbox_id)
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
            sandbox = self._client.get(sandbox_id)
            self._client.delete(sandbox)
        except Exception as exc:  # noqa: BLE001 - teardown is best-effort, never raise
            logger.warning("Failed to delete Daytona sandbox by id %s: %s", sandbox_id, exc)

    def remove_path(self, session_id: str, path: str) -> None:
        """Best-effort delete a workspace-relative path (per-render scratch dir); never raises.

        The tools pass a token DIRECTORY (e.g. ``artifacts/{token}``), so the delete is
        recursive — ``fs.delete_file`` with ``recursive=True`` removes a folder and its
        contents (daytona==0.190.1).
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
            handle.sandbox.fs.delete_file(remote, recursive=True)
            return
        except TypeError:
            # Older SDK without the recursive kwarg: fall back to a contained rm -rf.
            pass
        try:
            handle.sandbox.fs.delete_file(remote)
        except Exception:  # noqa: BLE001 - directory delete may need a recursive remove
            quoted = "'" + remote.replace("'", "'\\''") + "'"
            handle.sandbox.process.exec(f"rm -rf {quoted}", timeout=int(self._default_timeout))

    def _prime(self, handle: _Handle) -> None:
        """Create the per-session workspace directory inside the sandbox."""
        try:
            handle.sandbox.fs.create_folder(handle.workspace, "755")
        except Exception as exc:  # noqa: BLE001 - folder may already exist on a reused snapshot
            logger.debug("Workspace folder prime returned: %s", exc)

    # -- Execution -------------------------------------------------------

    def exec(self, session_id: str, code: str, timeout: Optional[float] = None) -> ExecResult:
        """Run ``code`` via Daytona ``code_run``; per-call interpreter, persistent filesystem."""
        handle = self._get_handle(session_id)
        wall = int(timeout or self._default_timeout)
        wrapped = self._with_workspace_cwd(handle.workspace, code)
        try:
            response = handle.sandbox.process.code_run(wrapped, timeout=wall)
        except Exception as exc:  # noqa: BLE001 - any SDK/cloud error -> error result, never raise
            # A cached handle may point at a sandbox Daytona auto-stopped; wake it and
            # retry once. Genuine code errors return a nonzero-exit response (they do
            # NOT raise), so this only retries transport/stopped faults.
            if self._ensure_started(handle):
                try:
                    return self._to_result(handle.sandbox.process.code_run(wrapped, timeout=wall))
                except Exception:  # noqa: BLE001 - second failure -> error result below
                    pass
            return ExecResult(
                status="error",
                error_name=type(exc).__name__,
                error_value=str(exc) or "code_run failed",
                exit_code=-1,
            )
        return self._to_result(response)

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
        )
        return hoisted + prelude + rest

    @staticmethod
    def _split_leading_future_imports(code: str) -> tuple[str, str]:
        """Split leading ``from __future__`` imports (and the blank/comment lines around them) from the rest.

        A module docstring appearing BEFORE a future import is an unsupported edge (rare in
        generated snippets); the common ``from __future__ import annotations`` first-line case
        is handled. Everything from the first real statement onward stays in ``rest``.
        """
        lines = code.splitlines(keepends=True)
        saw_future = False
        split_at = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "" or stripped.startswith("#"):
                continue  # blank/comment: part of the leading run
            if stripped.startswith("from __future__ import"):
                saw_future = True
                continue
            split_at = i  # first real statement: the leading run ends here
            break
        else:
            split_at = len(lines)  # whole snippet was blank/comment/future
        if not saw_future:
            return "", code
        hoisted = "".join(lines[:split_at])
        if hoisted and not hoisted.endswith("\n"):
            hoisted += "\n"
        return hoisted, "".join(lines[split_at:])

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

        truncated = False
        if self._max_output_bytes and len(stdout.encode("utf-8", "ignore")) > self._max_output_bytes:
            stdout = stdout.encode("utf-8", "ignore")[: self._max_output_bytes].decode("utf-8", "ignore")
            stdout += f"\n[output truncated at {self._max_output_bytes} bytes]"
            truncated = True

        result = ExecResult(
            status="ok" if exit_code == 0 else "error",
            stdout=stdout,
            exit_code=exit_code,
            truncated=truncated,
        )
        if exit_code != 0:
            result.error_name = "ExecutionError"
            result.error_value = stdout or f"exited with code {exit_code}"
        if artifacts is not None:
            for chart in getattr(artifacts, "charts", None) or []:
                png = getattr(chart, "png", None)
                if png:
                    result.plots.append(Plot(format="png", content_base64=png))
        return result

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
            logger.warning("put_file failed for %r: %s", dest_path, exc)
            raise IOError(f"put_file failed: {type(exc).__name__}") from exc

    def _upload(self, handle: "_Handle", remote: str, parent: str, data: bytes) -> None:
        """Create the parent folder (best-effort) and upload ``data`` to ``remote``."""
        if parent and parent != handle.workspace:
            try:
                handle.sandbox.fs.create_folder(parent, "755")
            except Exception as folder_exc:  # noqa: BLE001 - folder may already exist
                logger.debug("put_file parent folder create returned: %s", folder_exc)
        handle.sandbox.fs.upload_file(data, remote)

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
                logger.warning("get_file failed for %r: %s", path, exc)
                raise IOError(f"get_file failed: {type(exc).__name__}") from exc
            try:
                data = self._download(handle, remote)
            except IOError:
                raise
            except Exception:  # noqa: BLE001 - second failure -> generic IOError
                logger.warning("get_file failed for %r: %s", path, exc)
                raise IOError(f"get_file failed: {type(exc).__name__}") from exc
        if data is None:
            raise IOError(f"get_file produced no payload for {path!r}")
        data = data if isinstance(data, bytes) else bytes(data)
        # The pre-download size guard may be skipped when get_file_info has no size;
        # enforce the cap against the actual payload so an oversized file never slips through.
        if len(data) > self._max_file_bytes:
            raise IOError(f"file too large: {len(data)} > {self._max_file_bytes} bytes")
        return data

    def _download(self, handle: "_Handle", remote: str) -> object:
        """Fetch ``remote``'s bytes, rejecting a file whose declared size exceeds the cap."""
        info = handle.sandbox.fs.get_file_info(remote)
        size = getattr(info, "size", None)
        if size is not None and size > self._max_file_bytes:
            raise IOError(f"file too large: {size} > {self._max_file_bytes} bytes")
        return handle.sandbox.fs.download_file(remote)

    def list_files(self, session_id: str) -> List[str]:
        """List workspace-relative file paths for ``session_id`` (recursive, never escapes the workspace)."""
        handle = self._get_handle(session_id)
        try:
            return self._list_all(handle)
        except Exception:  # noqa: BLE001 - transport/stopped fault: wake and retry once, else re-raise
            # A cached handle may point at an auto-stopped sandbox; wake it and retry once.
            if self._ensure_started(handle):
                return self._list_all(handle)
            raise

    def _list_all(self, handle: "_Handle") -> List[str]:
        """Walk the workspace subtree for ``handle`` and return workspace-relative file paths."""
        out: List[str] = []
        self._walk(handle.sandbox, handle.workspace, "", out)
        return out

    def _walk(self, sandbox: object, root: str, rel_dir: str, out: List[str]) -> None:
        """Recurse one workspace subtree, appending workspace-relative file paths to ``out``."""
        abs_dir = posixpath.join(root, rel_dir) if rel_dir else root
        try:
            entries = sandbox.fs.list_files(abs_dir)
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
