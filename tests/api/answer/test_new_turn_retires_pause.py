"""A new turn retires the turn still waiting on approval before reading the history it sends the model."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from tests.api.answer.services.test_abandoned_pause_pg import USER, _paused_turn


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.answer.services.continuation_service.db_readonly", _yield), patch(
        "docsgpt.api.answer.services.continuation_service.db_session", _yield
    ), patch("docsgpt.api.answer.services.conversation_service.db_readonly", _yield), patch(
        "docsgpt.api.answer.services.conversation_service.db_session", _yield
    ), patch("docsgpt.monitors.secret_refs.exposed_values", return_value={}), patch(
        "docsgpt.events.publisher.publish_user_event"
    ):
        yield


def _processor(conversation_id: str):
    from docsgpt.api.answer.services.stream_processor import StreamProcessor

    sp = StreamProcessor({"conversation_id": conversation_id, "question": "Now set the sender up"}, {"sub": USER})
    sp._ensure_turn_fits = lambda: None
    return sp


class TestTheNextTurnSeesTheCallsAsNotRun:
    def test_history_carries_every_call_and_the_not_run_one(self, pg_conn):
        turn = _paused_turn(pg_conn)
        sp = _processor(turn["conversation_id"])

        with _patch_db(pg_conn), patch(
            "docsgpt.api.answer.services.stream_processor.settings.ENABLE_CONVERSATION_COMPRESSION", False
        ):
            sp._load_conversation_history()

        (entry,) = sp.history
        assert entry["response"] == "I'll set this up as a signed webhook."
        calls = entry["tool_calls"]
        assert [c["call_id"] for c in calls] == ["call-1", "call-2", "call-3", "call-4", "call-5"]
        assert calls[-1]["result"].startswith("Not run:")

    def test_the_model_reads_the_abandoned_call_as_not_run(self, pg_conn):
        import types

        from docsgpt.agents.base import BaseAgent

        turn = _paused_turn(pg_conn)
        sp = _processor(turn["conversation_id"])
        with _patch_db(pg_conn), patch(
            "docsgpt.api.answer.services.stream_processor.settings.ENABLE_CONVERSATION_COMPRESSION", False
        ):
            sp._load_conversation_history()

        class _Agent(BaseAgent):
            def _gen_inner(self, query, log_context):
                yield from ()

        agent = _Agent.__new__(_Agent)
        agent.chat_history = sp.history
        agent.compressed_summary = None
        agent.model_id = "model"
        agent.model_user_id = None
        agent.user = USER
        agent.multimodal_content = None
        agent.llm = types.SimpleNamespace(_uses_responses_api=lambda: False)
        messages = agent._build_messages("system", "Now set the sender up")

        tool_results = {m["tool_call_id"]: m["content"] for m in messages if m.get("role") == "tool"}
        assert tool_results["call-1"] == '{"monitor_id": "m-1"}'
        assert tool_results["call-5"].startswith("Not run:")


class TestOnlyARealNewTurnRetiresThePause:
    @pytest.mark.unit
    def test_a_new_turn_retires_before_reading(self):
        sp = _processor("conv-1")
        order = []
        sp.conversation_service = MagicMock()
        sp.conversation_service.abandon_pending_approval.side_effect = lambda *a: order.append("retire")
        sp.conversation_service.get_conversation.side_effect = lambda *a: order.append("read") or {"queries": []}

        with patch("docsgpt.api.answer.services.stream_processor.settings.ENABLE_CONVERSATION_COMPRESSION", False):
            sp._load_conversation_history()

        sp.conversation_service.abandon_pending_approval.assert_called_once_with("conv-1", USER)
        assert order == ["retire", "read"]

    @pytest.mark.unit
    def test_a_failed_retire_never_fails_the_turn(self):
        sp = _processor("conv-1")
        sp.conversation_service = MagicMock()
        sp.conversation_service.abandon_pending_approval.side_effect = RuntimeError("db blip")
        sp.conversation_service.get_conversation.return_value = {"queries": []}

        with patch("docsgpt.api.answer.services.stream_processor.settings.ENABLE_CONVERSATION_COMPRESSION", False):
            sp._load_conversation_history()

        assert sp.history == []

    @pytest.mark.unit
    def test_a_resent_tool_round_does_not_retire_anything(self):
        """``/v1`` rebuilding a tool round from the transcript is answering the pause, not moving on."""
        sp = _processor("conv-1")
        sp.conversation_service = MagicMock()
        sp.conversation_service.get_conversation.return_value = {"queries": []}
        agent = MagicMock()
        agent.tool_executor.get_tools.return_value = {}

        def _build_agent(question):
            sp._load_conversation_history()
            return agent

        sp.build_agent = _build_agent
        messages = [
            {"role": "user", "content": "weather?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "sunny"},
        ]
        with patch("docsgpt.api.answer.services.stream_processor.settings.ENABLE_CONVERSATION_COMPRESSION", False):
            sp.build_continuation_from_messages(messages, [{"call_id": "c1", "result": "sunny"}])

        sp.conversation_service.abandon_pending_approval.assert_not_called()
