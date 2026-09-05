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


# ── the summary already in play must survive a mid-execution compression ────


PRIOR = "Original delivery location: Warehouse Seven."


def _run_with(handler, agent, result, db_conversation, synthetic):
    conv_service = Mock()
    conv_service.get_conversation.return_value = db_conversation
    orchestrator = Mock()
    orchestrator.compress_mid_execution.return_value = result
    with patch(
        "application.api.answer.services.compression.CompressionOrchestrator",
        return_value=orchestrator,
    ), patch(
        "application.api.answer.services.conversation_service.ConversationService",
        return_value=conv_service,
    ), patch.object(
        handler, "_build_conversation_from_messages", return_value=synthetic
    ), patch.object(
        handler,
        "_rebuild_messages_after_compression",
        return_value=[{"role": "system", "content": "rebuilt"}],
    ), patch.object(handler, "_prune_messages_minimal", return_value=None):
        outcome = handler._perform_mid_execution_compression(
            agent, [{"role": "user", "content": "hi"}]
        )
    return outcome, orchestrator


@pytest.mark.unit
def test_db_path_carries_the_current_summary_and_persists_the_absolute_index():
    agent = _agent()
    agent.compressed_summary = PRIOR
    agent.last_compression_at = "2026-09-03T09:00:00+00:00"
    db_conversation = {
        "queries": [{"prompt": f"q{i}", "response": "r"} for i in range(20)],
        "compression_metadata": {
            "is_compressed": True,
            "compression_points": [{"query_index": 17, "compressed_summary": PRIOR,
                                    "compressed_token_count": 12}],
        },
    }
    # What the turn actually replayed: the two turns after the saved point
    # plus the in-flight one. Their indexes are 0-2 here, 18-19 in the DB.
    synthetic = {"queries": [{"prompt": "q18", "response": "r"}, {"prompt": "q19", "response": ""}],
                 "compression_metadata": {"is_compressed": False, "compression_points": []}}

    (success, _), orchestrator = _run_with(_Handler(), agent, _result(), db_conversation, synthetic)

    assert success is True
    kwargs = orchestrator.compress_mid_execution.call_args.kwargs
    sent = kwargs["current_conversation"]
    points = sent["compression_metadata"]["compression_points"]
    assert sent["compression_metadata"]["is_compressed"] is True
    # The summary the system prompt carries is what the compressor builds on...
    assert points[-1]["compressed_summary"] == PRIOR
    # ...and it predates every synthetic query, so all of them are "new".
    assert points[-1]["query_index"] == -1
    # The persisted point must index the DATABASE conversation, not the
    # shortened synthetic list.
    assert kwargs["persist_query_index"] == 19


@pytest.mark.unit
def test_db_path_without_a_summary_in_play_sends_no_carried_point():
    agent = _agent()
    agent.compressed_summary = None
    db_conversation = {"queries": [{"prompt": "q0", "response": "r"}]}
    synthetic = {"queries": [{"prompt": "q0", "response": ""}],
                 "compression_metadata": {"is_compressed": False, "compression_points": []}}

    _, orchestrator = _run_with(_Handler(), agent, _result(), db_conversation, synthetic)

    sent = orchestrator.compress_mid_execution.call_args.kwargs["current_conversation"]
    assert sent["compression_metadata"]["compression_points"] == []


@pytest.mark.unit
def test_in_memory_path_carries_the_current_summary():
    agent = _agent()
    agent.compressed_summary = PRIOR
    agent.decoded_token = {"sub": "user1"}
    metadata = Mock()
    metadata.compressed_token_count = 10
    metadata.original_token_count = 100
    metadata.compression_ratio = 10.0
    metadata.timestamp = "2026-09-03T10:00:00+00:00"
    metadata.to_dict.return_value = {"query_index": 1, "compressed_summary": "new", "compressed_token_count": 10}
    svc = Mock()
    svc.compress_conversation.return_value = metadata
    svc.get_compressed_context.return_value = ("new", [])
    handler = _Handler()
    with patch("application.api.answer.services.compression.service.CompressionService", return_value=svc), patch(
        "application.llm.llm_creator.LLMCreator"
    ), patch("application.core.model_utils.get_provider_from_model_id", return_value="openai"), patch(
        "application.core.model_utils.get_api_key_for_provider", return_value="sk"
    ), patch.object(
        handler, "_build_conversation_from_messages",
        return_value={"queries": [{"prompt": "q", "response": "r"}, {"prompt": "q2", "response": ""}],
                      "compression_metadata": {"is_compressed": False, "compression_points": []}},
    ), patch.object(handler, "_rebuild_messages_after_compression", return_value=[{"role": "system", "content": "x"}]):
        success, _ = handler._perform_in_memory_compression(agent, [{"role": "user", "content": "hi"}])

    assert success is True
    sent = svc.compress_conversation.call_args[0][0]
    assert sent["compression_metadata"]["compression_points"][-1]["compressed_summary"] == PRIOR
