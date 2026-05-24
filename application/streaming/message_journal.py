"""Per-yield journal write for the chat-stream snapshot+tail pattern.

``record_event`` inserts into ``message_events`` and publishes to
``channel:{message_id}``. Both are best-effort; the INSERT commits
before the publish so a fast reconnect sees the row. See
``docs/runbooks/sse-notifications.md``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError

from application.storage.db.repositories.message_events import (
    MessageEventsRepository,
)
from application.storage.db.session import db_readonly, db_session
from application.streaming.broadcast_channel import Topic
from application.streaming.event_replay import encode_pubsub_message
from application.streaming.keys import message_topic_name

logger = logging.getLogger(__name__)


# Tunables for ``BatchedJournalWriter``. A streaming answer emits ~100s
# of ``answer`` chunks per response; without batching, that's one PG
# transaction per yield in the WSGI thread. With these defaults, ~10x
# fewer commits at the cost of a ≤100ms reconnect-visibility lag for
# any event still sitting in the buffer.
DEFAULT_BATCH_SIZE = 16
DEFAULT_BATCH_INTERVAL_MS = 100


def _strip_null_bytes(value: Any) -> Any:
    """Recursively strip ``\\x00`` from string keys/values in ``value``.

    Postgres JSONB rejects the NUL escape; an LLM emitting a stray NUL
    in a chunk would otherwise raise ``DataError`` at INSERT and the row
    would be lost from the journal (live stream proceeds, reconnect
    snapshot misses the chunk). Mirrors the strip already done in
    ``parser/embedding_pipeline.py`` and
    ``api/user/attachments/routes.py``.
    """
    if isinstance(value, str):
        return value.replace("\x00", "") if "\x00" in value else value
    if isinstance(value, dict):
        return {
            (k.replace("\x00", "") if isinstance(k, str) and "\x00" in k else k):
            _strip_null_bytes(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_strip_null_bytes(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_strip_null_bytes(item) for item in value)
    return value


def record_event(
    message_id: str,
    sequence_no: int,
    event_type: str,
    payload: Optional[dict[str, Any]] = None,
) -> bool:
    """Journal one SSE event and publish it live. Best-effort.

    ``payload`` must be a ``dict`` or ``None`` (non-dicts are dropped so
    live and replay envelopes stay byte-identical). Returns ``True`` when
    the journal INSERT committed. Never raises.
    """
    if not message_id or not event_type:
        logger.warning(
            "record_event called without message_id/event_type "
            "(message_id=%r, event_type=%r)",
            message_id,
            event_type,
        )
        return False

    if payload is None:
        materialised_payload: dict[str, Any] = {}
    elif isinstance(payload, dict):
        materialised_payload = _strip_null_bytes(payload)
    else:
        logger.warning(
            "record_event called with non-dict payload "
            "(message_id=%s seq=%s type=%s payload_type=%s) — dropping",
            message_id,
            sequence_no,
            event_type,
            type(payload).__name__,
        )
        return False

    journal_committed = False
    # The seq we actually managed to write. Diverges from
    # ``sequence_no`` only on the IntegrityError-retry path below.
    materialised_seq = sequence_no
    try:
        # Short-lived per-event transaction. Critical for visibility:
        # the reconnect endpoint reads the journal from a separate
        # connection and only sees committed rows.
        with db_session() as conn:
            MessageEventsRepository(conn).record(
                message_id, sequence_no, event_type, materialised_payload
            )
        journal_committed = True
    except IntegrityError:
        # Composite-PK collision on (message_id, sequence_no). Most
        # likely cause is a stale ``latest_sequence_no`` seed on a
        # continuation retry — the route read MAX(seq) from a separate
        # connection before another writer committed past it. Look up
        # the live latest and retry once with latest+1 so the event is
        # not silently lost. Bounded to a single retry — if two
        # writers keep racing in lockstep the route-level retry will
        # converge them across attempts.
        try:
            with db_readonly() as conn:
                latest = MessageEventsRepository(conn).latest_sequence_no(
                    message_id
                )
            materialised_seq = (latest if latest is not None else -1) + 1
            with db_session() as conn:
                MessageEventsRepository(conn).record(
                    message_id,
                    materialised_seq,
                    event_type,
                    materialised_payload,
                )
            journal_committed = True
            logger.info(
                "record_event: collision at seq=%s recovered → wrote at "
                "seq=%s message_id=%s type=%s",
                sequence_no,
                materialised_seq,
                message_id,
                event_type,
            )
        except IntegrityError:
            # Second collision under the same retry — give up and log.
            # The route's nonlocal counter will continue at
            # ``sequence_no+1`` on the next emit; the next call may
            # land cleanly past the contended window.
            logger.warning(
                "record_event: IntegrityError persists after seq+1 retry; "
                "dropping. message_id=%s original_seq=%s retry_seq=%s "
                "type=%s",
                message_id,
                sequence_no,
                materialised_seq,
                event_type,
            )
        except Exception:
            logger.exception(
                "record_event: retry path failed unexpectedly "
                "(message_id=%s seq=%s type=%s)",
                message_id,
                sequence_no,
                event_type,
            )
    except Exception:
        logger.exception(
            "message_events INSERT failed: message_id=%s seq=%s type=%s",
            message_id,
            sequence_no,
            event_type,
        )

    try:
        # Publish using ``materialised_seq`` so the live pubsub frame
        # matches the journal row that other clients will snapshot on
        # reconnect. The original POST stream's SSE ``id:`` still
        # carries the caller's ``sequence_no`` — a reconnect from that
        # client will receive the same event at ``materialised_seq``
        # on the snapshot, which is a benign duplicate (the slice's
        # ``max_replayed_seq`` advances past it). No-collision case:
        # ``materialised_seq == sequence_no`` and this is identical to
        # the prior behaviour.
        wire = encode_pubsub_message(
            message_id, materialised_seq, event_type, materialised_payload
        )
        Topic(message_topic_name(message_id)).publish(wire)
    except Exception:
        logger.exception(
            "channel:%s publish failed: seq=%s type=%s",
            message_id,
            materialised_seq,
            event_type,
        )

    return journal_committed


class BatchedJournalWriter:
    """Per-stream journal writer that batches PG INSERTs.

    One writer per ``message_id``; ``record()`` buffers events and flushes
    on size/time/``close()`` triggers. Pubsub publishes fire only after the
    INSERT commits. On ``IntegrityError`` falls back to per-row writes.
    """

    def __init__(
        self,
        message_id: str,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        batch_interval_ms: int = DEFAULT_BATCH_INTERVAL_MS,
    ) -> None:
        self._message_id = message_id
        self._batch_size = batch_size
        self._batch_interval_ms = batch_interval_ms
        self._buffer: list[tuple[int, str, dict[str, Any]]] = []
        self._last_flush_mono_ms = time.monotonic() * 1000.0
        self._closed = False

    def record(
        self,
        sequence_no: int,
        event_type: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Buffer one event; maybe flush. Publish happens after journal commit."""
        if self._closed:
            logger.warning(
                "BatchedJournalWriter.record after close: "
                "message_id=%s seq=%s type=%s",
                self._message_id,
                sequence_no,
                event_type,
            )
            return False
        if not event_type:
            logger.warning(
                "BatchedJournalWriter.record without event_type: "
                "message_id=%s seq=%s",
                self._message_id,
                sequence_no,
            )
            return False
        if payload is None:
            materialised: dict[str, Any] = {}
        elif isinstance(payload, dict):
            materialised = _strip_null_bytes(payload)
        else:
            # Same contract as ``record_event`` — non-dict payloads
            # are rejected so the live and replay paths can't diverge
            # on envelope reconstruction.
            logger.warning(
                "BatchedJournalWriter.record with non-dict payload: "
                "message_id=%s seq=%s type=%s payload_type=%s — dropping",
                self._message_id,
                sequence_no,
                event_type,
                type(payload).__name__,
            )
            return False

        self._buffer.append((sequence_no, event_type, materialised))

        if self._should_flush():
            self.flush()
        return True

    def _should_flush(self) -> bool:
        if len(self._buffer) >= self._batch_size:
            return True
        elapsed_ms = (time.monotonic() * 1000.0) - self._last_flush_mono_ms
        return elapsed_ms >= self._batch_interval_ms and len(self._buffer) > 0

    def flush(self) -> None:
        """Commit buffered events to PG. Best-effort.

        Tries one bulk INSERT first; on ``IntegrityError`` (composite
        PK collision — typically a stale continuation seed) falls back
        to per-row ``record_event`` so one bad seq doesn't drop the
        rest of the batch. Always clears the buffer to bound memory,
        even on failure — a journaled event missing from a snapshot
        is degraded UX, but a runaway buffer is corruption.
        """
        if not self._buffer:
            self._last_flush_mono_ms = time.monotonic() * 1000.0
            return

        # Snapshot and clear before the I/O so a concurrent record()
        # call would land in a fresh buffer rather than racing the
        # flush. ``complete_stream`` is single-threaded per stream, so
        # this is belt-and-suspenders for any future change.
        pending = self._buffer
        self._buffer = []
        self._last_flush_mono_ms = time.monotonic() * 1000.0

        try:
            with db_session() as conn:
                MessageEventsRepository(conn).bulk_record(
                    self._message_id, pending
                )
        except IntegrityError:
            logger.info(
                "BatchedJournalWriter: bulk INSERT collided for "
                "message_id=%s n=%d; falling back to per-row writes",
                self._message_id,
                len(pending),
            )
            self._flush_per_row(pending)
            return
        except Exception:
            logger.exception(
                "BatchedJournalWriter: bulk INSERT failed for "
                "message_id=%s n=%d; events dropped from journal",
                self._message_id,
                len(pending),
            )
            return

        # Bulk INSERT committed — publish each frame in order. Best-effort:
        # one failed publish must not poison the rest of the batch.
        for seq, event_type, payload in pending:
            self._publish(seq, event_type, payload)

    def _flush_per_row(
        self, pending: list[tuple[int, str, dict[str, Any]]]
    ) -> None:
        """Per-row fallback after a bulk collision. Publishes after each commit."""
        for seq, event_type, payload in pending:
            committed_seq: Optional[int] = None
            try:
                with db_session() as conn:
                    MessageEventsRepository(conn).record(
                        self._message_id, seq, event_type, payload
                    )
                committed_seq = seq
            except IntegrityError:
                try:
                    with db_readonly() as conn:
                        latest = MessageEventsRepository(
                            conn
                        ).latest_sequence_no(self._message_id)
                    retry_seq = (latest if latest is not None else -1) + 1
                    with db_session() as conn:
                        MessageEventsRepository(conn).record(
                            self._message_id, retry_seq, event_type, payload
                        )
                    committed_seq = retry_seq
                except IntegrityError:
                    logger.warning(
                        "BatchedJournalWriter: IntegrityError persists "
                        "after seq+1 retry; dropping. message_id=%s "
                        "original_seq=%s type=%s",
                        self._message_id,
                        seq,
                        event_type,
                    )
                except Exception:
                    logger.exception(
                        "BatchedJournalWriter: per-row retry failed "
                        "(message_id=%s seq=%s type=%s)",
                        self._message_id,
                        seq,
                        event_type,
                    )
            except Exception:
                logger.exception(
                    "BatchedJournalWriter: per-row INSERT failed "
                    "(message_id=%s seq=%s type=%s)",
                    self._message_id,
                    seq,
                    event_type,
                )

            if committed_seq is not None:
                self._publish(committed_seq, event_type, payload)

    def _publish(
        self, sequence_no: int, event_type: str, payload: dict[str, Any]
    ) -> None:
        """Publish one frame to the per-message pubsub channel. Best-effort."""
        try:
            wire = encode_pubsub_message(
                self._message_id, sequence_no, event_type, payload
            )
            Topic(message_topic_name(self._message_id)).publish(wire)
        except Exception:
            logger.exception(
                "channel:%s publish failed: seq=%s type=%s",
                self._message_id,
                sequence_no,
                event_type,
            )

    def close(self) -> None:
        """Final flush. Idempotent — safe to call from multiple
        finally clauses.
        """
        if self._closed:
            return
        self.flush()
        self._closed = True
