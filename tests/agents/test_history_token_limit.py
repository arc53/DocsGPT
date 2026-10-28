"""``agents.config.history_token_limit``: summarize older messages once recent history passes it."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from docsgpt.api.user.agents.routes import _policy_changed, normalize_agent_config
from docsgpt.guardrails.config import (
    MAX_CONTEXT_WINDOW_LIMIT,
    MIN_HISTORY_TOKEN_LIMIT,
    AgentConfig,
    history_token_limit_of,
)

WINDOW = 200000
HISTORY = 8000


def _words(count: int) -> str:
    return "word " * count


def _turn(tokens: int) -> dict:
    return {"prompt": _words(tokens), "response": ""}


# ── the config field ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestConfigField:
    def test_defaults_to_none(self):
        assert AgentConfig().history_token_limit is None
        assert normalize_agent_config({})["history_token_limit"] is None

    def test_a_valid_limit_round_trips(self):
        assert normalize_agent_config({"history_token_limit": HISTORY})["history_token_limit"] == HISTORY

    def test_null_clears_it(self):
        assert normalize_agent_config({"history_token_limit": None})["history_token_limit"] is None

    @pytest.mark.parametrize("value", [MIN_HISTORY_TOKEN_LIMIT - 1, 0, -5, MAX_CONTEXT_WINDOW_LIMIT + 1])
    def test_out_of_range_is_rejected_on_write(self, value):
        with pytest.raises(ValueError, match="history_token_limit"):
            normalize_agent_config({"history_token_limit": value})

    def test_a_bool_is_rejected(self):
        with pytest.raises(ValueError):
            normalize_agent_config({"history_token_limit": True})

    @pytest.mark.parametrize("history", [32000, 40000])
    def test_must_stay_below_the_context_limit(self, history):
        with pytest.raises(ValueError, match="history_token_limit"):
            normalize_agent_config({"context_window_limit": 32000, "history_token_limit": history})

    def test_below_the_context_limit_is_accepted(self):
        config = normalize_agent_config({"context_window_limit": 32000, "history_token_limit": 31999})
        assert config["history_token_limit"] == 31999

    def test_lenient_read_drops_a_bad_limit_and_keeps_the_rest(self):
        parsed = AgentConfig.parse({"history_token_limit": 10, "context_window_limit": 32000})
        assert parsed.history_token_limit is None
        assert parsed.context_window_limit == 32000

    def test_lenient_read_keeps_a_good_limit_next_to_a_bad_block(self):
        parsed = AgentConfig.parse({"history_token_limit": HISTORY, "guardrails": {"mode": "bogus"}})
        assert parsed.history_token_limit == HISTORY

    @pytest.mark.parametrize("history", [32000, 40000])
    def test_lenient_read_drops_a_limit_not_below_the_context_limit(self, history):
        # A row the write path would reject (a manual edit) must not break a stream.
        parsed = AgentConfig.parse({"context_window_limit": 32000, "history_token_limit": history})
        assert parsed.history_token_limit is None
        assert parsed.context_window_limit == 32000

    def test_changing_it_is_a_policy_change(self):
        assert _policy_changed({"config": {}}, {"config": {"history_token_limit": HISTORY}})


@pytest.mark.unit
class TestReadLimit:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, None),
            ({}, None),
            ("nope", None),
            ({"history_token_limit": HISTORY}, HISTORY),
            ({"history_token_limit": 5}, None),
            ({"history_token_limit": "abc"}, None),
            ({"history_token_limit": True}, None),
            ({"history_token_limit": HISTORY, "guardrails": {"mode": "bogus"}}, HISTORY),
            ({"history_token_limit": HISTORY, "context_window_limit": 32000}, HISTORY),
            ({"history_token_limit": 32000, "context_window_limit": 32000}, None),
            ({"history_token_limit": 40000, "context_window_limit": 32000}, None),
        ],
    )
    def test_reads_only_a_valid_limit(self, raw, expected):
        assert history_token_limit_of(raw) == expected


# ── the threshold ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestHistoryOverLimit:
    def _checker(self):
        from docsgpt.api.answer.services.compression.threshold_checker import CompressionThresholdChecker

        return CompressionThresholdChecker(threshold_percentage=0.8)

    def test_off_without_a_limit(self):
        conversation = {"queries": [_turn(HISTORY * 2)]}
        assert self._checker().history_over_limit(conversation, "m", None) is False

    def test_trips_at_the_limit(self):
        assert self._checker().history_over_limit({"queries": [_turn(HISTORY + 100)]}, "m", HISTORY) is True
        assert self._checker().history_over_limit({"queries": [_turn(HISTORY - 500)]}, "m", HISTORY) is False

    def test_counts_only_messages_after_the_summary(self):
        # A summary larger than the limit must not compress every turn.
        conversation = {
            "queries": [_turn(HISTORY), _turn(HISTORY), _turn(500)],
            "compression_metadata": {
                "is_compressed": True,
                "compression_points": [
                    {"query_index": 1, "compressed_summary": _words(HISTORY * 2)},
                ],
            },
        }
        assert self._checker().history_over_limit(conversation, "m", HISTORY) is False


# ── the orchestrator ─────────────────────────────────────────────────────────


@pytest.fixture
def orchestrator():
    from docsgpt.api.answer.services.compression.orchestrator import CompressionOrchestrator

    return CompressionOrchestrator(conversation_service=MagicMock(), threshold_checker=MagicMock())


@pytest.mark.unit
class TestCompressIfNeeded:
    def _run(self, orchestrator, conversation, *, window_full: bool, history_full: bool):
        orchestrator.conversation_service.get_conversation.return_value = conversation
        orchestrator.threshold_checker.should_compress.return_value = window_full
        orchestrator.threshold_checker.history_over_limit.return_value = history_full
        with patch.object(orchestrator, "_perform_compression") as perform:
            orchestrator.compress_if_needed("c", "u", "m", {}, history_token_limit=HISTORY)
        return perform

    def test_history_past_the_limit_keeps_half_of_it_verbatim(self, orchestrator):
        perform = self._run(orchestrator, {"queries": [_turn(1)]}, window_full=False, history_full=True)
        assert perform.call_args.kwargs["keep_recent_tokens"] == HISTORY // 2
        assert orchestrator.threshold_checker.history_over_limit.call_args.args[2] == HISTORY

    def test_a_full_window_compresses_everything(self, orchestrator):
        perform = self._run(orchestrator, {"queries": [_turn(1)]}, window_full=True, history_full=True)
        assert perform.call_args.kwargs.get("keep_recent_tokens") is None

    def test_neither_leaves_history(self, orchestrator):
        perform = self._run(orchestrator, {"queries": [_turn(1)]}, window_full=False, history_full=False)
        perform.assert_not_called()


@pytest.mark.unit
class TestKeepRecent:
    """``_perform_compression`` with ``keep_recent_tokens`` leaves the newest turns out of the summary."""

    def _compress(self, orchestrator, conversation, keep, responses_api=False):
        service = MagicMock()
        service.compress_and_save.return_value = MagicMock(
            compression_ratio=2.0, original_token_count=2, compressed_token_count=1
        )
        service.get_compressed_context.return_value = ("summary", [])
        orchestrator.conversation_service.get_conversation.return_value = conversation
        module = "docsgpt.api.answer.services.compression.orchestrator"
        with patch(f"{module}.CompressionService", return_value=service), \
                patch(f"{module}.LLMCreator"), \
                patch(f"{module}.get_provider_from_model_id", return_value="openai"), \
                patch(f"{module}.get_api_key_for_provider", return_value="k"), \
                patch(f"{module}.uses_responses_api", return_value=responses_api):
            result = orchestrator._perform_compression(
                "c", conversation, "m", {"sub": "u"}, user_id="u", keep_recent_tokens=keep
            )
        assert result.success
        return service.compress_and_save.call_args

    def test_newest_turns_within_the_budget_stay(self, orchestrator):
        conversation = {"queries": [_turn(3000), _turn(3000), _turn(1500), _turn(1500)]}
        call = self._compress(orchestrator, conversation, keep=4000)
        # The last two turns (3,000 tokens) fit in 4,000; the third would not.
        assert call.args[2] == 1

    def test_without_a_budget_everything_is_compressed(self, orchestrator):
        conversation = {"queries": [_turn(3000), _turn(3000), _turn(1500)]}
        assert self._compress(orchestrator, conversation, keep=None).args[2] == 2

    def test_a_last_turn_over_the_budget_is_compressed_too(self, orchestrator):
        conversation = {"queries": [_turn(3000), _turn(9000)]}
        assert self._compress(orchestrator, conversation, keep=4000).args[2] == 1

    def test_starts_after_the_previous_point(self, orchestrator):
        conversation = {
            "queries": [_turn(3000), _turn(3000), _turn(3000), _turn(1000), _turn(1000)],
            "compression_metadata": {
                "is_compressed": True,
                "compression_points": [{"query_index": 1, "compressed_summary": "earlier"}],
            },
        }
        call = self._compress(orchestrator, conversation, keep=4000)
        assert call.args[2] == 2
        assert call.kwargs["start_index"] == 2

    def test_responses_reasoning_counts_toward_the_budget(self, orchestrator):
        # The trigger counts replayed reasoning, so the kept turns must too, or
        # they measure under the budget and trip the limit again next turn.
        conversation = {"queries": [_turn(3000), _turn(1500), _turn(1500)]}
        with patch(
            "docsgpt.api.answer.services.compression.token_counter.TokenCounter.replayed_reasoning_tokens",
            return_value=2000,
        ):
            assert self._compress(orchestrator, conversation, keep=4000).args[2] == 0
            assert self._compress(orchestrator, conversation, keep=4000, responses_api=True).args[2] == 1

    def test_summary_rows_take_no_budget(self, orchestrator):
        from docsgpt.api.answer.services.compression.types import (
            COMPRESSION_SUMMARY_MARKER,
            COMPRESSION_SUMMARY_PROMPT,
        )

        summary_row = {
            "prompt": COMPRESSION_SUMMARY_PROMPT,
            "response": _words(5000),
            "metadata": {COMPRESSION_SUMMARY_MARKER: True},
        }
        conversation = {"queries": [_turn(3000), summary_row, _turn(1500), _turn(1500)]}
        call = self._compress(orchestrator, conversation, keep=4000)
        assert call.args[2] == 1


# ── the stream processor ─────────────────────────────────────────────────────


def _processor(config):
    from docsgpt.api.answer.services.stream_processor import StreamProcessor

    sp = StreamProcessor.__new__(StreamProcessor)
    sp.data = {}
    sp.decoded_token = {"sub": "u"}
    sp.initial_user_id = "u"
    sp.model_id = "m"
    sp.model_user_id = None
    sp.agent_key = None
    sp._agent_data = None
    sp.attachments = []
    sp.earlier_attachments = []
    sp.agent_config = {"config": config}
    return sp


@pytest.mark.unit
class TestStreamProcessor:
    def test_reads_the_agent_limit(self):
        assert _processor({"history_token_limit": HISTORY})._history_token_limit() == HISTORY
        assert _processor({})._history_token_limit() is None
        assert _processor({"history_token_limit": 3})._history_token_limit() is None

    def test_compression_gets_the_limit(self):
        from docsgpt.api.answer.services.compression.types import CompressionResult

        calls = []
        sp = _processor({"history_token_limit": HISTORY})
        sp.compression_orchestrator = type("O", (), {})()
        sp.compression_orchestrator.compress_if_needed = (
            lambda **kw: calls.append(kw) or CompressionResult.failure("x")
        )
        sp.conversation_id = "c"
        with patch.object(sp, "_turn_token_estimate", return_value=10):
            sp._handle_compression({"queries": []})
        assert calls[0]["history_token_limit"] == HISTORY

    @pytest.mark.parametrize(
        "config,expected",
        [
            ({"history_token_limit": HISTORY, "context_window_limit": 32000}, 32000),
            ({"context_window_limit": 32000}, 32000),
            ({}, None),
        ],
    )
    def test_client_history_is_trimmed_to_the_context_limit(self, config, expected):
        sp = _processor(config)
        sp.conversation_id = None
        sp.data = {"history": "[]"}
        with patch.object(sp, "_ensure_turn_fits"), \
                patch.object(sp, "_with_request_earlier_attachments", return_value=[]), \
                patch("docsgpt.api.answer.services.stream_processor.limit_chat_history",
                      return_value=[]) as trim:
            sp._load_conversation_history()
        assert trim.call_args.kwargs["max_token_limit"] == expected

    def _client_history(self, config, turns, responses_api=False):
        import json

        sp = _processor(config)
        sp.conversation_id = None
        sp.data = {"history": json.dumps(turns)}
        with patch.object(sp, "_ensure_turn_fits"), \
                patch.object(sp, "_with_request_earlier_attachments", return_value=[]), \
                patch("docsgpt.api.answer.services.stream_processor.uses_responses_api",
                      return_value=responses_api):
            sp._load_conversation_history()
        return sp.history

    def test_client_history_keeps_the_newest_turns_within_the_history_limit(self):
        turns = [{**_turn(2500), "id": i} for i in range(4)]
        kept = self._client_history({"history_token_limit": HISTORY}, turns)
        assert [t["id"] for t in kept] == [1, 2, 3]

    def test_client_history_counts_thoughts_toward_the_history_limit(self):
        # Thoughts are replayed (reasoning_content), so they take room.
        turns = [{**_turn(2500), "thought": _words(2500), "id": i} for i in range(4)]
        kept = self._client_history({"history_token_limit": HISTORY}, turns)
        assert [t["id"] for t in kept] == [3]

    @pytest.mark.parametrize("responses_api,expected", [(True, [3]), (False, [1, 2, 3])])
    def test_client_history_counts_responses_reasoning_on_that_api(self, responses_api, expected):
        from docsgpt.api.answer.services.compression.token_counter import TokenCounter

        turns = [{**_turn(2500), "id": i} for i in range(4)]
        with patch.object(TokenCounter, "replayed_reasoning_tokens", return_value=3000):
            kept = self._client_history(
                {"history_token_limit": HISTORY}, turns, responses_api=responses_api
            )
        assert [t["id"] for t in kept] == expected

    def test_client_history_without_a_history_limit_is_left_to_the_context_limit(self):
        turns = [{**_turn(2500), "thought": _words(2500), "id": i} for i in range(4)]
        kept = self._client_history({}, turns)
        assert [t["id"] for t in kept] == [0, 1, 2, 3]

    @staticmethod
    def _chained(turns):
        return [
            {**t, "metadata": {"response_id": f"r{t['id']}", "response_chain_key": "k", "usage": {}}}
            for t in turns
        ]

    def test_trimmed_client_history_does_not_chain_onto_the_dropped_turns(self):
        # The provider's stored transcript behind the last response id holds
        # the dropped turns too, so chaining onto it would undo the trim.
        turns = self._chained([{**_turn(2500), "id": i} for i in range(4)])
        kept = self._client_history({"history_token_limit": HISTORY}, turns)
        assert [t["id"] for t in kept] == [1, 2, 3]
        assert "response_id" not in kept[-1]["metadata"]
        assert kept[-1]["metadata"]["response_chain_key"] == "k"

    def test_untrimmed_client_history_still_chains(self):
        turns = self._chained([{**_turn(1000), "id": i} for i in range(3)])
        kept = self._client_history({"history_token_limit": HISTORY}, turns)
        assert kept[-1]["metadata"]["response_id"] == "r2"

    def test_a_context_limit_trim_resets_the_chain_too(self):
        import json

        turns = self._chained([{**_turn(10), "id": i} for i in range(3)])
        sp = _processor({"context_window_limit": 32000})
        sp.conversation_id = None
        sp.data = {"history": json.dumps(turns)}
        with patch.object(sp, "_ensure_turn_fits"), \
                patch.object(sp, "_with_request_earlier_attachments", return_value=[]), \
                patch("docsgpt.api.answer.services.stream_processor.limit_chat_history",
                      return_value=turns[1:]):
            sp._load_conversation_history()
        assert "response_id" not in sp.history[-1]["metadata"]
        # The caller's own turn objects are left as sent.
        assert turns[-1]["metadata"]["response_id"] == "r2"
