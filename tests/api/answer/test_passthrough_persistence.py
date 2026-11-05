"""Request ``passthrough`` values are kept on the conversation and the turn's Logs row."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import text as sql_text

from docsgpt.api.answer.services.passthrough import (
    MAX_KEYS,
    MAX_VALUE_CHARS,
    stored_passthrough,
)


@pytest.mark.unit
class TestStoredPassthrough:
    def test_keeps_scalars(self):
        raw = {"user_id": "emp-42", "tier": 2, "score": 0.5, "admin": False, "team": None}
        assert stored_passthrough(raw) == raw

    def test_drops_nested_and_non_finite_values(self):
        raw = {"ok": "yes", "nested": {"a": 1}, "items": [1], "nan": float("nan"), "inf": float("inf")}
        assert stored_passthrough(raw) == {"ok": "yes"}

    def test_bounds_keys_and_strings(self):
        raw = {f"k{i}": "x" * (MAX_VALUE_CHARS + 10) for i in range(MAX_KEYS + 5)}
        raw["k" * 100] = "long key"
        stored = stored_passthrough(raw)
        assert len(stored) == MAX_KEYS
        assert all(len(value) == MAX_VALUE_CHARS for value in stored.values())
        assert "k" * 100 not in stored

    @pytest.mark.parametrize("raw", [None, "user", ["a"], {}, {"nested": {"a": 1}}])
    def test_nothing_left_is_none(self, raw):
        assert stored_passthrough(raw) is None


def _agent(answer: str = "hi"):
    agent = MagicMock()
    agent.gen.side_effect = lambda query: iter([{"answer": answer}])
    agent.tool_calls = []
    agent.compression_metadata = None
    agent.compression_saved = False
    return agent


def _run(resource, **kwargs):
    base = dict(
        question="Where is my order?",
        agent=_agent(),
        conversation_id=None,
        user_api_key=None,
        decoded_token={"sub": "owner-1"},
        should_persist=True,
        model_id="gpt-4",
    )
    base.update(kwargs)
    return list(resource.complete_stream(**base))


@pytest.mark.unit
class TestTurnPersistence:
    def test_conversation_and_log_row_keep_the_values(self, pg_conn, flask_app):
        from docsgpt.api.answer.routes.base import BaseAnswerResource
        from tests.api.answer.test_base_routes import _patch_db_session

        with flask_app.app_context(), _patch_db_session(pg_conn):
            _run(BaseAnswerResource(), passthrough={"user_id": "emp-42"})

        log = pg_conn.execute(sql_text("SELECT data FROM user_logs WHERE user_id = 'owner-1'")).fetchone()[0]
        assert log["passthrough"] == {"user_id": "emp-42"}
        assert log["conversation_id"]
        conversation = pg_conn.execute(
            sql_text("SELECT passthrough FROM conversations WHERE id = CAST(:id AS uuid)"),
            {"id": log["conversation_id"]},
        ).fetchone()
        assert conversation[0] == {"user_id": "emp-42"}

    def test_a_later_turn_replaces_the_conversations_values(self, pg_conn, flask_app):
        from docsgpt.api.answer.routes.base import BaseAnswerResource
        from tests.api.answer.test_base_routes import _patch_db_session

        with flask_app.app_context(), _patch_db_session(pg_conn):
            _run(BaseAnswerResource(), passthrough={"user_id": "emp-42"})
            conversation_id = pg_conn.execute(
                sql_text("SELECT data->>'conversation_id' FROM user_logs WHERE user_id = 'owner-1'")
            ).scalar()
            _run(
                BaseAnswerResource(),
                conversation_id=conversation_id,
                passthrough={"user_id": "emp-42", "page": "billing"},
            )

        stored = pg_conn.execute(
            sql_text("SELECT passthrough FROM conversations WHERE id = CAST(:id AS uuid)"),
            {"id": conversation_id},
        ).scalar()
        assert stored == {"user_id": "emp-42", "page": "billing"}

    def test_a_later_turn_without_values_clears_them(self, pg_conn, flask_app):
        from docsgpt.api.answer.routes.base import BaseAnswerResource
        from tests.api.answer.test_base_routes import _patch_db_session

        with flask_app.app_context(), _patch_db_session(pg_conn):
            _run(BaseAnswerResource(), passthrough={"user_id": "emp-42"})
            conversation_id = pg_conn.execute(
                sql_text("SELECT data->>'conversation_id' FROM user_logs WHERE user_id = 'owner-1'")
            ).scalar()
            _run(BaseAnswerResource(), conversation_id=conversation_id)

        stored = pg_conn.execute(
            sql_text("SELECT passthrough FROM conversations WHERE id = CAST(:id AS uuid)"),
            {"id": conversation_id},
        ).scalar()
        assert stored is None

    def test_a_turn_without_values_logs_none(self, pg_conn, flask_app):
        from docsgpt.api.answer.routes.base import BaseAnswerResource
        from tests.api.answer.test_base_routes import _patch_db_session

        with flask_app.app_context(), _patch_db_session(pg_conn):
            _run(BaseAnswerResource())

        log = pg_conn.execute(sql_text("SELECT data FROM user_logs WHERE user_id = 'owner-1'")).fetchone()[0]
        assert "passthrough" not in log
        assert log["conversation_id"]


@pytest.mark.unit
class TestPauseState:
    def test_the_pause_keeps_the_values_for_the_resume(self, flask_app):
        from unittest.mock import patch

        from docsgpt.api.answer.routes.base import BaseAnswerResource

        agent = MagicMock()
        agent.guardrails_config = None
        with flask_app.app_context(), patch("docsgpt.api.answer.routes.base.ContinuationService") as service:
            saved = BaseAnswerResource()._save_pause_state(
                agent=agent,
                continuation={"messages": [], "pending_tool_calls": [], "tools_dict": {}},
                conversation_id="c1",
                decoded_token={"sub": "owner-1"},
                model_id="gpt-4",
                model_user_id=None,
                user_api_key=None,
                agent_id=None,
                paused_sources=[],
                reserved_message_id=None,
                request_id="r1",
                tool_calls=[],
                passthrough={"user_id": "emp-42"},
            )
        assert saved
        agent_config = service.return_value.save_state.call_args.kwargs["agent_config"]
        assert agent_config["passthrough"] == {"user_id": "emp-42"}


@pytest.mark.unit
class TestProcessor:
    def test_request_values_are_bounded_for_storage(self):
        from docsgpt.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor(
            {"question": "q", "passthrough": {"user_id": "emp-42", "profile": {"a": 1}}},
            {"sub": "u"},
        )
        assert processor.passthrough == {"user_id": "emp-42"}


@pytest.mark.unit
class TestWorkflowSeed:
    def test_passthrough_starts_the_run_state(self):
        from docsgpt.agents.workflow_agent import WorkflowAgent

        agent = WorkflowAgent.__new__(WorkflowAgent)
        agent.passthrough = {"user_id": "emp-42"}
        assert agent._initial_inputs([]) == {"input_documents": [], "passthrough": {"user_id": "emp-42"}}

    def test_no_passthrough_leaves_it_out(self):
        from docsgpt.agents.workflow_agent import WorkflowAgent

        agent = WorkflowAgent.__new__(WorkflowAgent)
        agent.passthrough = None
        assert agent._initial_inputs([]) == {"input_documents": []}
