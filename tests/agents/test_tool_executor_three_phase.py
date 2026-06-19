"""Tests for the journaled execute path on ToolExecutor.

Each tool call inserts a ``tool_call_attempts`` row and flips it
``proposed → executed`` (or ``→ failed``). With a ``message_id`` it
stays ``executed`` for the finalize path to confirm; without one
(``save_conversation=False``) it goes straight to ``confirmed``.
"""

from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from sqlalchemy import text

from application.agents.tool_executor import ToolExecutor


@contextmanager
def _yield_pg(conn):
    """Adapter so the executor's ``db_session()`` writes land on ``pg_conn``."""

    @contextmanager
    def _yield():
        yield conn

    return _yield


def _patch_db(monkeypatch, pg_conn):
    """Patch all ``db_session`` entry points used by the executor and tools.

    Each module imports ``db_session`` / ``db_readonly`` by name so each
    module-level binding has to be replaced individually.
    """

    @contextmanager
    def _use_pg():
        yield pg_conn

    targets = (
        "application.agents.tool_executor",
        "application.agents.tools.notes",
        "application.agents.tools.todo_list",
        "application.storage.db.session",
    )
    for module in targets:
        monkeypatch.setattr(f"{module}.db_session", _use_pg, raising=False)
        monkeypatch.setattr(f"{module}.db_readonly", _use_pg, raising=False)


def _drain(gen):
    """Exhaust a generator, returning ``(events, return_value)``."""
    events = []
    while True:
        try:
            events.append(next(gen))
        except StopIteration as exc:
            return events, exc.value


def _select_attempt(pg_conn, call_id):
    row = pg_conn.execute(
        text("SELECT * FROM tool_call_attempts WHERE call_id = :cid"),
        {"cid": call_id},
    ).fetchone()
    return row._mapping if row is not None else None


def _make_call(name="test_action_t1", call_id="c1"):
    call = Mock()
    call.name = name
    call.id = call_id
    call.arguments = "{}"
    return call


_TOOLS_DICT = {
    "t1": {
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "test_tool",
        "config": {"key": "val"},
        "actions": [
            {"name": "test_action", "description": "T", "parameters": {"properties": {}}},
        ],
    }
}


@pytest.mark.unit
class TestExecuteJournaling:
    def test_no_message_id_proposed_then_confirmed(
        self, pg_conn, mock_tool_manager, monkeypatch
    ):
        """No reserved message (``save_conversation=False``) → row lands ``confirmed``, not ``executed``."""
        executor = ToolExecutor(user="u")
        monkeypatch.setattr(
            "application.agents.tool_executor.ToolActionParser",
            lambda _cls, **kw: Mock(
                parse_args=Mock(return_value=("t1", "test_action", {"q": "v"}))
            ),
        )
        _patch_db(monkeypatch, pg_conn)

        events, result = _drain(executor.execute(_TOOLS_DICT, _make_call(), "MockLLM"))
        assert result[0] == "Tool result"

        row = _select_attempt(pg_conn, "c1")
        assert row is not None
        assert row["status"] == "confirmed"
        assert row["tool_name"] == "test_tool"
        assert row["action_name"] == "test_action"
        assert row["arguments"] == {"q": "v"}
        # Result is wrapped so a future ``artifact_id`` can ride alongside.
        assert row["result"] == {"result": "Tool result"}
        assert row["error"] is None
        assert row["message_id"] is None

    def test_executor_message_id_is_persisted_on_executed_row(
        self, pg_conn, mock_tool_manager, monkeypatch
    ):
        """The executor's message_id is carried onto the journal row, which stays ``executed``."""
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        # FK constraint: message_id must reference a real row.
        repo = ConversationsRepository(pg_conn)
        conv = repo.create("u-mid", "msg-id-test")
        msg = repo.reserve_message(
            str(conv["id"]),
            prompt="q?",
            placeholder_response="...",
            request_id="req-mid-1",
            status="pending",
        )
        message_uuid = str(msg["id"])

        executor = ToolExecutor(user="u")
        executor.message_id = message_uuid
        monkeypatch.setattr(
            "application.agents.tool_executor.ToolActionParser",
            lambda _cls, **kw: Mock(
                parse_args=Mock(return_value=("t1", "test_action", {}))
            ),
        )
        _patch_db(monkeypatch, pg_conn)

        _drain(executor.execute(_TOOLS_DICT, _make_call(call_id="cm1"), "MockLLM"))

        row = _select_attempt(pg_conn, "cm1")
        assert row is not None
        assert row["status"] == "executed"
        assert str(row["message_id"]) == message_uuid

    def test_tool_raises_marks_failed_and_reraises(
        self, pg_conn, mock_tool_manager, monkeypatch
    ):
        executor = ToolExecutor(user="u")
        monkeypatch.setattr(
            "application.agents.tool_executor.ToolActionParser",
            lambda _cls, **kw: Mock(
                parse_args=Mock(return_value=("t1", "test_action", {}))
            ),
        )
        _patch_db(monkeypatch, pg_conn)
        mock_tool_manager.load_tool.return_value.execute_action.side_effect = (
            RuntimeError("boom")
        )

        gen = executor.execute(_TOOLS_DICT, _make_call(call_id="c2"), "MockLLM")
        with pytest.raises(RuntimeError, match="boom"):
            _drain(gen)

        row = _select_attempt(pg_conn, "c2")
        assert row is not None
        assert row["status"] == "failed"
        assert row["error"] == "boom"


@pytest.mark.unit
class TestRepository:
    def test_proposed_then_confirmed_when_no_message(self, pg_conn):
        from application.storage.db.repositories.tool_call_attempts import (
            ToolCallAttemptsRepository,
        )

        repo = ToolCallAttemptsRepository(pg_conn)
        assert repo.record_proposed("c-x", "tool", "act", {"a": 1}) is True
        # Duplicate insert is a no-op; original row stays put.
        assert repo.record_proposed("c-x", "tool", "act", {"a": 1}) is False
        row = _select_attempt(pg_conn, "c-x")
        assert row["status"] == "proposed"

        assert repo.mark_executed("c-x", {"out": "ok"}) is True
        row = _select_attempt(pg_conn, "c-x")
        assert row["status"] == "confirmed"
        assert row["message_id"] is None
        assert row["result"] == {"result": {"out": "ok"}}

    def test_mark_executed_with_message_stays_executed(self, pg_conn):
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )
        from application.storage.db.repositories.tool_call_attempts import (
            ToolCallAttemptsRepository,
        )

        # FK constraint: message_id must reference a real row.
        conv_repo = ConversationsRepository(pg_conn)
        conv = conv_repo.create("u-repo", "repo-msg-test")
        msg = conv_repo.reserve_message(
            str(conv["id"]),
            prompt="q?",
            placeholder_response="...",
            request_id="req-repo-1",
            status="pending",
        )
        message_uuid = str(msg["id"])

        repo = ToolCallAttemptsRepository(pg_conn)
        repo.record_proposed("c-m", "tool", "act", {})
        assert (
            repo.mark_executed("c-m", {"out": "ok"}, message_id=message_uuid) is True
        )
        row = _select_attempt(pg_conn, "c-m")
        assert row["status"] == "executed"
        assert str(row["message_id"]) == message_uuid

    def test_upsert_executed_without_message_confirms(self, pg_conn):
        """``upsert_executed`` (DB-outage fallback) with no ``message_id`` lands ``confirmed``."""
        from application.storage.db.repositories.tool_call_attempts import (
            ToolCallAttemptsRepository,
        )

        repo = ToolCallAttemptsRepository(pg_conn)
        repo.upsert_executed("c-up", "tool", "act", {"a": 1}, {"out": "ok"})
        row = _select_attempt(pg_conn, "c-up")
        assert row["status"] == "confirmed"
        assert row["message_id"] is None
        assert row["result"] == {"result": {"out": "ok"}}

    def test_mark_failed_sets_error(self, pg_conn):
        from application.storage.db.repositories.tool_call_attempts import (
            ToolCallAttemptsRepository,
        )

        repo = ToolCallAttemptsRepository(pg_conn)
        repo.record_proposed("c-y", "tool", "act", {})
        assert repo.mark_failed("c-y", "kaboom") is True
        row = _select_attempt(pg_conn, "c-y")
        assert row["status"] == "failed"
        assert row["error"] == "kaboom"

    def test_mark_failed_leaves_executed_row_untouched(self, pg_conn):
        """A late error for a reused ``call_id`` ("call_0"-style) must
        not flip an already-executed row (see ``mark_failed``)."""
        from application.storage.db.repositories.tool_call_attempts import (
            ToolCallAttemptsRepository,
        )

        repo = ToolCallAttemptsRepository(pg_conn)
        repo.record_proposed("c-dup", "tool", "act", {})
        # No message_id ⇒ lands straight in 'confirmed' (still non-proposed).
        assert repo.mark_executed("c-dup", {"out": "ok"}) is True
        # Late error path hits the same id — the guard rejects the update.
        assert repo.mark_failed("c-dup", "boom") is False
        row = _select_attempt(pg_conn, "c-dup")
        assert row["status"] == "confirmed"
        assert row["error"] is None

    def test_mark_executed_guarded_to_proposed(self, pg_conn):
        """A reused ``call_id`` must not flip an already-terminal row back
        to executed (the status guard mirrors ``mark_failed``)."""
        from application.storage.db.repositories.tool_call_attempts import (
            ToolCallAttemptsRepository,
        )

        repo = ToolCallAttemptsRepository(pg_conn)
        repo.record_proposed("c-me", "tool", "act", {})
        assert repo.mark_failed("c-me", "boom") is True
        # Late executed emission for the same id: no proposed row remains.
        assert repo.mark_executed("c-me", {"out": "ok"}) is False
        row = _select_attempt(pg_conn, "c-me")
        assert row["status"] == "failed"
        assert row["result"] is None

    def test_mark_executed_scoped_to_owner(self, pg_conn):
        """A colliding ``call_id`` from another tenant can't flip — or
        read its result into — this user's proposed row."""
        from application.storage.db.repositories.tool_call_attempts import (
            ToolCallAttemptsRepository,
        )

        repo = ToolCallAttemptsRepository(pg_conn)
        repo.record_proposed("call_0", "tool", "act", {}, user_id="victim")
        # Attacker's request reuses the id and tries to land its result.
        assert (
            repo.mark_executed("call_0", {"out": "leak"}, user_id="attacker")
            is False
        )
        row = _select_attempt(pg_conn, "call_0")
        assert row["status"] == "proposed"
        assert row["result"] is None
        assert row["user_id"] == "victim"

    def test_mark_failed_scoped_to_owner(self, pg_conn):
        from application.storage.db.repositories.tool_call_attempts import (
            ToolCallAttemptsRepository,
        )

        repo = ToolCallAttemptsRepository(pg_conn)
        repo.record_proposed("call_0", "tool", "act", {}, user_id="victim")
        assert repo.mark_failed("call_0", "boom", user_id="attacker") is False
        row = _select_attempt(pg_conn, "call_0")
        assert row["status"] == "proposed"

    def test_upsert_executed_stamps_attribution(self, pg_conn):
        """The DB-outage fallback row must carry user/agent so it stays
        visible to per-user / per-agent analytics (was born unattributed)."""
        import uuid as _uuid

        from application.storage.db.repositories.tool_call_attempts import (
            ToolCallAttemptsRepository,
        )

        agent_id = str(_uuid.uuid4())
        repo = ToolCallAttemptsRepository(pg_conn)
        repo.upsert_executed(
            "c-up2", "tool", "act", {}, {"out": "ok"},
            user_id="u-up", agent_id=agent_id,
        )
        row = _select_attempt(pg_conn, "c-up2")
        assert row["user_id"] == "u-up"
        assert str(row["agent_id"]) == agent_id

    def test_upsert_executed_wont_clobber_other_tenant(self, pg_conn):
        """A colliding fallback upsert must not upgrade another tenant's
        proposed row or overwrite its result."""
        from application.storage.db.repositories.tool_call_attempts import (
            ToolCallAttemptsRepository,
        )

        repo = ToolCallAttemptsRepository(pg_conn)
        repo.record_proposed("call_0", "tool", "act", {}, user_id="victim")
        repo.upsert_executed(
            "call_0", "tool", "act", {}, {"out": "leak"}, user_id="attacker"
        )
        row = _select_attempt(pg_conn, "call_0")
        assert row["status"] == "proposed"
        assert row["result"] is None
        assert row["user_id"] == "victim"


@pytest.mark.unit
class TestDefaultToolJournaling:
    """A default tool's synthetic id round-trips through execute/journal."""

    def test_synthetic_tool_id_is_journaled(
        self, pg_conn, mock_tool_manager, monkeypatch
    ):
        from application.agents.default_tools import synthesize_default_tool

        memory_row = synthesize_default_tool("memory")
        assert memory_row is not None
        tools_dict = {memory_row["id"]: memory_row}

        executor = ToolExecutor(user="u")
        monkeypatch.setattr(
            "application.agents.tool_executor.ToolActionParser",
            lambda _cls, **kw: Mock(
                parse_args=Mock(
                    return_value=(memory_row["id"], "memory_view", {"path": "/"})
                )
            ),
        )
        _patch_db(monkeypatch, pg_conn)

        events, result = _drain(
            executor.execute(tools_dict, _make_call(call_id="c-def"), "MockLLM")
        )
        assert result[0] == "Tool result"

        row = _select_attempt(pg_conn, "c-def")
        assert row is not None
        assert row["status"] == "confirmed"
        assert row["tool_name"] == "memory"
        assert str(row["tool_id"]) == memory_row["id"]
