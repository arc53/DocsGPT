"""In-process broker that routes invocations to active device sessions.

Single-worker assumption (per spec 13.1). Each device has at most one
active SSE session; concurrent invocations queue and drain in FIFO order.

Lifecycle:
1. Agent calls ``RemoteDeviceTool.execute_action`` → ``broker.dispatch_invocation``.
2. If a session is active, the envelope goes on the session's queue; the
   SSE handler reads it and emits to the wire. Otherwise it sits on the
   pending-invocation queue until ``register_session`` is called by the
   next ``GET /api/devices/poll`` -> SSE upgrade.
3. CLI POSTs ack and chunked output back. Output chunks land in the
   invocation's stdout/stderr queue, which the tool's generator drains
   to yield streaming events.
4. Final ``control`` chunk closes the invocation. The tool resolves with
   the aggregated result.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from queue import Empty, Queue
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


# Sentinel object signalling the end of an invocation's output stream.
INVOCATION_DONE = object()


@dataclass
class InvocationState:
    """In-flight invocation: envelope + back-streaming queues."""

    invocation_id: str
    device_id: str
    session_id: str
    envelope: Dict[str, Any]
    output_queue: Queue = field(default_factory=Queue)
    stdout_parts: List[str] = field(default_factory=list)
    stderr_parts: List[str] = field(default_factory=list)
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    decision: Optional[str] = None
    decision_reason: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    completed: threading.Event = field(default_factory=threading.Event)


@dataclass
class SessionState:
    """Active SSE session for one device."""

    session_id: str
    device_id: str
    user_id: str
    invocation_queue: Queue = field(default_factory=Queue)
    last_event_id: int = 0
    invocations: Dict[str, InvocationState] = field(default_factory=dict)
    last_activity_at: float = field(default_factory=time.time)
    closed: threading.Event = field(default_factory=threading.Event)


class DeviceBroker:
    """In-process device registry; thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # device_id -> SessionState (active SSE).
        self._sessions: Dict[str, SessionState] = {}
        # session_id -> device_id (reverse map for fast session-by-id lookup).
        self._session_by_id: Dict[str, str] = {}
        # device_id -> pending invocations (no active session yet).
        self._pending: Dict[str, List[InvocationState]] = {}
        # invocation_id -> InvocationState for ack/output lookup.
        self._invocations: Dict[str, InvocationState] = {}
        # device_id -> session ticket queued for the next poll response.
        self._tickets: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Session lifecycle (CLI side)
    # ------------------------------------------------------------------
    def register_session(self, device_id: str, user_id: str) -> SessionState:
        """Open or refresh the active SSE session for ``device_id``.

        Drains any pending invocations into the session's queue so the
        next SSE read sees them in order. If a previous session is still
        registered, it is closed and replaced (the CLI reconnected).
        """
        with self._lock:
            existing = self._sessions.get(device_id)
            if existing is not None:
                existing.closed.set()
                self._session_by_id.pop(existing.session_id, None)
            session_id = self._tickets.pop(device_id, None) or f"st_{uuid.uuid4().hex}"
            sess = SessionState(
                session_id=session_id,
                device_id=device_id,
                user_id=user_id,
            )
            for inv in self._pending.pop(device_id, []):
                inv.session_id = session_id
                sess.invocations[inv.invocation_id] = inv
                sess.invocation_queue.put(inv)
            self._sessions[device_id] = sess
            self._session_by_id[session_id] = device_id
            return sess

    def close_session(self, session_id: str, *, reason: str = "closed") -> None:
        """Close the session by id; outstanding invocations get an error."""
        with self._lock:
            device_id = self._session_by_id.pop(session_id, None)
            if device_id is None:
                return
            sess = self._sessions.pop(device_id, None)
            if sess is None:
                return
            sess.closed.set()
            for inv in sess.invocations.values():
                if not inv.completed.is_set():
                    inv.error = inv.error or f"session_{reason}"
                    inv.output_queue.put(INVOCATION_DONE)
                    inv.completed.set()
        logger.debug("device session closed: %s (%s)", session_id, reason)

    def get_session(self, session_id: str) -> Optional[SessionState]:
        with self._lock:
            device_id = self._session_by_id.get(session_id)
            if device_id is None:
                return None
            return self._sessions.get(device_id)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------
    def claim_ticket(self, device_id: str) -> Optional[str]:
        """Return a session ticket if the device has work waiting, else None.

        A pending invocation queued before the CLI polls allocates a ticket
        eagerly; the CLI then upgrades to SSE with that ticket within the
        envelope's ``expires_in``.
        """
        with self._lock:
            if not self._pending.get(device_id):
                return None
            existing = self._tickets.get(device_id)
            if existing:
                return existing
            ticket = f"st_{uuid.uuid4().hex}"
            self._tickets[device_id] = ticket
            return ticket

    # ------------------------------------------------------------------
    # Dispatch (server-issued)
    # ------------------------------------------------------------------
    def dispatch_invocation(
        self,
        device_id: str,
        user_id: str,
        envelope: Dict[str, Any],
    ) -> InvocationState:
        """Enqueue an invocation for ``device_id``.

        If there's an active session, drops it onto the session's
        invocation queue. Otherwise parks it in the pending list and
        the next poll will see a ticket.
        """
        invocation_id = envelope["invocation_id"]
        with self._lock:
            sess = self._sessions.get(device_id)
            session_id = sess.session_id if sess else ""
            inv = InvocationState(
                invocation_id=invocation_id,
                device_id=device_id,
                session_id=session_id,
                envelope=envelope,
            )
            self._invocations[invocation_id] = inv
            if sess is not None:
                sess.invocations[invocation_id] = inv
                sess.invocation_queue.put(inv)
                sess.last_activity_at = time.time()
            else:
                self._pending.setdefault(device_id, []).append(inv)
        return inv

    def get_invocation(self, invocation_id: str) -> Optional[InvocationState]:
        with self._lock:
            return self._invocations.get(invocation_id)

    # ------------------------------------------------------------------
    # Output streaming (CLI side)
    # ------------------------------------------------------------------
    def submit_output_chunk(
        self,
        invocation_id: str,
        chunk: Dict[str, Any],
    ) -> bool:
        """Forward a chunk from the CLI to the agent stream's generator."""
        inv = self.get_invocation(invocation_id)
        if inv is None:
            return False
        with self._lock:
            sess = self._sessions.get(inv.device_id)
            if sess is not None:
                sess.last_activity_at = time.time()
            stream = chunk.get("stream")
            if stream == "stdout":
                inv.stdout_parts.append(chunk.get("chunk", ""))
            elif stream == "stderr":
                inv.stderr_parts.append(chunk.get("chunk", ""))
            elif stream == "control":
                inv.exit_code = chunk.get("exit_code")
                inv.duration_ms = chunk.get("duration_ms")
                inv.error = chunk.get("error") or inv.error
                if inv.started_at is None:
                    inv.started_at = time.time()
                inv.finished_at = time.time()
        inv.output_queue.put(chunk)
        if chunk.get("stream") == "control":
            inv.output_queue.put(INVOCATION_DONE)
            inv.completed.set()
        return True

    def submit_ack(
        self,
        invocation_id: str,
        decision: str,
        reason: Optional[str] = None,
    ) -> bool:
        inv = self.get_invocation(invocation_id)
        if inv is None:
            return False
        with self._lock:
            inv.decision = decision
            inv.decision_reason = reason
            inv.started_at = inv.started_at or time.time()
        if decision == "denied":
            inv.error = inv.error or "denied"
            inv.output_queue.put(INVOCATION_DONE)
            inv.completed.set()
        return True

    def drain_output(self, invocation_id: str, timeout: float = 0.5):
        """Yield queued chunks for an invocation; stops on INVOCATION_DONE.

        Used by the tool's generator. Blocks up to ``timeout`` per chunk
        so the caller can interleave with other work.
        """
        inv = self.get_invocation(invocation_id)
        if inv is None:
            return
        while True:
            try:
                item = inv.output_queue.get(timeout=timeout)
            except Empty:
                if inv.completed.is_set():
                    return
                continue
            if item is INVOCATION_DONE:
                return
            yield item

    def cleanup_invocation(self, invocation_id: str) -> None:
        with self._lock:
            self._invocations.pop(invocation_id, None)


_broker_instance: Optional[DeviceBroker] = None
_broker_lock = threading.Lock()


def get_broker() -> DeviceBroker:
    """Return the process-wide ``DeviceBroker`` instance."""
    global _broker_instance
    if _broker_instance is None:
        with _broker_lock:
            if _broker_instance is None:
                _broker_instance = DeviceBroker()
    return _broker_instance
