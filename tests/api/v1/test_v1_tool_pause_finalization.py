"""Tool-pause finalization + stateless resume for the OpenAI-compatible ``/v1``
path.

The OpenAI protocol has no slot for DocsGPT's ``reserved_message_id``: clients
resume a tool call by re-POSTing the whole message history with
``{role:"tool"}`` results (optionally threading the ``conversation_id`` they got
back), not via a native resume. The ``/v1`` tool round-trip is therefore fully
stateless on both ends:

- **Pause side.** When an agent pauses for a client-executed tool,
  ``complete_stream`` (run with ``finalize_tool_pause_as_complete=True``)
  finalizes the reserved ``conversation_messages`` row as ``complete``
  (recording the tool_calls) instead of writing a ``pending_tool_state`` record
  and leaving the row non-terminal. The reconciler never sees an orphaned row.
- **Resume side.** The ``/v1`` route rebuilds the agent + pending calls from the
  re-POSTed history via ``StreamProcessor.build_continuation_from_messages``
  (which has *no* ``pending_tool_state`` dependency) — **regardless of whether a
  ``conversation_id`` is present**. It never calls ``resume_from_tool_actions``
  (whose ``load_state`` would 400, since the pause wrote no state). When a
  ``conversation_id`` is carried, the final answer persists as a NEW terminal
  turn appended to that conversation.

Net result per tool turn: a ``complete`` tool-call turn + a ``complete`` answer
turn — both terminal, no orphan, no 400, OpenAI-faithful.

These tests drive the real ``/v1/chat/completions`` route and real
``complete_stream`` against an ephemeral Postgres database (``pg_engine``):

- a real two-POST round-trip (pause then answer, threading the
  ``conversation_id``) returns 200 on *both* POSTs and persists the answer into
  the SAME conversation, with nothing left ``pending``/``streaming`` — the
  regression catcher (the pre-fix route 400s on POST #2 via
  ``resume_from_tool_actions``);
- a v1 tool round WITH a conversation context finalizes the reserved row as
  ``complete`` and leaves no ``pending``/``streaming`` row behind;
- a stateless v1 tool round (no conversation_id, ``should_persist=False``)
  leaves nothing non-terminal and writes no orphan conversation;
- the native ``/stream`` pause (flag defaulted False) is byte-for-byte
  unchanged: it still writes ``pending_tool_state`` and leaves the row
  non-terminal awaiting a native resume.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from application.api.answer.routes.base import BaseAnswerResource
from application.api.answer.services.conversation_service import ConversationService
from application.api.v1.routes import v1_bp


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeLLM:
    """Minimal LLM stand-in so ``complete_stream`` can stamp ``_request_id``."""

    def __init__(self) -> None:
        self._request_id: Optional[str] = None
        self.model_id = "gpt-4"


class _FakeToolExecutor:
    """Tool executor stub the native pause path reads ``client_tools`` off of."""

    def __init__(self) -> None:
        self.client_tools: Optional[List[Dict[str, Any]]] = None
        self.message_id: Optional[str] = None
        self.conversation_id: Optional[str] = None


class _PausingAgent:
    """Agent whose ``gen``/``gen_continuation`` pauses for a client tool.

    Mirrors what the real handler does on a client-side / approval pause:
    yield a ``tool_calls_pending`` event and stash ``_pending_continuation``
    on the agent. ``complete_stream`` keys its pause handling off both.
    """

    def __init__(
        self,
        pending_tool_calls: List[Dict[str, Any]],
        *,
        with_tool_executor: bool = False,
    ) -> None:
        self.llm = _FakeLLM()
        self._pending_tool_calls = pending_tool_calls
        self._pending_continuation: Optional[Dict[str, Any]] = None
        # The native pause path reads ``agent.tool_executor.client_tools`` and
        # ``agent.tools`` to persist continuation state; the v1 finalize path
        # touches neither. Only attach a tool_executor when the test needs the
        # native branch (``getattr(agent, "tool_executor", None)`` stays None
        # otherwise).
        if with_tool_executor:
            self.tool_executor = _FakeToolExecutor()

    def _emit_pause(self):
        self._pending_continuation = {
            "messages": [{"role": "system", "content": "sys"}],
            "pending_tool_calls": self._pending_tool_calls,
            "tools_dict": {"0": {"name": "get_weather", "client_side": True}},
            "reasoning_content": "",
        }
        yield {
            "type": "tool_calls_pending",
            "data": {"pending_tool_calls": self._pending_tool_calls},
        }

    def gen(self, query: str = ""):
        yield from self._emit_pause()

    def gen_continuation(self, **kwargs):
        yield from self._emit_pause()


class _NoopJournalWriter:
    """No-op journal writer so the test exercises DB row state, not the
    message-events journal / Redis broadcast (orthogonal to finalization)."""

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


PENDING_TOOL_CALLS = [
    {
        "call_id": "call_abc",
        "name": "get_weather_0",
        "tool_name": "get_weather",
        "action_name": "get_weather",
        "arguments": {"city": "SF"},
        "pause_type": "requires_client_execution",
    }
]


def _seed_user(conn, user_id: str) -> None:
    from sqlalchemy import text

    conn.execute(
        text(
            "INSERT INTO users (user_id) VALUES (:u) "
            "ON CONFLICT (user_id) DO NOTHING"
        ),
        {"u": user_id},
    )


def _row_statuses(conn, conversation_id: str) -> List[str]:
    from sqlalchemy import text

    rows = conn.execute(
        text(
            "SELECT status FROM conversation_messages "
            "WHERE conversation_id = CAST(:c AS uuid) "
            "ORDER BY position ASC"
        ),
        {"c": conversation_id},
    ).fetchall()
    return [r[0] for r in rows]


def _row_tool_calls(conn, message_id: str):
    from sqlalchemy import text

    row = conn.execute(
        text(
            "SELECT tool_calls FROM conversation_messages "
            "WHERE id = CAST(:m AS uuid)"
        ),
        {"m": message_id},
    ).fetchone()
    return row[0] if row is not None else None


def _pending_tool_state_count(conn, conversation_id: str) -> int:
    from sqlalchemy import text

    return conn.execute(
        text(
            "SELECT count(*) FROM pending_tool_state "
            "WHERE conversation_id = CAST(:c AS uuid)"
        ),
        {"c": conversation_id},
    ).scalar()


@contextmanager
def _wire_db(engine, monkeypatch):
    """Point conversation_service / continuation_service / base at ``engine``.

    Each helper opens its own short-lived connection (matching production),
    so we hand out fresh connections from the same ephemeral engine and
    swap the journal writer for a no-op.
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
    # The native approval pause publishes ``tool.approval.required`` out of
    # band (Redis); no-op it so the test stays DB-only.
    monkeypatch.setattr(base_mod, "publish_user_event", lambda *a, **kw: None)
    yield


def _drain(gen) -> List[str]:
    """Consume an SSE generator into a list of frames."""
    return list(gen)


# ---------------------------------------------------------------------------
# Guarantee 1 — v1 tool pause never leaves a non-terminal row
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestV1ToolPauseFinalizesRow:
    """A first-turn ``/v1`` tool emission reserves a WAL row; the pause must
    finalize it as ``complete`` (with the tool_calls) rather than strand it.
    """

    def test_v1_tool_pause_with_conversation_finalizes_row_complete(
        self, pg_engine, monkeypatch
    ):
        user_id = f"user-{uuid.uuid4().hex[:8]}"
        with pg_engine.begin() as conn:
            _seed_user(conn, user_id)

        with _wire_db(pg_engine, monkeypatch):
            base = BaseAnswerResource.__new__(BaseAnswerResource)
            base.default_model_id = "gpt-4"
            base.conversation_service = ConversationService()

            agent = _PausingAgent(PENDING_TOOL_CALLS)
            frames = _drain(
                base.complete_stream(
                    question="weather in SF?",
                    agent=agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": user_id},
                    should_persist=True,
                    model_id="gpt-4",
                    finalize_tool_pause_as_complete=True,
                )
            )

        # The client still receives the pause signal + a conversation id.
        joined = "\n".join(frames)
        assert "tool_calls_pending" in joined
        assert '"type": "id"' in joined
        assert '"type": "end"' in joined

        # Resolve the conversation that was created for the reserved row.
        with pg_engine.connect() as conn:
            from sqlalchemy import text

            conv_id = conn.execute(
                text(
                    "SELECT id FROM conversations WHERE user_id = :u "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"u": user_id},
            ).scalar()
            assert conv_id is not None
            statuses = _row_statuses(conn, str(conv_id))
            msg_id = conn.execute(
                text(
                    "SELECT id FROM conversation_messages "
                    "WHERE conversation_id = CAST(:c AS uuid) LIMIT 1"
                ),
                {"c": str(conv_id)},
            ).scalar()
            tool_calls = _row_tool_calls(conn, str(msg_id))
            pts = _pending_tool_state_count(conn, str(conv_id))

        # Guarantee 1: exactly one row, terminal ``complete`` — never
        # ``pending``/``streaming``.
        assert statuses == ["complete"]
        assert "pending" not in statuses
        assert "streaming" not in statuses
        # The emitted/pending tool_calls are recorded on the row.
        assert tool_calls
        assert tool_calls[0]["call_id"] == "call_abc"
        # No native continuation record is written on the v1 path.
        assert pts == 0

    def test_v1_stateless_tool_pause_leaves_no_orphan(
        self, pg_engine, monkeypatch
    ):
        """Pure OpenAI/opencode style: a stateless continuation carries no
        conversation_id and ``should_persist=False`` (translator opt-out), so
        no WAL row is reserved. The pause must end cleanly with no
        non-terminal row and no empty-prompt orphan conversation.
        """
        user_id = f"user-{uuid.uuid4().hex[:8]}"
        with pg_engine.begin() as conn:
            _seed_user(conn, user_id)
            conv_count_before = conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT count(*) FROM conversations WHERE user_id = :u"
                ),
                {"u": user_id},
            ).scalar()

        with _wire_db(pg_engine, monkeypatch):
            base = BaseAnswerResource.__new__(BaseAnswerResource)
            base.default_model_id = "gpt-4"
            base.conversation_service = ConversationService()

            agent = _PausingAgent(PENDING_TOOL_CALLS)
            frames = _drain(
                base.complete_stream(
                    question="",
                    agent=agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": user_id},
                    should_persist=False,
                    model_id="gpt-4",
                    _continuation={
                        "messages": [{"role": "system", "content": "sys"}],
                        "tools_dict": {"0": {"name": "get_weather"}},
                        "pending_tool_calls": PENDING_TOOL_CALLS,
                        "tool_actions": [{"call_id": "call_abc", "result": "72F"}],
                        "reserved_message_id": None,
                        "request_id": None,
                        "reasoning_content": "",
                    },
                    finalize_tool_pause_as_complete=True,
                )
            )

        joined = "\n".join(frames)
        assert "tool_calls_pending" in joined
        assert '"type": "end"' in joined

        with pg_engine.connect() as conn:
            from sqlalchemy import text

            conv_count_after = conn.execute(
                text("SELECT count(*) FROM conversations WHERE user_id = :u"),
                {"u": user_id},
            ).scalar()
            non_terminal = conn.execute(
                text(
                    "SELECT count(*) FROM conversation_messages cm "
                    "JOIN conversations c ON c.id = cm.conversation_id "
                    "WHERE c.user_id = :u "
                    "AND cm.status IN ('pending', 'streaming')"
                ),
                {"u": user_id},
            ).scalar()

        # No orphan conversation created, nothing left non-terminal.
        assert conv_count_after == conv_count_before
        assert non_terminal == 0

    def test_v1_multi_round_continuation_pause_leaves_nothing_non_terminal(
        self, pg_engine, monkeypatch
    ):
        """Multi-round loop, coherent Option B: a v1 continuation rebuilds
        STATELESSLY (the route passes ``reserved_message_id=None`` because the
        first turn's row is already ``complete`` and cannot be reused). When
        the resume pauses AGAIN for another client tool, no new WAL row is
        reserved (``_continuation`` is truthy → ``wal_eligible`` is False), so
        there is nothing to strand: the round ends cleanly, the already-
        ``complete`` first-turn row is untouched, and nothing is left
        ``pending``/``streaming`` for the reconciler.
        """
        user_id = f"user-{uuid.uuid4().hex[:8]}"
        # Seed a conversation whose first (tool-emitting) turn has already
        # been finalized ``complete`` — the coherent-Option-B state after the
        # first POST: no lingering ``pending`` row mid-loop.
        with pg_engine.begin() as conn:
            _seed_user(conn, user_id)
        with _wire_db(pg_engine, monkeypatch):
            svc = ConversationService()
            reservation = svc.save_user_question(
                conversation_id=None,
                question="multi-step task",
                decoded_token={"sub": user_id},
                model_id="gpt-4",
            )
            conv_id = reservation["conversation_id"]
            first_turn_id = reservation["message_id"]
            svc.finalize_message(
                first_turn_id,
                "",
                tool_calls=[{"call_id": "call_abc", "name": "step1"}],
                model_id="gpt-4",
                status="complete",
            )

        with pg_engine.connect() as conn:
            assert _row_statuses(conn, conv_id) == ["complete"]

        second_round_calls = [
            {
                "call_id": "call_def",
                "name": "lookup_0",
                "tool_name": "lookup",
                "action_name": "lookup",
                "arguments": {"q": "next"},
                "pause_type": "requires_client_execution",
            }
        ]

        with _wire_db(pg_engine, monkeypatch):
            base = BaseAnswerResource.__new__(BaseAnswerResource)
            base.default_model_id = "gpt-4"
            base.conversation_service = ConversationService()

            agent = _PausingAgent(second_round_calls)
            frames = _drain(
                base.complete_stream(
                    question="",
                    agent=agent,
                    conversation_id=conv_id,
                    user_api_key=None,
                    decoded_token={"sub": user_id},
                    should_persist=True,
                    model_id="gpt-4",
                    _continuation={
                        "messages": [{"role": "system", "content": "sys"}],
                        "tools_dict": {"0": {"name": "lookup"}},
                        "pending_tool_calls": second_round_calls,
                        "tool_actions": [
                            {"call_id": "call_abc", "result": "step1 done"}
                        ],
                        # Coherent Option B: the v1 route rebuilds statelessly,
                        # so it threads no reserved_message_id/request_id.
                        "reserved_message_id": None,
                        "request_id": None,
                        "reasoning_content": "",
                    },
                    finalize_tool_pause_as_complete=True,
                )
            )

        joined = "\n".join(frames)
        assert "tool_calls_pending" in joined
        assert '"type": "end"' in joined

        with pg_engine.connect() as conn:
            statuses = _row_statuses(conn, conv_id)
            first_turn_calls = _row_tool_calls(conn, first_turn_id)
            pts = _pending_tool_state_count(conn, conv_id)

        # The first-turn row stays exactly as it was (terminal ``complete``
        # with its own tool_calls); no sibling row was reserved or stranded,
        # nothing is ``pending``/``streaming``, and no native state was written.
        assert statuses == ["complete"]
        assert "pending" not in statuses
        assert "streaming" not in statuses
        assert first_turn_calls
        assert first_turn_calls[0]["call_id"] == "call_abc"
        assert pts == 0


# ---------------------------------------------------------------------------
# Guarantee 3 — native pause path is unchanged (flag defaults False)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestNativePauseUnchanged:
    """The native ``/stream`` + ``/api/answer`` flow must keep writing
    ``pending_tool_state`` and leaving the reserved row non-terminal so a
    native resume can finalize it. This is the default (flag omitted).
    """

    def test_native_pause_writes_state_and_leaves_row_non_terminal(
        self, pg_engine, monkeypatch
    ):
        user_id = f"user-{uuid.uuid4().hex[:8]}"
        with pg_engine.begin() as conn:
            _seed_user(conn, user_id)

        approval_calls = [
            {
                "call_id": "call_xyz",
                "name": "send_msg_0",
                "tool_name": "telegram",
                "action_name": "send_msg",
                "arguments": {"text": "hi"},
                "pause_type": "awaiting_approval",
            }
        ]

        with _wire_db(pg_engine, monkeypatch):
            base = BaseAnswerResource.__new__(BaseAnswerResource)
            base.default_model_id = "gpt-4"
            base.conversation_service = ConversationService()

            agent = _PausingAgent(approval_calls, with_tool_executor=True)
            agent.tools = []
            # Native default: finalize_tool_pause_as_complete omitted (False).
            frames = _drain(
                base.complete_stream(
                    question="message my team",
                    agent=agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": user_id},
                    should_persist=True,
                    model_id="gpt-4",
                )
            )

        joined = "\n".join(frames)
        assert "tool_calls_pending" in joined
        assert '"type": "end"' in joined

        with pg_engine.connect() as conn:
            from sqlalchemy import text

            conv_id = conn.execute(
                text(
                    "SELECT id FROM conversations WHERE user_id = :u "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"u": user_id},
            ).scalar()
            assert conv_id is not None
            statuses = _row_statuses(conn, str(conv_id))
            pts = _pending_tool_state_count(conn, str(conv_id))

        # Native UX preserved: row stays non-terminal (awaiting native
        # resume) and a continuation record was written.
        assert statuses, "expected a reserved row"
        assert statuses[0] in ("pending", "streaming")
        assert "complete" not in statuses
        assert pts == 1


# ---------------------------------------------------------------------------
# Guarantee 2 — coherent Option B routing: a v1 continuation carrying a
# conversation_id rebuilds STATELESSLY via build_continuation_from_messages
# (never resume_from_tool_actions), and threads no reserved_message_id.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestV1ContinuationRoutesStatelessly:
    """Coherent Option B: a v1 tool-result continuation is fully stateless on
    the resume side. Because the pause finalized the prior row ``complete`` and
    wrote NO ``pending_tool_state``, the route must rebuild from the re-POSTed
    history via ``build_continuation_from_messages`` — **even when a
    ``conversation_id`` is carried** — and must NOT call
    ``resume_from_tool_actions`` (whose ``load_state`` would 400). The
    ``_continuation`` dict therefore carries no live ``reserved_message_id`` /
    ``request_id`` (id-reuse is inert under this design).
    """

    def _build_app(self) -> Flask:
        app = Flask(__name__)
        app.register_blueprint(v1_bp)
        return app

    def test_continuation_with_conversation_id_uses_stateless_rebuild(self):
        app = self._build_app()

        def _fake_translate(data, api_key):
            return {
                "question": "",
                "tool_actions": [{"call_id": "c1", "result": "r"}],
                "conversation_id": "conv-1",
                "persist": True,
                "messages": data["messages"],
            }

        fake_processor = MagicMock()
        fake_processor.decoded_token = {"sub": "owner"}
        fake_processor.conversation_id = "conv-1"
        fake_processor.agent_config = {"user_api_key": "k"}
        fake_processor.agent_id = None
        fake_processor.model_id = "m"
        fake_processor.model_user_id = None
        # A real processor leaves these at None until a *native* resume hoists
        # them; the route must not invent values from them.
        fake_processor.reserved_message_id = None
        fake_processor.request_id = None

        build_calls: Dict[str, Any] = {}

        def _fake_build_continuation(messages, tool_actions):
            build_calls["messages"] = messages
            build_calls["tool_actions"] = tool_actions
            return (MagicMock(), [], {}, [{"call_id": "c1"}], tool_actions, "")

        fake_processor.build_continuation_from_messages.side_effect = (
            _fake_build_continuation
        )

        captured: Dict[str, Any] = {}

        def _capture_complete_stream(**kw):
            captured.update(kw)
            return iter(['data: {"type": "end"}'])

        fake_helper = MagicMock()
        fake_helper.check_usage.return_value = None
        fake_helper.complete_stream.side_effect = _capture_complete_stream
        fake_helper.process_response_stream.return_value = {
            "error": None,
            "conversation_id": "conv-1",
            "answer": "done",
            "sources": [],
            "tool_calls": [],
            "thought": "",
        }

        @contextmanager
        def _yield_conn():
            yield MagicMock()

        with patch(
            "application.api.v1.routes.translate_request",
            side_effect=_fake_translate,
        ), patch(
            "application.api.v1.routes.StreamProcessor",
            return_value=fake_processor,
        ), patch(
            "application.api.v1.routes._V1AnswerHelper",
            return_value=fake_helper,
        ), patch(
            "application.api.v1.routes.db_readonly",
            _yield_conn,
        ), patch(
            "application.api.v1.routes.translate_response",
            return_value={"id": "x", "choices": []},
        ):
            with app.test_client() as c:
                resp = c.post(
                    "/v1/chat/completions",
                    headers={"Authorization": "Bearer x"},
                    json={
                        "conversation_id": "conv-1",
                        "messages": [
                            {"role": "user", "content": "hi"},
                            {
                                "role": "assistant",
                                "tool_calls": [{"id": "c1", "function": {}}],
                            },
                            {"role": "tool", "tool_call_id": "c1", "content": "r"},
                        ],
                    },
                )

        assert resp.status_code == 200
        # Coherent Option B: the stateless rebuild ran...
        fake_processor.build_continuation_from_messages.assert_called_once()
        assert build_calls["tool_actions"] == [{"call_id": "c1", "result": "r"}]
        # ...and the stateful native resume was NOT used.
        fake_processor.resume_from_tool_actions.assert_not_called()

        continuation = captured.get("_continuation")
        assert continuation is not None
        # id-reuse is gone from the v1 continuation dict (inert under Option B).
        assert "reserved_message_id" not in continuation
        assert "request_id" not in continuation
        # The v1 path still runs in stateless-finalize mode.
        assert captured.get("finalize_tool_pause_as_complete") is True
        # The incoming conversation_id is the persistence target.
        assert captured.get("conversation_id") == "conv-1"


# ---------------------------------------------------------------------------
# Regression catcher — real two-POST /v1/chat/completions round-trip
# ---------------------------------------------------------------------------


class _FakeLLMGen:
    """LLM stand-in for the answer path's title-gen ``create_llm``.

    The append branch of ``save_conversation`` (conversation_id present) never
    calls ``gen``; this just satisfies the ``LLMCreator.create_llm`` call that
    ``complete_stream`` makes before persisting.
    """

    model_id = "gpt-4"
    _request_id: Optional[str] = None
    _token_usage_source: Optional[str] = None

    def gen(self, *args, **kwargs) -> str:
        return "Title"


class _FakeClientToolExecutor:
    """Tool executor stub exposing ``get_tools`` for the real
    ``build_continuation_from_messages`` (which reads the agent's tools)."""

    def __init__(self) -> None:
        self.client_tools: Optional[List[Dict[str, Any]]] = None
        self.message_id: Optional[str] = None
        self.conversation_id: Optional[str] = None

    def get_tools(self) -> Dict[str, Any]:
        return {"0": {"name": "get_weather", "client_side": True}}


class _PauseThenAnswerAgent:
    """Agent that pauses for a client tool on ``gen`` (POST #1) and emits a
    final answer on ``gen_continuation`` (POST #2).

    A fresh instance is handed back by the patched ``build_agent`` for each
    request, so the first POST (normal mode) drives ``gen`` and the second
    (continuation mode) drives ``gen_continuation``.
    """

    ANSWER_TEXT = "It is 72F and sunny in SF."

    def __init__(self, pending_tool_calls: List[Dict[str, Any]]) -> None:
        self.llm = _FakeLLM()
        self.tool_executor = _FakeClientToolExecutor()
        self._pending_tool_calls = pending_tool_calls
        self._pending_continuation: Optional[Dict[str, Any]] = None
        self.conversation_id: Optional[str] = None
        self.initial_user_id: Optional[str] = None
        self.tools: List[Dict[str, Any]] = []

    def gen(self, query: str = ""):
        # First turn: pause for the client tool.
        self._pending_continuation = {
            "messages": [{"role": "system", "content": "sys"}],
            "pending_tool_calls": self._pending_tool_calls,
            "tools_dict": {"0": {"name": "get_weather", "client_side": True}},
            "reasoning_content": "",
        }
        yield {
            "type": "tool_calls_pending",
            "data": {"pending_tool_calls": self._pending_tool_calls},
        }

    def gen_continuation(self, **kwargs):
        # Resume turn: emit the final answer and finish normally.
        yield {"answer": self.ANSWER_TEXT}


def _seed_agent(conn, user_id: str, key: str) -> None:
    from application.storage.db.repositories.agents import AgentsRepository

    AgentsRepository(conn).create(user_id, "Weather Agent", "published", key=key)


@contextmanager
def _wire_v1_route_db(engine, monkeypatch):
    """Full route-level DB wiring for the ``/v1/chat/completions`` blueprint.

    Extends ``_wire_db`` (conversation/continuation/base services) with the v1
    routes module's own ``db_readonly`` (used by ``_lookup_agent``) and a fake
    title-gen ``LLMCreator`` on the base module, so a real two-POST round-trip
    runs entirely against the ephemeral Postgres with no live LLM/provider.
    """
    from application.api.v1 import routes as v1_routes_mod
    from application.api.answer.routes import base as base_mod

    @contextmanager
    def _readonly():
        conn = engine.connect()
        try:
            yield conn
        finally:
            conn.close()

    with _wire_db(engine, monkeypatch):
        monkeypatch.setattr(v1_routes_mod, "db_readonly", _readonly)
        monkeypatch.setattr(
            base_mod.LLMCreator,
            "create_llm",
            staticmethod(lambda *a, **kw: _FakeLLMGen()),
        )
        yield


def _post_chat(client, body: Dict[str, Any], api_key: str):
    return client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=body,
    )


@pytest.mark.integration
class TestV1ToolRoundTripEndToEnd:
    """Drive the real ``/v1/chat/completions`` route twice through the real
    ``routes.py`` routing and real ``StreamProcessor.build_continuation_from_messages``.

    Only the agent *creation* is mocked (``StreamProcessor.build_agent`` returns
    a fake that pauses then answers) — the route logic, the continuation
    rebuild, and ``resume_from_tool_actions`` are NOT mocked. This is the
    regression catcher: the pre-fix route sends a conversation_id-carrying
    continuation to ``resume_from_tool_actions`` → ``load_state`` returns None →
    ``ValueError`` → HTTP 400 on POST #2.
    """

    CLIENT_TOOL = {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }

    PENDING = [
        {
            "call_id": "call_abc",
            "name": "get_weather",
            "tool_name": "get_weather",
            "action_name": "get_weather",
            "arguments": {"city": "SF"},
            "pause_type": "requires_client_execution",
        }
    ]

    def _build_app(self) -> Flask:
        app = Flask(__name__)
        app.register_blueprint(v1_bp)
        return app

    def _count_non_terminal(self, conn, user_id: str) -> int:
        from sqlalchemy import text

        return conn.execute(
            text(
                "SELECT count(*) FROM conversation_messages cm "
                "JOIN conversations c ON c.id = cm.conversation_id "
                "WHERE c.user_id = :u "
                "AND cm.status IN ('pending', 'streaming')"
            ),
            {"u": user_id},
        ).scalar()

    def test_pause_then_answer_round_trip_persists_into_same_conversation(
        self, pg_engine, monkeypatch
    ):
        user_id = f"user-{uuid.uuid4().hex[:8]}"
        api_key = f"key-{uuid.uuid4().hex[:8]}"
        with pg_engine.begin() as conn:
            _seed_user(conn, user_id)
            _seed_agent(conn, user_id, api_key)

        app = self._build_app()

        # ``build_agent`` is the only mock — a fresh pausing/answering agent
        # per call. The route's ``build_continuation_from_messages`` calls this
        # internally on POST #2, so the rebuild itself still runs for real.
        def _fake_build_agent(self, question):  # noqa: ARG001
            return _PauseThenAnswerAgent(
                TestV1ToolRoundTripEndToEnd.PENDING
            )

        # ---- POST #1: user question -> agent pauses for the client tool ----
        with _wire_v1_route_db(pg_engine, monkeypatch), patch(
            "application.api.answer.services.stream_processor.StreamProcessor"
            ".build_agent",
            _fake_build_agent,
        ):
            with app.test_client() as c:
                resp1 = _post_chat(
                    c,
                    {
                        "messages": [{"role": "user", "content": "weather in SF?"}],
                        "tools": [self.CLIENT_TOOL],
                        "docsgpt": {"save_conversation": True},
                    },
                    api_key,
                )

        assert resp1.status_code == 200, resp1.get_data(as_text=True)
        body1 = resp1.get_json()
        choice1 = body1["choices"][0]
        # OpenAI surfaces the pending client tool call.
        assert choice1["finish_reason"] == "tool_calls"
        tool_calls1 = choice1["message"]["tool_calls"]
        assert tool_calls1[0]["function"]["name"] == "get_weather"
        assert tool_calls1[0]["id"] == "call_abc"
        # A conversation id is returned for the client to thread back.
        conv_id = body1.get("docsgpt", {}).get("conversation_id")
        assert conv_id

        # Reserved row finalized ``complete`` (with tool_calls); no
        # ``pending_tool_state`` and no non-terminal row.
        with pg_engine.connect() as conn:
            statuses = _row_statuses(conn, conv_id)
            assert statuses == ["complete"]
            assert _pending_tool_state_count(conn, conv_id) == 0
            assert self._count_non_terminal(conn, user_id) == 0

        # ---- POST #2: tool result + conversation_id -> agent answers ----
        with _wire_v1_route_db(pg_engine, monkeypatch), patch(
            "application.api.answer.services.stream_processor.StreamProcessor"
            ".build_agent",
            _fake_build_agent,
        ):
            with app.test_client() as c:
                resp2 = _post_chat(
                    c,
                    {
                        "messages": [
                            {"role": "user", "content": "weather in SF?"},
                            {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_abc",
                                        "type": "function",
                                        "function": {
                                            "name": "get_weather",
                                            "arguments": json.dumps({"city": "SF"}),
                                        },
                                    }
                                ],
                            },
                            {
                                "role": "tool",
                                "tool_call_id": "call_abc",
                                "content": "72F sunny",
                            },
                        ],
                        "conversation_id": conv_id,
                        "docsgpt": {"save_conversation": True},
                    },
                    api_key,
                )

        # The regression: pre-fix this is a 400 (resume_from_tool_actions ->
        # load_state None -> ValueError). Post-fix it is a 200 answer.
        assert resp2.status_code == 200, resp2.get_data(as_text=True)
        body2 = resp2.get_json()
        choice2 = body2["choices"][0]
        assert choice2["finish_reason"] == "stop"
        assert choice2["message"]["content"] == _PauseThenAnswerAgent.ANSWER_TEXT
        # The answer persisted into the SAME conversation.
        assert body2.get("docsgpt", {}).get("conversation_id") == conv_id

        with pg_engine.connect() as conn:
            from sqlalchemy import text

            # The answer is a NEW terminal turn appended to the same
            # conversation: the original tool-call turn + the answer turn.
            statuses = _row_statuses(conn, conv_id)
            assert statuses == ["complete", "complete"]
            # Nothing left non-terminal anywhere for this user / conversation.
            assert self._count_non_terminal(conn, user_id) == 0
            # The appended turn carries the assistant answer.
            answer_rows = conn.execute(
                text(
                    "SELECT response FROM conversation_messages "
                    "WHERE conversation_id = CAST(:c AS uuid) "
                    "ORDER BY position ASC"
                ),
                {"c": conv_id},
            ).fetchall()
            assert answer_rows[-1][0] == _PauseThenAnswerAgent.ANSWER_TEXT
            # Exactly one conversation was used (no orphan sibling created).
            conv_count = conn.execute(
                text("SELECT count(*) FROM conversations WHERE user_id = :u"),
                {"u": user_id},
            ).scalar()
            assert conv_count == 1

