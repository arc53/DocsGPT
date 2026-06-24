"""Process-wide registry binding session ids to sandbox handles with idle expiry."""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from application.sandbox.base import CodeSandbox, ExecResult


@dataclass
class _Session:
    """Bookkeeping for one bound sandbox session: its TTL and access timestamps."""

    session_id: str
    ttl: float
    created_at: float
    last_access: float = field(default=0.0)

    def is_expired(self, now: float) -> bool:
        """True when the session has been idle longer than its (clamped) TTL."""
        return (now - self.last_access) > self.ttl


class SandboxManager:
    """Binds session ids to a shared backend, clamps TTLs, and reaps idle sessions."""

    def __init__(self, backend: CodeSandbox, max_ttl: float, default_ttl: Optional[float] = None) -> None:
        """Wrap ``backend`` with a registry clamped to ``max_ttl`` seconds per session."""
        self._backend = backend
        self._max_ttl = max_ttl
        self._default_ttl = default_ttl if default_ttl is not None else max_ttl
        self._sessions: Dict[str, _Session] = {}
        self._lock = threading.Lock()

    def _clamp_ttl(self, ttl: Optional[float]) -> float:
        """Return an agent-requested TTL bounded to (0, ``max_ttl``]."""
        if ttl is None:
            ttl = self._default_ttl
        if ttl <= 0:
            return self._default_ttl
        return min(ttl, self._max_ttl)

    def open(self, session_id: str, ttl: Optional[float] = None) -> str:
        """Open (or reuse) the sandbox for ``session_id`` with a clamped TTL."""
        self.reap_expired()
        with self._lock:
            session = self._sessions.get(session_id)
            now = time.monotonic()
            if session is not None:
                session.last_access = now
                handle = self._backend.attach(session_id)
                return handle
            handle = self._backend.open(session_id)
            self._sessions[session_id] = _Session(
                session_id=session_id,
                ttl=self._clamp_ttl(ttl),
                created_at=now,
                last_access=now,
            )
            return handle

    def attach(self, session_id: str) -> str:
        """Reattach to an existing session, refreshing its idle clock."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"No sandbox session bound for {session_id!r}")
            session.last_access = time.monotonic()
        return self._backend.attach(session_id)

    def exec(self, session_id: str, code: str, timeout: Optional[float] = None) -> ExecResult:
        """Execute ``code`` in the bound session, touching its idle clock first."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"No sandbox session bound for {session_id!r}")
            session.last_access = time.monotonic()
        return self._backend.exec(session_id, code, timeout)

    def put_file(self, session_id: str, dest_path: str, data: bytes) -> None:
        """Write ``data`` into the bound session's workspace."""
        self._touch(session_id)
        self._backend.put_file(session_id, dest_path, data)

    def get_file(self, session_id: str, path: str) -> bytes:
        """Read ``path`` from the bound session's workspace."""
        self._touch(session_id)
        return self._backend.get_file(session_id, path)

    def list_files(self, session_id: str) -> List[str]:
        """List files in the bound session's workspace."""
        self._touch(session_id)
        return self._backend.list_files(session_id)

    def close(self, session_id: str) -> None:
        """Tear down the backend runtime and drop the session from the registry."""
        with self._lock:
            self._sessions.pop(session_id, None)
        self._backend.close(session_id)

    def has_session(self, session_id: str) -> bool:
        """True when ``session_id`` is currently bound in the registry."""
        with self._lock:
            return session_id in self._sessions

    def ttl_for(self, session_id: str) -> Optional[float]:
        """Return the clamped TTL bound to ``session_id``, or None if unbound."""
        with self._lock:
            session = self._sessions.get(session_id)
            return session.ttl if session else None

    def _touch(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"No sandbox session bound for {session_id!r}")
            session.last_access = time.monotonic()

    def reap_expired(self) -> List[str]:
        """Close sessions idle past their TTL and return the reaped session ids.

        Extension point: a later hardening slice runs this on a background
        reaper and, before close, flushes workspace files to the artifact
        store (persist-on-reap) so a fresh kernel can re-mount them by
        reference on next access. For now it is a plain idle close.
        """
        now = time.monotonic()
        with self._lock:
            expired = [sid for sid, s in self._sessions.items() if s.is_expired(now)]
            for sid in expired:
                self._sessions.pop(sid, None)
        for sid in expired:
            self._backend.close(sid)
        return expired
