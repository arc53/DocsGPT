"""Redis-backed broker that routes invocations to active device sessions.

The device CLI only ever talks to the web process (poll / SSE / output
POST), but an agent may dispatch a command from *any* process — notably a
Celery worker during a scheduled run. An in-memory broker can't bridge
that gap: the worker and the web process don't share Python memory, so a
worker-side dispatch never reaches the web-side SSE session and the tool
times out. Routing through Redis makes every hop cross-process.

What lives in Redis (shared) vs. in the process (ephemeral):

* ``dev:cmd:{device_id}``   — list of queued command envelopes (JSON).
* ``dev:ticket:{device_id}``— poll-issued SSE upgrade ticket (string, TTL).
* ``dev:inv:{invocation_id}``— invocation metadata hash (status, result).
* ``dev:out:{invocation_id}``— stream of stdout/stderr/control chunks.
* ``SessionState`` is per-connection state for the one SSE handler that
  owns the live socket; it stays in that process's memory.

Lifecycle:
1. Agent (any process) calls ``dispatch_invocation`` → metadata hash + an
   RPUSH onto the device's command list.
2. The web SSE handler blocks on that list (``next_command``) and emits
   each envelope to the wire; an offline device leaves the envelope queued
   until its next ``/poll`` issues a ticket and upgrades to SSE.
3. The CLI POSTs ack + chunked output back; ``submit_output_chunk`` XADDs
   chunks to the invocation's output stream and updates the hash.
4. A ``control`` chunk closes the invocation; ``drain_output`` (in the
   dispatching process) reads the stream from the start and stops on it.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, Optional

from application.cache import get_redis_instance
from application.core.settings import settings


logger = logging.getLogger(__name__)


# Kept for backwards compatibility with callers/tests importing the
# sentinel; the Redis path signals end-of-output with a ``control`` chunk.
INVOCATION_DONE = object()


def _cmd_key(device_id: str) -> str:
    return f"dev:cmd:{device_id}"


def _ticket_key(device_id: str) -> str:
    return f"dev:ticket:{device_id}"


def _inv_key(invocation_id: str) -> str:
    return f"dev:inv:{invocation_id}"


def _out_key(invocation_id: str) -> str:
    return f"dev:out:{invocation_id}"


def _as_str(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return str(value)


@dataclass
class Invocation:
    """Snapshot of an invocation's cross-process state.

    Returned by ``dispatch_invocation`` (fresh) and ``get_invocation`` (read
    from Redis). Carries enough for ownership checks and audit without the
    caller touching Redis directly.
    """

    invocation_id: str
    device_id: str
    completed: bool = False
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    stdout_bytes: int = 0
    stderr_bytes: int = 0


@dataclass
class SessionState:
    """Per-connection state for the SSE handler that owns the live socket."""

    session_id: str
    device_id: str
    user_id: str
    last_event_id: int = 0
    last_activity_at: float = field(default_factory=time.time)
    closed: threading.Event = field(default_factory=threading.Event)


class DeviceBroker:
    """Cross-process device registry backed by Redis.

    Redis is the source of truth for queued commands, output, and tickets,
    so dispatch and drain work regardless of which process they run in. A
    small in-memory map of live SSE sessions stays local to the web process
    that holds each socket (sessions are inherently per-connection).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions_by_id: Dict[str, SessionState] = {}
        self._sessions_by_device: Dict[str, SessionState] = {}

    # ------------------------------------------------------------------
    # Session lifecycle (web process / CLI side)
    # ------------------------------------------------------------------
    def register_session(self, device_id: str, user_id: str) -> SessionState:
        """Open the SSE session for ``device_id``, adopting its poll ticket.

        The poll-issued ticket becomes the ``session_id`` so the URL the CLI
        opens matches the live session. A previous local session for the
        same device is closed and replaced (the CLI reconnected).
        """
        redis = get_redis_instance()
        issued = None
        if redis is not None:
            try:
                issued = redis.get(_ticket_key(device_id))
                if issued is not None:
                    redis.delete(_ticket_key(device_id))
            except Exception:
                logger.exception("ticket lookup failed for %s", device_id)
        session_id = _as_str(issued) if issued else f"st_{uuid.uuid4().hex}"
        sess = SessionState(
            session_id=session_id, device_id=device_id, user_id=user_id
        )
        with self._lock:
            prior = self._sessions_by_device.get(device_id)
            if prior is not None:
                prior.closed.set()
                self._sessions_by_id.pop(prior.session_id, None)
            self._sessions_by_device[device_id] = sess
            self._sessions_by_id[session_id] = sess
        return sess

    def close_session(self, session_id: str, *, reason: str = "closed") -> None:
        """Close the local session by id.

        Queued-but-undelivered commands stay on the device's Redis list and
        are picked up by the next session; an in-flight command whose socket
        drops falls back to the tool's own drain deadline.
        """
        with self._lock:
            sess = self._sessions_by_id.pop(session_id, None)
            if sess is None:
                return
            sess.closed.set()
            if self._sessions_by_device.get(sess.device_id) is sess:
                self._sessions_by_device.pop(sess.device_id, None)
        logger.debug("device session closed: %s (%s)", session_id, reason)

    def get_session(self, session_id: str) -> Optional[SessionState]:
        with self._lock:
            return self._sessions_by_id.get(session_id)

    def next_command(
        self, session: SessionState, timeout: float = 1.0
    ) -> Optional[Dict[str, Any]]:
        """Block up to ``timeout`` for the next queued command envelope.

        Returns the decoded envelope, or ``None`` on timeout so the SSE
        handler can emit a keepalive and re-check the session lifecycle.
        """
        redis = get_redis_instance()
        if redis is None:
            time.sleep(timeout)
            return None
        try:
            popped = redis.blpop(_cmd_key(session.device_id), timeout=timeout)
        except Exception:
            logger.exception("blpop failed for %s", session.device_id)
            time.sleep(timeout)
            return None
        if not popped:
            return None
        _key, raw = popped
        try:
            envelope = json.loads(_as_str(raw))
        except (TypeError, ValueError):
            logger.warning("dropping malformed command envelope")
            return None
        if not isinstance(envelope, dict):
            return None
        # Drop an envelope whose invocation was already reaped (timed out /
        # cleaned up) after it was queued, so a command the user already saw
        # fail can't still run on the device. Best-effort — it narrows but does
        # not fully close the BLPOP-vs-cleanup window (see cleanup_invocation).
        inv_id = envelope.get("invocation_id")
        if inv_id and self.get_invocation(inv_id) is None:
            logger.debug("dropping reaped invocation %s", inv_id)
            return None
        return envelope

    # ------------------------------------------------------------------
    # Polling / tickets
    # ------------------------------------------------------------------
    def claim_ticket(self, device_id: str, ttl_seconds: float) -> Optional[str]:
        """Return an SSE upgrade ticket iff the device has queued work.

        Reuses an unexpired ticket so repeated polls don't churn it; the
        ticket's Redis TTL doubles as the advertised ``expires_in`` window.
        """
        redis = get_redis_instance()
        if redis is None:
            return None
        try:
            if redis.llen(_cmd_key(device_id)) <= 0:
                return None
            existing = redis.get(_ticket_key(device_id))
            if existing:
                return _as_str(existing)
            ticket = f"st_{uuid.uuid4().hex}"
            redis.set(_ticket_key(device_id), ticket, ex=int(ttl_seconds))
            return ticket
        except Exception:
            logger.exception("claim_ticket failed for %s", device_id)
            return None

    def validate_ticket(self, device_id: str, session_id: str) -> bool:
        """True iff ``session_id`` is the unexpired ticket issued to the device.

        An absent, mismatched, or expired ticket is rejected; expiry is
        enforced by Redis's TTL (a ``GET`` of an expired key returns nil).
        """
        if not session_id:
            return False
        redis = get_redis_instance()
        if redis is None:
            return False
        try:
            issued = redis.get(_ticket_key(device_id))
        except Exception:
            logger.exception("validate_ticket failed for %s", device_id)
            return False
        return issued is not None and _as_str(issued) == session_id

    # ------------------------------------------------------------------
    # Dispatch (server-issued, any process)
    # ------------------------------------------------------------------
    def dispatch_invocation(
        self,
        device_id: str,
        user_id: str,
        envelope: Dict[str, Any],
    ) -> Invocation:
        """Queue an invocation for ``device_id`` and record its metadata.

        Writes the metadata hash, then RPUSHes the envelope onto the
        device's command list. A live SSE session draining the list picks it
        up immediately; otherwise it waits for the next poll-issued ticket.
        """
        invocation_id = envelope["invocation_id"]
        inv = Invocation(invocation_id=invocation_id, device_id=device_id)
        redis = get_redis_instance()
        if redis is None:
            inv.error = "device broker unavailable"
            inv.completed = True
            return inv
        envelope_json = json.dumps(envelope)
        try:
            redis.hset(
                _inv_key(invocation_id),
                mapping={
                    "device_id": device_id,
                    "user_id": user_id,
                    "envelope": envelope_json,
                    "completed": "0",
                    "stdout_bytes": "0",
                    "stderr_bytes": "0",
                },
            )
            redis.expire(_inv_key(invocation_id), self._inv_ttl())
            redis.rpush(_cmd_key(device_id), envelope_json)
            redis.expire(_cmd_key(device_id), self._cmd_ttl())
        except Exception:
            logger.exception("dispatch_invocation failed for %s", invocation_id)
            # Don't strand the metadata hash (it holds the plaintext command)
            # if the queue write failed partway through.
            try:
                redis.delete(_inv_key(invocation_id))
            except Exception:
                logger.debug(
                    "cleanup after failed dispatch failed for %s", invocation_id
                )
            inv.error = "device broker dispatch failed"
            inv.completed = True
        return inv

    def get_invocation(self, invocation_id: str) -> Optional[Invocation]:
        """Read an invocation's current metadata snapshot from Redis."""
        redis = get_redis_instance()
        if redis is None:
            return None
        try:
            raw = redis.hgetall(_inv_key(invocation_id))
        except Exception:
            logger.exception("get_invocation failed for %s", invocation_id)
            return None
        if not raw:
            return None
        h = {_as_str(k): _as_str(v) for k, v in raw.items()}
        return Invocation(
            invocation_id=invocation_id,
            device_id=h.get("device_id", ""),
            completed=h.get("completed") == "1",
            exit_code=_to_int(h.get("exit_code")),
            duration_ms=_to_int(h.get("duration_ms")),
            error=h.get("error") or None,
            started_at=_to_float(h.get("started_at")),
            finished_at=_to_float(h.get("finished_at")),
            stdout_bytes=_to_int(h.get("stdout_bytes")) or 0,
            stderr_bytes=_to_int(h.get("stderr_bytes")) or 0,
        )

    # ------------------------------------------------------------------
    # Output streaming (web process / CLI side)
    # ------------------------------------------------------------------
    def submit_output_chunk(
        self, invocation_id: str, chunk: Dict[str, Any]
    ) -> bool:
        """Forward one CLI output chunk to the dispatching process's drain.

        Updates the metadata hash (byte counts; result fields on the closing
        ``control`` chunk) and XADDs the chunk to the invocation's output
        stream. Returns ``False`` for an unknown invocation.
        """
        redis = get_redis_instance()
        if redis is None:
            return False
        key = _inv_key(invocation_id)
        try:
            device_id = redis.hget(key, "device_id")
        except Exception:
            logger.exception("submit_output_chunk read failed for %s", invocation_id)
            return False
        if device_id is None:
            return False
        device_id = _as_str(device_id)
        now = time.time()
        stream = chunk.get("stream")
        try:
            # Append to the output stream BEFORE flipping completion state, so a
            # reader that observes completed=1 is guaranteed the chunk (and every
            # earlier one) is already on the stream — otherwise drain could see
            # completion and stop before the control chunk lands.
            redis.xadd(
                _out_key(invocation_id),
                {"c": json.dumps(chunk)},
                maxlen=self._out_maxlen(),
                approximate=True,
            )
            redis.expire(_out_key(invocation_id), self._inv_ttl())
            if stream in ("stdout", "stderr"):
                text = chunk.get("chunk")
                if isinstance(text, str):
                    field = "stdout_bytes" if stream == "stdout" else "stderr_bytes"
                    redis.hincrby(key, field, len(text.encode("utf-8")))
            elif stream == "control":
                redis.hsetnx(key, "started_at", repr(now))
                mapping = {"completed": "1", "finished_at": repr(now)}
                if chunk.get("exit_code") is not None:
                    mapping["exit_code"] = str(int(chunk["exit_code"]))
                if chunk.get("duration_ms") is not None:
                    mapping["duration_ms"] = str(int(chunk["duration_ms"]))
                if chunk.get("error"):
                    mapping["error"] = _as_str(chunk["error"])
                redis.hset(key, mapping=mapping)
            redis.expire(key, self._inv_ttl())
        except Exception:
            logger.exception("submit_output_chunk failed for %s", invocation_id)
            return False
        # Keep a co-located SSE session alive while output flows (single-worker
        # web tier); a cross-worker session relies on its own keepalive.
        with self._lock:
            sess = self._sessions_by_device.get(device_id)
        if sess is not None:
            sess.last_activity_at = now
        return True

    def submit_ack(
        self,
        invocation_id: str,
        decision: str,
        reason: Optional[str] = None,
    ) -> bool:
        """Record the CLI's accept/deny decision for an invocation."""
        redis = get_redis_instance()
        if redis is None:
            return False
        key = _inv_key(invocation_id)
        try:
            if not redis.exists(key):
                return False
            now = time.time()
            mapping = {"decision": decision}
            if reason:
                mapping["decision_reason"] = reason
            redis.hset(key, mapping=mapping)
            redis.hsetnx(key, "started_at", repr(now))
            redis.expire(key, self._inv_ttl())
            if decision == "denied":
                # XADD the synthetic control chunk BEFORE marking completed, so a
                # racing drain that observes completed=1 always finds the chunk
                # and reports "denied" rather than a false timeout.
                redis.xadd(
                    _out_key(invocation_id),
                    {"c": json.dumps(
                        {"stream": "control", "exit_code": None, "error": "denied"}
                    )},
                    maxlen=self._out_maxlen(),
                    approximate=True,
                )
                redis.expire(_out_key(invocation_id), self._inv_ttl())
                redis.hset(
                    key,
                    mapping={
                        "completed": "1",
                        "error": "denied",
                        "finished_at": repr(now),
                    },
                )
        except Exception:
            logger.exception("submit_ack failed for %s", invocation_id)
            return False
        return True

    def drain_output(
        self,
        invocation_id: str,
        timeout: float = 0.5,
        deadline: Optional[float] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Yield queued output chunks for an invocation; stop on ``control``.

        Reads the invocation's output stream from the start (so chunks
        XADDed before draining began are never missed) and blocks up to
        ``timeout`` per read. ``deadline`` is an absolute ``time.time()``;
        once it passes with no closing ``control`` chunk the generator
        returns so a device that never responds can't loop forever.
        """
        redis = get_redis_instance()
        if redis is None:
            yield {
                "stream": "control",
                "exit_code": None,
                "error": "device broker unavailable",
            }
            return
        last_id = "0-0"
        block_ms = max(1, int(timeout * 1000))
        out_key = _out_key(invocation_id)
        # ``resp`` is parsed as the RESP2 list shape ``[[key, [(id, fields)]]]``;
        # the client must stay protocol=2 (redis-py default — see cache.py).
        tail_flush = False
        while True:
            try:
                # On the final sweep, read non-blocking (block=None) so any
                # entries that landed after the prior empty read are drained
                # before returning — closing the completion-vs-control race.
                resp = redis.xread(
                    {out_key: last_id},
                    count=200,
                    block=None if tail_flush else block_ms,
                )
            except Exception:
                logger.exception("xread failed for %s", invocation_id)
                return
            if not resp:
                if tail_flush:
                    return
                done = self._is_completed(redis, invocation_id)
                timed_out = deadline is not None and time.time() >= deadline
                if done or timed_out:
                    # One final non-blocking sweep from last_id, then stop.
                    tail_flush = True
                continue
            for _stream_key, entries in resp:
                for entry_id, fields in entries:
                    last_id = _as_str(entry_id)
                    raw = fields.get(b"c")
                    if raw is None:
                        raw = fields.get("c")
                    if raw is None:
                        continue
                    try:
                        chunk = json.loads(_as_str(raw))
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(chunk, dict):
                        continue
                    if chunk.get("stream") in ("stdout", "stderr", "control"):
                        yield chunk
                    if chunk.get("stream") == "control":
                        return

    def cleanup_invocation(self, invocation_id: str) -> None:
        """Drop an invocation's Redis state, including any undelivered command.

        Deletes the metadata hash first so a concurrent ``next_command`` that
        just BLPOPped this envelope re-checks ``get_invocation``, sees it gone,
        and drops it instead of delivering a command the user already saw fail;
        the ``LREM`` then clears it for the still-queued (offline-device) case.
        Best-effort: a delivery that wins a tight race with the delete can still
        reach the device once, and that run's output is discarded.
        """
        redis = get_redis_instance()
        if redis is None:
            return
        try:
            raw = redis.hgetall(_inv_key(invocation_id))
            device_id = envelope_json = None
            if raw:
                h = {_as_str(k): _as_str(v) for k, v in raw.items()}
                device_id = h.get("device_id")
                envelope_json = h.get("envelope")
            redis.delete(_inv_key(invocation_id))
            redis.delete(_out_key(invocation_id))
            if device_id and envelope_json:
                redis.lrem(_cmd_key(device_id), 0, envelope_json)
        except Exception:
            logger.exception("cleanup_invocation failed for %s", invocation_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _is_completed(redis, invocation_id: str) -> bool:
        try:
            return _as_str(redis.hget(_inv_key(invocation_id), "completed")) == "1"
        except Exception:
            return False

    @staticmethod
    def _inv_ttl() -> int:
        return int(getattr(settings, "REMOTE_DEVICE_INVOCATION_TTL_SECONDS", 900))

    @staticmethod
    def _cmd_ttl() -> int:
        return int(getattr(settings, "REMOTE_DEVICE_CMD_QUEUE_TTL_SECONDS", 900))

    @staticmethod
    def _out_maxlen() -> int:
        return int(getattr(settings, "REMOTE_DEVICE_OUTPUT_STREAM_MAXLEN", 10_000))


def _to_int(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Optional[str]) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
