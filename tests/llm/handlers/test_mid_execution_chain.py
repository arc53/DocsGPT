"""Mid-execution compression must persist one point, write no message row,
break the Responses chain, and treat an empty summary as a failure."""

from typing import Any, Dict, Generator
from unittest.mock import Mock, patch

import pytest

from docsgpt.llm.handlers.base import LLMHandler, LLMResponse, ToolCall


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
        "docsgpt.api.answer.services.compression.CompressionOrchestrator",
        return_value=orchestrator,
    ), patch(
        "docsgpt.api.answer.services.conversation_service.ConversationService",
        return_value=conv_service,
    ), patch.object(
        handler, "_build_conversation_from_messages", return_value={"queries": []}
    ), patch.object(
        handler,
        "_rebuild_messages_after_compression",
        return_value=[{"role": "system", "content": "rebuilt"}],
    ):
        return handler._perform_mid_execution_compression(
            agent, [{"role": "user", "content": "hi"}]
        ), conv_service


@pytest.mark.unit
def test_db_path_persists_once_and_breaks_chain():
    agent = _agent()
    (success, messages), conv_service = _run(_Handler(), agent, _result())

    assert success is True and messages
    # The orchestrator's compress_and_save wrote the point; no summary row
    # goes into the conversation.
    assert [call[0] for call in conv_service.method_calls] == ["get_conversation"]
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
    assert [call[0] for call in conv_service.method_calls] == ["get_conversation"]
    agent.llm.start_responses_turn.assert_not_called()


# ── the summary already in play must survive a mid-execution compression ────


PRIOR = "Original delivery location: Warehouse Seven."


def _run_with(handler, agent, result, db_conversation, synthetic):
    conv_service = Mock()
    conv_service.get_conversation.return_value = db_conversation
    orchestrator = Mock()
    orchestrator.compress_mid_execution.return_value = result
    with patch(
        "docsgpt.api.answer.services.compression.CompressionOrchestrator",
        return_value=orchestrator,
    ), patch(
        "docsgpt.api.answer.services.conversation_service.ConversationService",
        return_value=conv_service,
    ), patch.object(
        handler, "_build_conversation_from_messages", return_value=synthetic
    ), patch.object(
        handler,
        "_rebuild_messages_after_compression",
        return_value=[{"role": "system", "content": "rebuilt"}],
    ):
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
    with patch("docsgpt.api.answer.services.compression.service.CompressionService", return_value=svc), patch(
        "docsgpt.llm.llm_creator.LLMCreator"
    ), patch("docsgpt.core.model_utils.get_provider_from_model_id", return_value="openai"), patch(
        "docsgpt.core.model_utils.get_api_key_for_provider", return_value="sk"
    ), patch.object(
        handler, "_build_conversation_from_messages",
        return_value={"queries": [{"prompt": "q", "response": "r"}, {"prompt": "q2", "response": ""}],
                      "compression_metadata": {"is_compressed": False, "compression_points": []}},
    ), patch.object(handler, "_rebuild_messages_after_compression", return_value=[{"role": "system", "content": "x"}]):
        success, _ = handler._perform_in_memory_compression(agent, [{"role": "user", "content": "hi"}])

    assert success is True
    sent = svc.compress_conversation.call_args[0][0]
    assert sent["compression_metadata"]["compression_points"][-1]["compressed_summary"] == PRIOR


# ── the in-flight turn stays out of the persisted point ─────────────────────


def _settled(n):
    return [{"id": f"m{i}", "prompt": f"q{i}", "response": "r", "status": "complete"} for i in range(n)]


@pytest.mark.unit
def test_point_stops_before_the_reserved_row_of_this_turn():
    agent = _agent()
    agent.compressed_summary = None
    agent.tool_executor.message_id = "m3"
    db_conversation = {"queries": [*_settled(3), {"id": "m3", "prompt": "q3", "response": "", "status": "streaming"}]}
    synthetic = {"queries": [{"prompt": "q2", "response": "r"}, {"prompt": "q3", "response": ""}],
                 "compression_metadata": {"is_compressed": False, "compression_points": []}}

    _, orchestrator = _run_with(_Handler(), agent, _result(), db_conversation, synthetic)

    kwargs = orchestrator.compress_mid_execution.call_args.kwargs
    # The answer of row 3 is not written yet: the next turn must replay it.
    assert kwargs["persist_query_index"] == 2
    assert kwargs["turn_index"] == 3


@pytest.mark.unit
def test_an_unknown_reserved_id_falls_back_to_the_row_status():
    agent = _agent()
    agent.compressed_summary = None
    agent.tool_executor.message_id = None
    db_conversation = {"queries": [*_settled(2), {"id": "m2", "prompt": "q2", "response": "", "status": "pending"}]}
    synthetic = {"queries": [{"prompt": "q2", "response": ""}, {"prompt": "x", "response": "y"}],
                 "compression_metadata": {"is_compressed": False, "compression_points": []}}

    _, orchestrator = _run_with(_Handler(), agent, _result(), db_conversation, synthetic)

    kwargs = orchestrator.compress_mid_execution.call_args.kwargs
    assert kwargs["persist_query_index"] == 1
    assert kwargs["turn_index"] == 2


@pytest.mark.unit
def test_first_turn_point_covers_no_saved_row():
    agent = _agent()
    agent.compressed_summary = None
    agent.tool_executor.message_id = "m0"
    db_conversation = {"queries": [{"id": "m0", "prompt": "q0", "response": "", "status": "streaming"}]}
    synthetic = {"queries": [{"prompt": "x", "response": "y"}, {"prompt": "q0", "response": ""}],
                 "compression_metadata": {"is_compressed": False, "compression_points": []}}

    _, orchestrator = _run_with(_Handler(), agent, _result(), db_conversation, synthetic)

    kwargs = orchestrator.compress_mid_execution.call_args.kwargs
    assert kwargs["persist_query_index"] == -1
    assert kwargs["turn_index"] == 0


@pytest.mark.unit
def test_rebuild_leaves_the_in_flight_row_out_of_the_history():
    agent = _agent()
    agent.compressed_summary = None
    agent.tool_executor.message_id = "m1"
    in_flight = {"id": "m1", "prompt": "q1", "response": "", "status": "streaming"}
    db_conversation = {"queries": [*_settled(1), in_flight]}
    result = _result()
    result.recent_queries = [in_flight]
    conv_service = Mock()
    conv_service.get_conversation.return_value = db_conversation
    orchestrator = Mock()
    orchestrator.compress_mid_execution.return_value = result
    handler = _Handler()
    with patch(
        "docsgpt.api.answer.services.compression.CompressionOrchestrator",
        return_value=orchestrator,
    ), patch(
        "docsgpt.api.answer.services.conversation_service.ConversationService",
        return_value=conv_service,
    ), patch.object(
        handler, "_build_conversation_from_messages",
        return_value={"queries": [{"prompt": "q0", "response": "r"}, {"prompt": "q1", "response": ""}],
                      "compression_metadata": {"is_compressed": False, "compression_points": []}},
    ), patch.object(
        handler, "_rebuild_messages_after_compression",
        return_value=[{"role": "system", "content": "rebuilt"}],
    ) as rebuild:
        success, _ = handler._perform_mid_execution_compression(agent, [{"role": "user", "content": "q1"}])

    assert success is True
    # The turn's own message is restored after the summary; the row must not
    # come back as a history turn too.
    assert rebuild.call_args.args[2] == []


@pytest.mark.unit
def test_a_settled_row_after_the_reserved_row_stays_replayed():
    agent = _agent()
    agent.compressed_summary = None
    agent.tool_executor.message_id = "m2"
    # A scheduled answer was appended while this turn (row 2) still ran.
    db_conversation = {"queries": [*_settled(2), {"id": "m2", "prompt": "q2", "response": "", "status": "streaming"},
                                   {"id": "m3", "prompt": "scheduled", "response": "r", "status": "complete"}]}
    synthetic = {"queries": [{"prompt": "q1", "response": "r"}, {"prompt": "q2", "response": ""}],
                 "compression_metadata": {"is_compressed": False, "compression_points": []}}

    _, orchestrator = _run_with(_Handler(), agent, _result(), db_conversation, synthetic)

    kwargs = orchestrator.compress_mid_execution.call_args.kwargs
    assert kwargs["persist_query_index"] == 1
    assert kwargs["turn_index"] == 2
    assert kwargs["turn_message_id"] == "m2"


@pytest.mark.unit
def test_an_earlier_unanswered_row_is_not_summarized():
    agent = _agent()
    agent.compressed_summary = None
    agent.tool_executor.message_id = "m2"
    # Another tab's turn (row 1) is still being answered.
    db_conversation = {"queries": [*_settled(1), {"id": "m1", "prompt": "q1", "response": "", "status": "pending"},
                                   {"id": "m2", "prompt": "q2", "response": "", "status": "streaming"}]}
    synthetic = {"queries": [{"prompt": "q0", "response": "r"}, {"prompt": "q2", "response": ""}],
                 "compression_metadata": {"is_compressed": False, "compression_points": []}}

    _, orchestrator = _run_with(_Handler(), agent, _result(), db_conversation, synthetic)

    kwargs = orchestrator.compress_mid_execution.call_args.kwargs
    assert kwargs["persist_query_index"] == 0
    assert kwargs["turn_index"] == 2


@pytest.mark.unit
def test_a_conversation_without_rows_puts_the_turn_first():
    agent = _agent()
    agent.compressed_summary = None
    agent.tool_executor.message_id = None
    synthetic = {"queries": [{"prompt": "x", "response": "y"}, {"prompt": "q0", "response": ""}],
                 "compression_metadata": {"is_compressed": False, "compression_points": []}}

    _, orchestrator = _run_with(_Handler(), agent, _result(), {"queries": []}, synthetic)

    kwargs = orchestrator.compress_mid_execution.call_args.kwargs
    assert kwargs["persist_query_index"] == -1
    assert kwargs["turn_index"] == 0


@pytest.mark.unit
def test_a_stale_unanswered_row_does_not_pull_the_point_behind_the_saved_one():
    agent = _agent()
    agent.compressed_summary = PRIOR
    agent.tool_executor.message_id = "m5"
    # Row 1 crashed mid-stream and was never reconciled; later turns went on.
    rows = _settled(5)
    rows[1] = {"id": "m1", "prompt": "q1", "response": "", "status": "streaming"}
    db_conversation = {
        "queries": [*rows, {"id": "m5", "prompt": "q5", "response": "", "status": "streaming"}],
        "compression_metadata": {
            "is_compressed": True,
            "compression_points": [{"query_index": 3, "compressed_summary": PRIOR, "compressed_token_count": 9}],
        },
    }
    synthetic = {"queries": [{"prompt": "q4", "response": "r"}, {"prompt": "q5", "response": ""}],
                 "compression_metadata": {"is_compressed": False, "compression_points": []}}

    _, orchestrator = _run_with(_Handler(), agent, _result(), db_conversation, synthetic)

    kwargs = orchestrator.compress_mid_execution.call_args.kwargs
    # The summary in play already covers rows up to 3; the new one builds on it.
    assert kwargs["persist_query_index"] == 3
    assert kwargs["turn_index"] == 5


@pytest.mark.unit
def test_the_point_stops_where_the_turn_history_stopped_when_it_began():
    agent = _agent()
    agent.compressed_summary = None
    agent.tool_executor.message_id = "m3"
    # Row 1 was still being answered when this turn began, so its answer is in
    # neither the replayed history nor the summary; it has settled since.
    agent.history_bound = 0
    db_conversation = {"queries": [*_settled(3), {"id": "m3", "prompt": "q3", "response": "", "status": "streaming"}]}
    synthetic = {"queries": [{"prompt": "q0", "response": "r"}, {"prompt": "q3", "response": ""}],
                 "compression_metadata": {"is_compressed": False, "compression_points": []}}

    _, orchestrator = _run_with(_Handler(), agent, _result(), db_conversation, synthetic)

    kwargs = orchestrator.compress_mid_execution.call_args.kwargs
    assert kwargs["persist_query_index"] == 0
    assert kwargs["turn_index"] == 3


@pytest.mark.unit
def test_the_point_is_stored_only_for_a_turn_whose_row_is_saved():
    agent = _agent()
    agent.compressed_summary = None
    synthetic = {"queries": [{"prompt": "q0", "response": "r"}, {"prompt": "q1", "response": ""}],
                 "compression_metadata": {"is_compressed": False, "compression_points": []}}

    agent.tool_executor.message_id = "m1"
    saved = {"queries": [*_settled(1), {"id": "m1", "prompt": "q1", "response": "", "status": "streaming"}]}
    _, orchestrator = _run_with(_Handler(), agent, _result(), saved, synthetic)
    assert orchestrator.compress_mid_execution.call_args.kwargs["persist_point"] is True

    # A reservation that failed leaves the turn without a row of its own.
    agent.tool_executor.message_id = "m9"
    _, orchestrator = _run_with(_Handler(), agent, _result(), saved, synthetic)
    assert orchestrator.compress_mid_execution.call_args.kwargs["persist_point"] is False
