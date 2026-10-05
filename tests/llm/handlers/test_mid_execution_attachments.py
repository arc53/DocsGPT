"""Mid-execution compression keeps the current turn, attachments included.

Production (/v1 legal client): a tool loop crossed the threshold, the
mid-execution compression folded the whole message, attached documents
included, into a ~3k-token summary, and every later tool round of that turn
ran without the documents. Only earlier history may be summarized; the
turn's own message and files are carried over verbatim, round after round.
"""

import json
from typing import Any, Dict, Generator
from unittest.mock import Mock, patch

import pytest

from docsgpt.agents.base import BaseAgent
from docsgpt.llm.handlers.base import LLMHandler, LLMResponse, ToolCall
from docsgpt.utils import num_tokens_from_string

pytestmark = pytest.mark.unit

ATTACHED = "CONTRACT-CLAUSE-7 the buyer pays the deposit"
QUESTION = "Draft the offer letter from the attached contract."


class _Handler(LLMHandler):
    def parse_response(self, response: Any) -> LLMResponse:
        return LLMResponse(content=str(response), tool_calls=[], finish_reason="stop", raw_response=response)

    def create_tool_message(self, tool_call: ToolCall, result: Any) -> Dict:
        return {"role": "tool", "content": str(result), "tool_call_id": tool_call.id}

    def _iterate_stream(self, response: Any) -> Generator:
        yield from response


class _Agent(BaseAgent):
    def _gen_inner(self, query, log_context=None):
        yield {"answer": "ok"}


def _agent():
    llm = Mock()
    llm.get_supported_attachment_types = Mock(return_value=[])
    llm._supports_tools = Mock(return_value=True)
    llm.model_id = "m"
    attachment = {
        "id": "a1",
        "filename": "contract.txt",
        "mime_type": "text/plain",
        "content": ATTACHED,
        "token_count": num_tokens_from_string(ATTACHED),
        "metadata": {"extraction": {"status": "ok"}},
    }
    agent = _Agent(
        endpoint="stream",
        llm_name="openai",
        model_id="m",
        api_key="k",
        llm=llm,
        llm_handler=Mock(),
        decoded_token={"sub": "u"},
        attachments=[attachment],
        attachment_planning=True,
        chat_history=[{"prompt": "earlier question", "response": "earlier answer"}],
    )
    agent.conversation_id = "conv1"
    agent.initial_user_id = "u"
    agent._prepare_tools({})
    return agent


def _tool_round(messages, n):
    call_id = f"call_{n}"
    messages.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": call_id, "type": "function", "function": {"name": "search", "arguments": "{}"}}],
        }
    )
    messages.append({"role": "tool", "tool_call_id": call_id, "content": f"tool result {n}"})


def _result(summary="summary of earlier work"):
    metadata = Mock()
    metadata.compressed_token_count = 10
    metadata.original_token_count = 1000
    metadata.compression_ratio = 100
    metadata.timestamp = "2026-10-01T10:00:00+00:00"
    metadata.to_dict.return_value = {"timestamp": metadata.timestamp}
    result = Mock()
    result.success = True
    result.compression_performed = True
    result.compressed_summary = summary
    result.recent_queries = []
    result.metadata = metadata
    result.error = None
    return result


def _compress(handler, agent, messages):
    conv_service = Mock()
    conv_service.get_conversation.return_value = {"queries": [{"prompt": "earlier question"}]}
    orchestrator = Mock()
    orchestrator.compress_mid_execution.return_value = _result()
    with patch(
        "docsgpt.api.answer.services.compression.CompressionOrchestrator", return_value=orchestrator
    ), patch(
        "docsgpt.api.answer.services.conversation_service.ConversationService", return_value=conv_service
    ):
        outcome = handler._perform_mid_execution_compression(agent, messages)
    return outcome, orchestrator


def _summarized_text(orchestrator) -> str:
    conversation = orchestrator.compress_mid_execution.call_args.kwargs["current_conversation"]
    return json.dumps(conversation["queries"])


@pytest.fixture(autouse=True)
def _window():
    with patch("docsgpt.core.model_utils.get_token_limit", return_value=100_000):
        yield


def _turn():
    handler = _Handler()
    agent = _agent()
    messages = agent._build_messages("SYSTEM", QUESTION)
    messages = handler.prepare_messages(agent, messages, agent.attachments)
    return handler, agent, messages


class TestCurrentTurnSurvives:
    def test_attachments_and_question_are_not_summarized(self):
        handler, agent, messages = _turn()
        _tool_round(messages, 1)

        (ok, rebuilt), orchestrator = _compress(handler, agent, messages)

        assert ok is True
        summarized = _summarized_text(orchestrator)
        assert ATTACHED not in summarized
        assert QUESTION not in summarized
        # Earlier history is what gets summarized.
        assert "earlier question" in summarized

    def test_rebuilt_messages_carry_the_turn_verbatim(self):
        handler, agent, messages = _turn()
        turn = agent._current_turn_message
        _tool_round(messages, 1)

        (ok, rebuilt), _ = _compress(handler, agent, messages)

        assert any(m is turn for m in rebuilt)
        assert rebuilt[-1] is turn
        text = json.dumps(rebuilt)
        assert ATTACHED in text and QUESTION in text
        assert "Please continue with the remaining tasks" not in text

    def test_every_round_of_a_long_tool_loop_keeps_the_turn(self):
        handler, agent, messages = _turn()
        turn = agent._current_turn_message
        for round_number in range(1, 4):
            _tool_round(messages, round_number)
            (ok, messages), orchestrator = _compress(handler, agent, messages)
            assert ok is True
            assert messages[-1] is turn
            assert ATTACHED not in _summarized_text(orchestrator)

    def test_turn_is_found_after_a_resume_without_the_object(self):
        # A paused turn is resumed from serialized messages: the dict identity
        # is gone, so the turn is found by position instead.
        handler, agent, messages = _turn()
        _tool_round(messages, 1)
        restored = json.loads(json.dumps(messages))
        agent._current_turn_message = None

        (ok, rebuilt), orchestrator = _compress(handler, agent, restored)

        assert ok is True
        assert ATTACHED not in _summarized_text(orchestrator)
        assert ATTACHED in json.dumps(rebuilt[-1])

    def test_nothing_to_summarize_skips_the_compression_call(self):
        handler = _Handler()
        agent = _agent()
        agent.chat_history = []
        messages = agent._build_messages("SYSTEM", QUESTION)
        messages = handler.prepare_messages(agent, messages, agent.attachments)

        (ok, rebuilt), orchestrator = _compress(handler, agent, messages)

        assert ok is False
        orchestrator.compress_mid_execution.assert_not_called()

    def test_conversation_text_extraction_strips_attachment_blocks(self):
        handler, agent, messages = _turn()
        conversation = handler._build_conversation_from_messages(messages)
        assert ATTACHED not in json.dumps(conversation)
