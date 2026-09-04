"""Mid-execution compression must persist once, break the Responses chain,
and treat an empty summary as a failure.

Background (prod 2026-09-01): the DB path wrote the compression point and the
summary row, then left ``compression_saved`` False so the route wrote both
again; and the rebuilt four-message input was still sent with
``previous_response_id``, so Azure prepended the uncompressed transcript
(236k input tokens for four local messages).
"""

from typing import Any, Dict, Generator
from unittest.mock import Mock, patch

import pytest

from application.llm.handlers.base import LLMHandler, LLMResponse, ToolCall


class _Handler(LLMHandler):
    def parse_response(self, response: Any) -> LLMResponse:
        return LLMResponse(
            content=str(response), tool_calls=[], finish_reason="stop", raw_response=response
        )

    def create_tool_message(self, tool_call: ToolCall, result: Any) -> Dict:
        return {"role": "tool", "content": str(result), "tool_call_id": tool_call.id}

    def _iterate_stream(self, response: Any) -> Generator:
        yield from response


def _agent():
    agent = Mock()
    agent.conversation_id = "conv1"
    agent.initial_user_id = "user1"
    agent.model_id = "gpt-5.6"
    agent.decoded_token = {}
    agent.context_limit_reached = True
    agent.current_token_count = 999
    agent.llm = Mock()
    return agent


def _result(compressed=100, original=1000, summary="summary"):
    metadata = Mock()
    metadata.compressed_token_count = compressed
    metadata.original_token_count = original
    metadata.compression_ratio = original / max(compressed, 1)
    metadata.timestamp = "2026-09-03T10:00:00+00:00"
    metadata.to_dict.return_value = {"timestamp": metadata.timestamp}
    result = Mock()
    result.success = True
    result.compression_performed = True
    result.compressed_summary = summary
    result.recent_queries = []
    result.metadata = metadata
    result.error = None
    return result


def _run(handler, agent, result):
    conv_service = Mock()
    conv_service.get_conversation.return_value = {"queries": []}
    orchestrator = Mock()
    orchestrator.compress_mid_execution.return_value = result
    with patch(
        "application.api.answer.services.compression.CompressionOrchestrator",
        return_value=orchestrator,
    ), patch(
        "application.api.answer.services.conversation_service.ConversationService",
        return_value=conv_service,
    ), patch.object(
        handler, "_build_conversation_from_messages", return_value={"queries": []}
    ), patch.object(
        handler,
        "_rebuild_messages_after_compression",
        return_value=[{"role": "system", "content": "rebuilt"}],
    ), patch.object(handler, "_prune_messages_minimal", return_value=None):
        return handler._perform_mid_execution_compression(
            agent, [{"role": "user", "content": "hi"}]
        ), conv_service


@pytest.mark.unit
def test_db_path_persists_once_and_breaks_chain():
    agent = _agent()
    (success, messages), conv_service = _run(_Handler(), agent, _result())

    assert success is True and messages
    # The orchestrator's compress_and_save already wrote the point; the
    # handler wrote the visible row. The route must not write either again.
    conv_service.append_compression_message.assert_called_once()
    assert agent.compression_saved is True
    # The rebuilt messages are the whole context now: forget the chain so
    # the next call is not prepended with the uncompressed transcript.
    agent.llm.start_responses_turn.assert_called_once()
    assert agent.last_compression_at == "2026-09-03T10:00:00+00:00"
    assert agent.context_limit_reached is False


@pytest.mark.unit
def test_empty_summary_is_a_failure_not_a_success():
    agent = _agent()
    (success, messages), conv_service = _run(
        _Handler(), agent, _result(compressed=0, original=1000, summary="")
    )
    assert success is False and messages is None
    conv_service.append_compression_message.assert_not_called()
    agent.llm.start_responses_turn.assert_not_called()
