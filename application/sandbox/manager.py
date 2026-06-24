"""Process-wide registry binding session ids to sandbox handles with idle expiry."""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from application.sandbox.base import CodeSandbox, ExecResult

logger = logging.getLogger(__name__)


class SandboxCapacityError(RuntimeError):
    """Raised when the concurrent-session cap is reached and no idle session can be freed."""


@dataclass
class _Session:
    """Bookkeeping for one bound sandbox session: its TTL, access timestamps, and backend handle.

    ``handle`` is the backend handle id returned by ``backend.open``; ``None`` while a
    slot is RESERVED (a placeholder occupying a cap slot during a cold backend open that
    runs outside the lock). ``ready`` is False for such a placeholder so reuse/reap/evict
    skip it until the backend open finalizes it.
    """

    session_id: str
    ttl: float
    created_at: float
    last_access: float = field(default=0.0)
    in_use: int = field(default=0)
    handle: Optional[str] = field(default=None)
    ready: bool = field(default=False)

    def is_expired(self, now: float) -> bool:
        """True when the session has been idle longer than its (clamped) TTL."""
        return (now - self.last_access) > self.ttl


class SandboxManager:
    """Binds session ids to a shared backend, clamps TTLs, caps concurrency, and reaps idle sessions."""

    def __init__(
        self,
        backend: CodeSandbox,
        max_ttl: float,
        default_ttl: Optional[float] = None,
        max_sessions: Optional[int] = None,
    ) -> None:
        """Wrap ``backend`` with a registry clamped to ``max_ttl`` and bounded to ``max_sessions``.

        The session cap is per-process/worker: each app or Celery process keeps its
        own registry, so the effective fleet-wide ceiling is ``max_sessions`` times
        the number of live processes.
        """
        self._backend = backend
        self._max_ttl = max_ttl
        self._default_ttl = default_ttl if default_ttl is not None else max_ttl
        self._max_sessions = max_sessions if max_sessions and max_sessions > 0 else None
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
        """Open (or reuse) the sandbox for ``session_id`` with a clamped TTL.

        The lock guards ONLY the in-memory registry and refcounts; the (potentially
        ~60s) cold backend open runs WITHOUT the lock held so it can never serialize
        other lock-taking methods. Flow:

        1. Under the lock: if the session already exists and is ready, refresh it and
           return its cached handle (reuse never does backend I/O). Otherwise reap
           idle-expired sessions, evict an LRU-idle victim if at capacity, then RESERVE
           a placeholder slot for ``session_id`` so concurrent opens can't overshoot
           the cap.
        2. Outside the lock: call ``backend.open`` (cold start) and close any reaped /
           evicted victims' captured backend resources.
        3. Under the lock: finalize the placeholder into a ready session. On failure,
           free the reserved slot and re-raise.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            now = time.monotonic()
            if session is not None and session.ready:
                session.last_access = now
                return session.handle
            # A placeholder for this id means another thread is mid cold-open; refresh
            # it and re-reserve below. Both threads call the (idempotent) backend.open,
            # which dedupes by session id, so no cap overshoot and no orphaned runtime.
            reaped = self._reap_locked(now)
            evicted = self._make_room_locked()
            self._sessions[session_id] = _Session(
                session_id=session_id,
                ttl=self._clamp_ttl(ttl),
                created_at=now,
                last_access=now,
            )

        # Cold backend open and victim teardown run OUTSIDE the lock.
        for sid, handle in reaped:
            self._close_backend(sid, handle)
        if evicted is not None:
            self._close_backend(evicted[0], evicted[1])
        try:
            handle = self._backend.open(session_id)
        except Exception:
            # Free the reserved slot so a failed cold open never leaks a cap slot.
            with self._lock:
                placeholder = self._sessions.get(session_id)
                if placeholder is not None and not placeholder.ready:
                    self._sessions.pop(session_id, None)
            self._close_backend(session_id, None)  # best-effort: tear down anything created
            raise

        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                # Slot was reclaimed (e.g. closed) while we opened; drop the new runtime.
                stale = handle
            else:
                session.handle = handle
                session.ready = True
                session.last_access = time.monotonic()
                stale = None
        if stale is not None:
            self._close_backend(session_id, stale)
        return handle

    def _make_room_locked(self) -> Optional[Tuple[str, Optional[str]]]:
        """Evict the LRU-idle ready session when at capacity; return (id, handle) to close, else None.

        Caller holds the lock. The victim is removed from the registry here so its slot
        is freed for the reserving caller; its backend ``close`` is deferred to outside
        the lock (keyed by the captured handle so a concurrent re-open of the same id
        is never torn down). Raises ``SandboxCapacityError`` when the registry is full
        and every session is busy or still opening.
        """
        if self._max_sessions is None or len(self._sessions) < self._max_sessions:
            return None
        idle = [s for s in self._sessions.values() if s.ready and s.in_use == 0]
        if not idle:
            raise SandboxCapacityError(
                f"sandbox session cap reached ({self._max_sessions} live, all busy); cannot open another"
            )
        victim = min(idle, key=lambda s: s.last_access)
        self._sessions.pop(victim.session_id, None)
        logger.info("SandboxManager evicting LRU-idle session %s to honor cap", victim.session_id)
        return (victim.session_id, victim.handle)

    def attach(self, session_id: str) -> str:
        """Reattach to an existing session, refreshing its idle clock.

        Returns the cached handle without backend I/O for a ready session; falls back
        to ``backend.attach`` (outside the lock) only when no handle is cached yet.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"No sandbox session bound for {session_id!r}")
            session.last_access = time.monotonic()
            cached = session.handle
        if cached is not None:
            return cached
        return self._backend.attach(session_id)

    def exec(self, session_id: str, code: str, timeout: Optional[float] = None) -> ExecResult:
        """Execute ``code`` in the bound session, holding it in-use so a reap/evict can't pull it."""
        self._enter(session_id)
        try:
            return self._backend.exec(session_id, code, timeout)
        finally:
            self._leave(session_id)

    def put_file(self, session_id: str, dest_path: str, data: bytes) -> None:
        """Write ``data`` into the bound session's workspace."""
        self._enter(session_id)
        try:
            self._backend.put_file(session_id, dest_path, data)
        finally:
            self._leave(session_id)

    def get_file(self, session_id: str, path: str) -> bytes:
        """Read ``path`` from the bound session's workspace."""
        self._enter(session_id)
        try:
            return self._backend.get_file(session_id, path)
        finally:
            self._leave(session_id)

    def list_files(self, session_id: str) -> List[str]:
        """List files in the bound session's workspace."""
        self._enter(session_id)
        try:
            return self._backend.list_files(session_id)
        finally:
            self._leave(session_id)

    def remove_path(self, session_id: str, path: str) -> None:
        """Best-effort delete a workspace-relative path; never raises (cleanup must not fail an op)."""
        try:
            self._enter(session_id)
        except KeyError:
            return
        try:
            remover = getattr(self._backend, "remove_path", None)
            if callable(remover):
                remover(session_id, path)
            else:
                self._remove_via_exec(session_id, path)
        except Exception:
            logger.exception("SandboxManager: best-effort remove_path failed for %r", path)
        finally:
            self._leave(session_id)

    def _remove_via_exec(self, session_id: str, path: str) -> None:
        """Fallback workspace cleanup: run a contained shutil.rmtree of the relative path."""
        self._backend.exec(session_id, self._build_remove_program(path), None)

    @staticmethod
    def _build_remove_program(path: str) -> str:
        """Build the contained shutil.rmtree program for ``path`` with a workspace-root guard."""
        # ``path`` is a server-controlled token dir literal; it is passed as a
        # repr so its contents are never interpreted as code, and the backend
        # already chdirs into the per-session workspace before running. The
        # guard rejects absolute, traversal, and empty/'.'/'./' paths so a caller
        # can never rmtree the whole workspace root.
        return (
            "import os, shutil\n"
            f"_p = {path!r}\n"
            "if _p and not _p.startswith('/') and '..' not in _p.split('/') and os.path.normpath(_p) != '.':\n"
            "    shutil.rmtree(_p, ignore_errors=True)\n"
        )

    def close(self, session_id: str) -> None:
        """Tear down the backend runtime and drop the session from the registry.

        The backend ``close`` runs OUTSIDE the lock (it may be slow network I/O) and is
        keyed by the captured handle so it tears down only the resource this session
        owned, never one a concurrent re-open created.
        """
        with self._lock:
            session = self._sessions.pop(session_id, None)
            handle = session.handle if session is not None else None
        self._close_backend(session_id, handle)

    def has_session(self, session_id: str) -> bool:
        """True when ``session_id`` is currently bound (ready or opening) in the registry."""
        with self._lock:
            return session_id in self._sessions

    def session_count(self) -> int:
        """Return the number of sessions currently bound (ready or reserved) in the registry."""
        with self._lock:
            return len(self._sessions)

    def ttl_for(self, session_id: str) -> Optional[float]:
        """Return the clamped TTL bound to ``session_id``, or None if unbound."""
        with self._lock:
            session = self._sessions.get(session_id)
            return session.ttl if session else None

    def _enter(self, session_id: str) -> None:
        """Touch the idle clock and mark the session in-use so a concurrent reap/evict skips it."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or not session.ready:
                raise KeyError(f"No sandbox session bound for {session_id!r}")
            session.last_access = time.monotonic()
            session.in_use += 1

    def _leave(self, session_id: str) -> None:
        """Release an in-use hold taken by ``_enter`` (idempotent if the session was closed)."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None and session.in_use > 0:
                session.in_use -= 1
                session.last_access = time.monotonic()

    def _close_backend(self, session_id: str, handle: Optional[str]) -> None:
        """Close the SPECIFIC backend resource captured for this session, best-effort.

        When the backend exposes ``close_handle``, the captured handle id is passed so a
        concurrent re-open of the same ``session_id`` (which created a new backend handle)
        is never the one torn down. Backends without that hook fall back to ``close`` by
        id, which is correct for callers (``close``/reap/failed-open) where no concurrent
        re-open of a still-registered session can be in flight.
        """
        try:
            closer = getattr(self._backend, "close_handle", None)
            if handle is not None and callable(closer):
                closer(session_id, handle)
            else:
                self._backend.close(session_id)
        except Exception:
            logger.exception("SandboxManager: backend close failed for %s", session_id)

    def reap_expired(self) -> List[str]:
        """Close sessions idle past their TTL and return the reaped session ids.

        Artifacts are persisted eagerly by the tools/code node right after each
        exec, so a session's workspace is scratch: reaping only closes the kernel
        and never loses a user-facing artifact. Busy (in-use) sessions are left
        alone so a reap can't pull a workspace out from under a running exec.
        """
        now = time.monotonic()
        with self._lock:
            expired = self._reap_locked(now)
        for sid, handle in expired:
            self._close_backend(sid, handle)
        return [sid for sid, _ in expired]

    def _reap_locked(self, now: float) -> List[Tuple[str, Optional[str]]]:
        """Pop idle-expired ready sessions from the registry; return (id, handle) pairs to close.

        Caller holds the lock. Placeholders (not yet ready) and busy sessions are left
        alone. The backend close of each popped session is deferred to outside the lock.
        """
        expired = [
            (sid, s.handle)
            for sid, s in self._sessions.items()
            if s.ready and s.in_use == 0 and s.is_expired(now)
        ]
        for sid, _ in expired:
            self._sessions.pop(sid, None)
        return expired
