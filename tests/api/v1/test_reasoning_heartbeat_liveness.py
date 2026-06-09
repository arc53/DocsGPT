"""Streaming-heartbeat liveness for reasoning models that "think" before
answering (``complete_stream`` in ``application/api/answer/routes/base.py``).

Background
----------
The reconciler (``ReconciliationRepository.find_and_lock_stuck_messages``)
fails a ``pending``/``streaming`` row whose effective freshness —
``GREATEST(timestamp, message_metadata.last_heartbeat_at)`` — is older than
5 minutes. ``complete_stream`` keeps that freshness up via a streaming
heartbeat.

The bug these tests pin: the heartbeat pump used to early-return until the row
had been flipped to ``streaming``, and the row is only flipped on the first
``answer``/``sources`` chunk. A reasoning model (e.g. ``reasoning_effort:
high``) that streams only ``thought`` chunks for minutes before its first
answer token therefore left the row ``pending`` with a *frozen* heartbeat, so
the reconciler would falsely fail a live request.

The fix makes the heartbeat a true "agent is producing output / is alive"
signal: it pumps whenever a ``reserved_message_id`` exists (regardless of the
``streaming`` status flip), and is seeded once at generation start. The
``pending → streaming`` status transition itself is unchanged (still driven by
the first ``answer``/``sources`` chunk).

Residual (documented, intentionally not covered here): a model that emits *no*
chunks at all — not even ``thought`` — for >5 min would still go stale, since
the pump only ticks when a chunk flows. Covering a fully-silent stream would
need a background-thread heartbeat or a higher threshold; both are out of
scope for this surgical fix.

These tests drive the real ``complete_stream`` against an ephemeral Postgres
database (``pg_engine``) and reuse the wiring/fakes style of
``tests/api/v1/test_v1_tool_pause_finalization.py``.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy import text

from application.api.answer.routes.base import BaseAnswerResource
from application.api.answer.services.conversation_service import ConversationService
from application.storage.db.repositories.conversations import ConversationsRepository
from application.storage.db.repositories.reconciliation import (
    ReconciliationRepository,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeLLM:
    """Minimal LLM stand-in so ``complete_stream`` can stamp ``_request_id``."""

    def __init__(self) -> None:
        self._request_id: Optional[str] = None
        self.model_id = "gpt-5"


class _ThoughtOnlyAgent:
    """Agent that streams only ``thought`` chunks and never answers.

    Models a reasoning model mid-"thinking" phase: the stream is alive and
    producing output, but no ``answer``/``sources`` chunk has arrived yet, so
    the row is still ``pending`` (``streaming`` not marked).
    """

    def __init__(self, n_thoughts: int = 4) -> None:
        self.llm = _FakeLLM()
        self._n_thoughts = n_thoughts

    def gen(self, query: str = ""):
        for i in range(self._n_thoughts):
            yield {"thought": f"reasoning step {i}..."}


class _ThoughtThenAnswerAgent:
    """Agent that thinks (``thought`` chunks) then emits a final ``answer``.

    Used for the regression case: the row must still flip to ``streaming`` on
    the first ``answer`` chunk and finalize ``complete``.
    """

    ANSWER_TEXT = "The answer is 42."

    def __init__(self, n_thoughts: int = 3) -> None:
        self.llm = _FakeLLM()
        self._n_thoughts = n_thoughts

    def gen(self, query: str = ""):
        for i in range(self._n_thoughts):
            yield {"thought": f"reasoning step {i}..."}
        yield {"answer": self.ANSWER_TEXT}


class _NoopJournalWriter:
    """No-op journal writer so the test exercises DB row state, not the
    message-events journal / Redis broadcast (orthogonal to heartbeats)."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def record(self, *args, **kwargs) -> None:
        pass

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------


def _seed_user(conn, user_id: str) -> None:
    conn.execute(
        text(
            "INSERT INTO users (user_id) VALUES (:u) "
            "ON CONFLICT (user_id) DO NOTHING"
        ),
        {"u": user_id},
    )


def _row(conn, message_id: str) -> Dict[str, Any]:
    """Fetch ``(status, message_metadata)`` for a reserved row."""
    r = conn.execute(
        text(
            "SELECT status, message_metadata FROM conversation_messages "
            "WHERE id = CAST(:m AS uuid)"
        ),
        {"m": message_id},
    ).fetchone()
    return {"status": r[0], "metadata": r[1]} if r is not None else {}


@contextmanager
def _wire_db(engine, monkeypatch):
    """Point conversation_service / continuation_service / base at ``engine``.

    Each helper opens its own short-lived connection (matching production),
    so we hand out fresh connections from the same ephemeral engine and swap
    the journal writer for a no-op. Mirrors the helper in
    ``test_v1_tool_pause_finalization.py``.
    """
    from application.api.answer.services import conversation_service as conv_mod
    from application.api.answer.services import continuation_service as cont_mod
    from application.api.answer.routes import base as base_mod

    @contextmanager
    def _session():
        conn = engine.connect()
        txn = conn.begin()
        try:
            yield conn
            txn.commit()
        except Exception:
            txn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _readonly():
        conn = engine.connect()
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(conv_mod, "db_session", _session)
    monkeypatch.setattr(conv_mod, "db_readonly", _readonly)
    monkeypatch.setattr(cont_mod, "db_session", _session)
    monkeypatch.setattr(cont_mod, "db_readonly", _readonly)
    monkeypatch.setattr(base_mod, "db_session", _session)
    monkeypatch.setattr(base_mod, "db_readonly", _readonly)
    monkeypatch.setattr(base_mod, "BatchedJournalWriter", _NoopJournalWriter)
    monkeypatch.setattr(base_mod, "record_event", lambda *a, **kw: None)
    monkeypatch.setattr(base_mod, "publish_user_event", lambda *a, **kw: None)
    yield


class _FakeMonotonic:
    """Deterministic ``time.monotonic`` that jumps forward on every call.

    ``complete_stream`` reads ``time.monotonic()`` once per loop iteration
    (via ``_heartbeat_streaming``) plus at seed/mark points. Advancing by more
    than ``STREAM_HEARTBEAT_INTERVAL`` (60s) on each read guarantees the
    interval gate fires every iteration, so a thought-only stream attempts a
    heartbeat on every ``thought`` chunk.
    """

    def __init__(self, step: float = 120.0) -> None:
        self._t = 0.0
        self._step = step

    def __call__(self) -> float:
        self._t += self._step
        return self._t


def _make_base() -> BaseAnswerResource:
    base = BaseAnswerResource.__new__(BaseAnswerResource)
    base.default_model_id = "gpt-5"
    base.conversation_service = ConversationService()
    return base


def _drain(gen) -> List[str]:
    return list(gen)


# ---------------------------------------------------------------------------
# 1. Pump-during-reasoning: a thought-only stream heartbeats while pending
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestHeartbeatPumpsDuringReasoning:
    """A reasoning model that only streams ``thought`` chunks (no answer yet)
    must still keep its ``last_heartbeat_at`` fresh while the row is ``pending``
    — otherwise the reconciler falsely fails a live request.

    Pre-fix the pump early-returns while ``streaming`` is unmarked, so a
    thought-only phase produces NO heartbeat and these assertions fail.
    """

    def test_thought_only_stream_heartbeats_while_pending(
        self, pg_engine, monkeypatch
    ):
        from application.api.answer.routes import base as base_mod

        user_id = f"user-{uuid.uuid4().hex[:8]}"
        with pg_engine.begin() as conn:
            _seed_user(conn, user_id)

        # Count heartbeat invocations directly on the service so the test is
        # explicit that the pump fired during the thought-only phase.
        heartbeat_calls: List[str] = []
        real_heartbeat = ConversationService.heartbeat_message

        def _counting_heartbeat(self, message_id: str) -> bool:
            heartbeat_calls.append(message_id)
            return real_heartbeat(self, message_id)

        with _wire_db(pg_engine, monkeypatch):
            monkeypatch.setattr(
                ConversationService, "heartbeat_message", _counting_heartbeat
            )
            # Make every loop iteration cross the heartbeat interval.
            monkeypatch.setattr(base_mod.time, "monotonic", _FakeMonotonic())

            base = _make_base()
            agent = _ThoughtOnlyAgent(n_thoughts=4)
            frames = _drain(
                base.complete_stream(
                    question="hard reasoning question",
                    agent=agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": user_id},
                    should_persist=True,
                    model_id="gpt-5",
                )
            )

        # Sanity: the stream only ever emitted thoughts (plus framing/end),
        # never an answer — so ``streaming`` was never marked during the loop.
        joined = "\n".join(frames)
        assert '"type": "thought"' in joined
        assert '"type": "answer"' not in joined

        # Resolve the reserved row.
        with pg_engine.connect() as conn:
            msg_id = conn.execute(
                text(
                    "SELECT cm.id FROM conversation_messages cm "
                    "JOIN conversations c ON c.id = cm.conversation_id "
                    "WHERE c.user_id = :u ORDER BY cm.timestamp DESC LIMIT 1"
                ),
                {"u": user_id},
            ).scalar()
            assert msg_id is not None
            row = _row(conn, str(msg_id))

        # Core assertion: the heartbeat fired for this row during a thought-only
        # phase. Pre-fix the pump is gated behind ``streaming_marked`` and never
        # runs, so ``heartbeat_calls`` is empty.
        assert str(msg_id) in heartbeat_calls, (
            "heartbeat_message was never called for the pending reasoning row; "
            "the heartbeat pump is still gated behind the streaming flip"
        )
        # And it is observable on the row: a non-null last_heartbeat_at.
        assert row["metadata"] is not None
        assert row["metadata"].get("last_heartbeat_at") is not None

    def test_heartbeat_advances_last_heartbeat_at_while_row_stays_pending(
        self, pg_engine, monkeypatch
    ):
        """End-of-stream the answer arrives and the row finalizes, so to observe
        the *pending* heartbeat we snapshot the row mid-stream: after the first
        ``thought`` chunk the row must be ``pending`` with a fresh
        ``last_heartbeat_at`` already stamped (seed-at-start), and a subsequent
        ``thought`` must bump it further — all before any ``answer``.
        """
        from application.api.answer.routes import base as base_mod

        user_id = f"user-{uuid.uuid4().hex[:8]}"
        with pg_engine.begin() as conn:
            _seed_user(conn, user_id)

        observed: List[Dict[str, Any]] = []

        class _ObservingAgent:
            """Yields thoughts; after each, the harness inspects the DB row."""

            def __init__(self) -> None:
                self.llm = _FakeLLM()

            def gen(self, query: str = ""):
                # message_id is surfaced before this generator runs, so by the
                # time we yield, the reserved row already exists. We can't read
                # it from inside gen() (no msg id handle), so just emit; the
                # snapshots happen in the consuming loop below via a wrapper.
                for i in range(3):
                    yield {"thought": f"step {i}"}

        with _wire_db(pg_engine, monkeypatch):
            monkeypatch.setattr(base_mod.time, "monotonic", _FakeMonotonic())
            base = _make_base()
            agent = _ObservingAgent()

            gen = base.complete_stream(
                question="reason about it",
                agent=agent,
                conversation_id=None,
                user_api_key=None,
                decoded_token={"sub": user_id},
                should_persist=True,
                model_id="gpt-5",
            )

            # Pull the first frame (the ``message_id`` event) to learn the row.
            first = next(gen)
            assert "message_id" in first
            msg_id = None
            with pg_engine.connect() as conn:
                msg_id = conn.execute(
                    text(
                        "SELECT cm.id FROM conversation_messages cm "
                        "JOIN conversations c ON c.id = cm.conversation_id "
                        "WHERE c.user_id = :u ORDER BY cm.timestamp DESC LIMIT 1"
                    ),
                    {"u": user_id},
                ).scalar()
            assert msg_id is not None

            # Drain the rest, snapshotting the row's heartbeat after each frame.
            for _ in gen:
                with pg_engine.connect() as conn:
                    observed.append(_row(conn, str(msg_id)))

        # While the stream was thought-only the row stayed ``pending`` and the
        # heartbeat advanced (was non-null on each snapshot).
        pending_snaps = [s for s in observed if s.get("status") == "pending"]
        assert pending_snaps, "expected at least one pending snapshot mid-stream"
        for snap in pending_snaps:
            assert snap["metadata"] is not None
            assert snap["metadata"].get("last_heartbeat_at") is not None


# ---------------------------------------------------------------------------
# 2. Seed-at-start: the reserved row has a heartbeat from generation start
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestHeartbeatSeededAtGenerationStart:
    """Right after ``complete_stream`` reserves the row and begins consuming the
    generator (before any ``answer``), the row must already carry a non-null
    ``last_heartbeat_at`` — so even a model that takes a while to emit its first
    chunk is covered from t=0, not only from the first interval tick.
    """

    def test_reserved_row_has_heartbeat_before_first_answer(
        self, pg_engine, monkeypatch
    ):
        # This case keeps real ``time.monotonic`` so it asserts the *seed*
        # (which runs before the loop, with no time advance), not an
        # interval-driven pump — so no ``base.time`` monkeypatch is needed.
        user_id = f"user-{uuid.uuid4().hex[:8]}"
        with pg_engine.begin() as conn:
            _seed_user(conn, user_id)

        captured: Dict[str, Any] = {}

        class _SlowFirstChunkAgent:
            """Yields a single thought then stops — emulates a model that has
            produced no answer yet by the time we inspect the row."""

            def __init__(self) -> None:
                self.llm = _FakeLLM()

            def gen(self, query: str = ""):
                # Inspect the reserved row at the very first generator step,
                # before any answer/sources chunk has been processed.
                with pg_engine.connect() as conn:
                    mid = conn.execute(
                        text(
                            "SELECT cm.id FROM conversation_messages cm "
                            "JOIN conversations c ON c.id = cm.conversation_id "
                            "WHERE c.user_id = :u "
                            "ORDER BY cm.timestamp DESC LIMIT 1"
                        ),
                        {"u": user_id},
                    ).scalar()
                    captured["row"] = _row(conn, str(mid)) if mid else {}
                yield {"thought": "starting to reason"}

        with _wire_db(pg_engine, monkeypatch):
            # Keep real monotonic time so this asserts the *seed*, not an
            # interval-driven pump (no time advance happens before gen runs).
            base = _make_base()
            agent = _SlowFirstChunkAgent()
            _drain(
                base.complete_stream(
                    question="seed check",
                    agent=agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": user_id},
                    should_persist=True,
                    model_id="gpt-5",
                )
            )

        row = captured.get("row") or {}
        # The seed runs before the loop, so the row is still ``pending`` and
        # already has a heartbeat stamped.
        assert row.get("status") == "pending"
        assert row.get("metadata") is not None
        assert row["metadata"].get("last_heartbeat_at") is not None


# ---------------------------------------------------------------------------
# 3. End-to-end reconciler guarantee: a fresh-heartbeat pending row is safe
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReconcilerProtectsFreshlyHeartbeatedPendingRow:
    """The whole point of the fix: a ``pending`` row older than 5 min by
    ``timestamp`` but with a fresh ``last_heartbeat_at`` (the reasoning pump)
    must NOT be swept by ``find_and_lock_stuck_messages``; a stale-heartbeat
    ``pending`` row still IS swept.

    This mirrors the ``streaming`` cases in
    ``tests/storage/db/repositories/test_reconciliation.py`` but for the
    ``pending`` (still-reasoning) status the fix is about.
    """

    def _seed_pending_with_heartbeat(
        self, conn, *, hb_minutes_ago: float, ts_minutes_ago: int = 20,
    ) -> str:
        conv = ConversationsRepository(conn).create("u-recon", "reasoning recon")
        row = conn.execute(
            text(
                """
                INSERT INTO conversation_messages (
                    conversation_id, position, prompt, response, status,
                    user_id, timestamp, message_metadata
                )
                VALUES (
                    CAST(:cid AS uuid), 0, 'p', '', 'pending', 'u-recon',
                    clock_timestamp() - make_interval(mins => :ts),
                    jsonb_build_object(
                        'last_heartbeat_at',
                        to_jsonb(
                            clock_timestamp()
                            - make_interval(secs => :hb_secs)
                        )
                    )
                )
                RETURNING id
                """
            ),
            {
                "cid": conv["id"],
                "ts": ts_minutes_ago,
                "hb_secs": int(hb_minutes_ago * 60),
            },
        ).fetchone()
        return str(row[0])

    def test_fresh_heartbeat_pending_row_is_not_swept(self, pg_conn):
        # timestamp 20 min old (well past the 5-min age gate) but the reasoning
        # pump heartbeat is only 30s old → the row is live, must be skipped.
        msg_id = self._seed_pending_with_heartbeat(
            pg_conn, hb_minutes_ago=0.5, ts_minutes_ago=20
        )
        rows = ReconciliationRepository(pg_conn).find_and_lock_stuck_messages()
        assert all(str(r["id"]) != msg_id for r in rows), (
            "a still-reasoning pending row with a fresh heartbeat was "
            "incorrectly selected for reconciliation"
        )

    def test_stale_heartbeat_pending_row_is_swept(self, pg_conn):
        # Both timestamp and heartbeat are older than 5 min → genuinely stuck.
        msg_id = self._seed_pending_with_heartbeat(
            pg_conn, hb_minutes_ago=10, ts_minutes_ago=20
        )
        rows = ReconciliationRepository(pg_conn).find_and_lock_stuck_messages()
        assert any(str(r["id"]) == msg_id for r in rows), (
            "a pending row stale by both timestamp and heartbeat should be "
            "selected for reconciliation"
        )


# ---------------------------------------------------------------------------
# 4. Regression: a normal answer turn still marks streaming + heartbeats
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestNormalAnswerTurnUnchanged:
    """A normal turn that streams an ``answer`` must still flip the row to
    ``streaming`` on the first answer chunk (status semantics unchanged) and
    finalize ``complete``. The heartbeat liveness change must not regress this.
    """

    def test_answer_turn_marks_streaming_and_finalizes_complete(
        self, pg_engine, monkeypatch
    ):
        from application.api.answer.routes import base as base_mod

        user_id = f"user-{uuid.uuid4().hex[:8]}"
        with pg_engine.begin() as conn:
            _seed_user(conn, user_id)

        # Observe the status transition: snapshot after the first answer frame.
        statuses_seen: List[str] = []
        real_update = ConversationService.update_message_status

        def _recording_update(self, message_id: str, status: str) -> bool:
            statuses_seen.append(status)
            return real_update(self, message_id, status)

        with _wire_db(pg_engine, monkeypatch):
            monkeypatch.setattr(
                ConversationService, "update_message_status", _recording_update
            )
            monkeypatch.setattr(base_mod.time, "monotonic", _FakeMonotonic())
            base = _make_base()
            agent = _ThoughtThenAnswerAgent(n_thoughts=2)
            frames = _drain(
                base.complete_stream(
                    question="normal question",
                    agent=agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": user_id},
                    should_persist=True,
                    model_id="gpt-5",
                )
            )

        joined = "\n".join(frames)
        assert '"type": "answer"' in joined
        assert '"type": "end"' in joined

        # The first answer chunk marked the row ``streaming`` exactly once.
        assert statuses_seen == ["streaming"]

        with pg_engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT status, response, message_metadata "
                    "FROM conversation_messages cm "
                    "JOIN conversations c ON c.id = cm.conversation_id "
                    "WHERE c.user_id = :u ORDER BY cm.timestamp DESC LIMIT 1"
                ),
                {"u": user_id},
            ).fetchone()

        # Final state: terminal ``complete`` with the answer, and a heartbeat
        # was stamped along the way (liveness intact).
        assert row[0] == "complete"
        assert row[1] == _ThoughtThenAnswerAgent.ANSWER_TEXT
        assert row[2] is not None
        assert row[2].get("last_heartbeat_at") is not None
