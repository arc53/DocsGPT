"""Compression must stick: a saved summary is applied on every later turn,
re-compression only summarises the tail, an empty summary is a failure, and
the visible ``[Context Compression Summary]`` rows are never replayed.

Background (prod + OSS reproduction, 2026-09-01/03): the turn-start path
returned the full raw history whenever the conversation was under the
threshold, so a summary was used exactly once; over the threshold it
re-summarised everything from query 0 on every turn (14-24 s each); one
conversation was "compressed" to a 0-token summary and carried on with
nothing.
"""

from unittest.mock import MagicMock, patch

import pytest

from application.api.answer.services.compression import CompressionService
from application.api.answer.services.compression.orchestrator import (
    CompressionOrchestrator,
)
from application.api.answer.services.compression.threshold_checker import (
    CompressionThresholdChecker,
)
from application.api.answer.services.compression.token_counter import TokenCounter
from application.api.answer.services.compression.types import CompressionResult
from application.api.answer.services.conversation_service import (
    COMPRESSION_SUMMARY_PROMPT,
)

EPOCH = "2026-09-03T09:00:00+00:00"
POINT = {
    "timestamp": EPOCH,
    "query_index": 1,
    "compressed_summary": "S",
    "original_token_count": 900,
    "compressed_token_count": 5,
    "compression_ratio": 180.0,
    "model_used": "m",
    "compression_prompt_version": "v1.0",
}


def _compressed_conversation():
    big = "word " * 600
    return {
        "queries": [
            {"prompt": "q0", "response": big},
            {"prompt": "q1", "response": big},
            {"prompt": "q2", "response": "r2"},
            {"prompt": "q3", "response": "r3"},
        ],
        "compression_metadata": {
            "is_compressed": True,
            "last_compression_at": EPOCH,
            "compression_points": [POINT],
        },
        "agent_id": "agent-1",
    }


@pytest.fixture
def conversation_service():
    return MagicMock()


@pytest.fixture
def threshold_checker():
    return MagicMock()


@pytest.fixture
def orchestrator(conversation_service, threshold_checker):
    return CompressionOrchestrator(
        conversation_service=conversation_service, threshold_checker=threshold_checker
    )


@pytest.mark.unit
class TestTurnStartReuse:
    def test_under_threshold_returns_existing_summary_and_recent(
        self, orchestrator, conversation_service, threshold_checker
    ):
        conversation_service.get_conversation.return_value = _compressed_conversation()
        threshold_checker.should_compress.return_value = False

        result = orchestrator.compress_if_needed("conv1", "user1", "m", {"sub": "user1"})

        assert result.success is True
        assert result.compression_performed is False
        assert result.compressed_summary == "S"
        assert [q["prompt"] for q in result.recent_queries] == ["q2", "q3"]
        assert result.last_compression_at == EPOCH

    def test_uncompressed_under_threshold_returns_full_history(
        self, orchestrator, conversation_service, threshold_checker
    ):
        conv = _compressed_conversation()
        conv["compression_metadata"] = {}
        conversation_service.get_conversation.return_value = conv
        threshold_checker.should_compress.return_value = False

        result = orchestrator.compress_if_needed("conv1", "user1", "m", {"sub": "user1"})

        assert result.compressed_summary is None
        assert len(result.recent_queries) == 4
        assert result.last_compression_at is None

    @patch(
        "application.api.answer.services.compression.orchestrator.get_provider_from_model_id",
        return_value="openai",
    )
    @patch(
        "application.api.answer.services.compression.orchestrator.get_api_key_for_provider",
        return_value="sk",
    )
    @patch("application.api.answer.services.compression.orchestrator.LLMCreator")
    @patch("application.api.answer.services.compression.orchestrator.CompressionService")
    @patch("application.api.answer.services.compression.orchestrator.settings")
    def test_over_threshold_compresses_only_the_tail(
        self,
        mock_settings,
        MockCompressionService,
        MockLLMCreator,
        _key,
        _provider,
        orchestrator,
        conversation_service,
        threshold_checker,
    ):
        mock_settings.COMPRESSION_MODEL_OVERRIDE = None
        conversation = _compressed_conversation()
        conversation_service.get_conversation.return_value = conversation
        threshold_checker.should_compress.return_value = True
        MockLLMCreator.create_llm.return_value = MagicMock()
        metadata = MagicMock()
        metadata.compression_ratio = 3.0
        metadata.original_token_count = 30
        metadata.compressed_token_count = 10
        metadata.timestamp = "2026-09-03T10:00:00+00:00"
        svc = MagicMock()
        svc.compress_and_save.return_value = metadata
        svc.get_compressed_context.return_value = ("S2", [])
        MockCompressionService.return_value = svc

        result = orchestrator.compress_if_needed("conv1", "user1", "m", {"sub": "user1"})

        assert result.success and result.compression_performed
        args, kwargs = svc.compress_and_save.call_args
        # queries 0-1 are already inside point 1; only 2-3 are new.
        start_index = kwargs.get("start_index", args[3] if len(args) > 3 else 0)
        assert start_index == 2
        assert (kwargs.get("compress_up_to_index") or args[2]) == 3


@pytest.mark.unit
class TestEffectiveTokenCount:
    def test_counts_summary_plus_recent_only(self):
        conv = _compressed_conversation()
        effective = TokenCounter.count_effective_conversation_tokens(conv)
        raw = TokenCounter.count_conversation_tokens(conv)
        expected = TokenCounter.count_message_tokens([{"content": "S"}]) + (
            TokenCounter.count_query_tokens(conv["queries"][2:])
        )
        assert effective == expected
        assert effective < raw

    def test_uncompressed_conversation_counts_everything(self):
        conv = _compressed_conversation()
        conv["compression_metadata"] = None
        assert TokenCounter.count_effective_conversation_tokens(conv) == (
            TokenCounter.count_conversation_tokens(conv)
        )

    @patch(
        "application.api.answer.services.compression.threshold_checker.get_token_limit",
        return_value=1000,
    )
    def test_should_compress_uses_effective_count(self, _limit):
        checker = CompressionThresholdChecker(threshold_percentage=0.8)
        conv = _compressed_conversation()
        # Raw history is ~1.2k tokens (over 800); summary + tail is tiny.
        assert TokenCounter.count_conversation_tokens(conv) > 800
        assert checker.should_compress(conv, "m", current_query_tokens=10) is False


@pytest.mark.unit
class TestServiceIncremental:
    def _service(self, summary_text="<summary>new</summary>"):
        llm = MagicMock()
        llm.gen.return_value = summary_text
        svc = CompressionService(llm=llm, model_id="m")
        svc.prompt_builder = MagicMock(version="v1.0")
        svc.prompt_builder.build_prompt.return_value = [{"role": "user", "content": "p"}]
        return svc

    def test_compress_conversation_tail_only(self):
        svc = self._service()
        conv = _compressed_conversation()

        metadata = svc.compress_conversation(conv, compress_up_to_index=3, start_index=2)

        queries, existing = svc.prompt_builder.build_prompt.call_args[0]
        assert [q["prompt"] for q in queries] == ["q2", "q3"]
        assert existing == [POINT]
        assert metadata.query_index == 3
        assert metadata.compressed_summary == "new"

    def test_nothing_new_since_last_point_is_rejected(self):
        svc = self._service()
        with pytest.raises(ValueError):
            svc.compress_conversation(
                _compressed_conversation(), compress_up_to_index=1, start_index=2
            )

    def test_empty_summary_raises(self):
        svc = self._service("<summary>   </summary>")
        with pytest.raises(ValueError):
            svc.compress_conversation(_compressed_conversation(), compress_up_to_index=3)

    def test_get_compressed_context_skips_summary_rows(self):
        svc = CompressionService(llm=None, model_id="m")
        conv = _compressed_conversation()
        conv["queries"].insert(2, {"prompt": COMPRESSION_SUMMARY_PROMPT, "response": "S"})
        summary, recent = svc.get_compressed_context(conv)
        assert summary == "S"
        assert [q["prompt"] for q in recent] == ["q2", "q3"]


@pytest.mark.unit
class TestHistoryHelpers:
    def test_as_history_skips_summary_rows(self):
        result = CompressionResult.success_no_compression(
            [
                {"prompt": "q", "response": "r"},
                {"prompt": COMPRESSION_SUMMARY_PROMPT, "response": "S"},
            ]
        )
        assert [h["prompt"] for h in result.as_history()] == ["q"]

    def test_success_from_existing(self):
        result = CompressionResult.success_from_existing(
            "S", [{"prompt": "q", "response": "r"}], last_compression_at=EPOCH
        )
        assert result.success and not result.compression_performed
        assert result.compressed_summary == "S"
        assert result.last_compression_at == EPOCH


@pytest.mark.unit
class TestSummaryRowMarker:
    """The visible summary row is recognised by its persisted marker; a user
    who types the label text as a question keeps that turn."""

    def test_marked_row_is_a_summary_row(self):
        from application.api.answer.services.compression.types import (
            COMPRESSION_SUMMARY_MARKER,
            is_compression_summary_row,
        )

        row = {"prompt": "anything", "response": "S", "metadata": {COMPRESSION_SUMMARY_MARKER: True}}
        assert is_compression_summary_row(row) is True

    def test_legacy_row_without_metadata_is_a_summary_row(self):
        from application.api.answer.services.compression.types import is_compression_summary_row

        assert is_compression_summary_row({"prompt": COMPRESSION_SUMMARY_PROMPT, "response": "S"}) is True
        assert is_compression_summary_row(
            {"prompt": COMPRESSION_SUMMARY_PROMPT, "response": "S", "metadata": {}}
        ) is True

    def test_user_turn_with_the_label_text_is_kept(self):
        from application.api.answer.services.compression.types import is_compression_summary_row

        real_turn = {
            "prompt": COMPRESSION_SUMMARY_PROMPT,
            "response": "an answer",
            "metadata": {"usage": {"prompt_tokens": 10}, "response_id": "resp_1"},
        }
        assert is_compression_summary_row(real_turn) is False
        with_tools = {"prompt": COMPRESSION_SUMMARY_PROMPT, "response": "r", "tool_calls": [{"tool_name": "x"}]}
        assert is_compression_summary_row(with_tools) is False
        result = CompressionResult.success_no_compression([real_turn])
        assert [h["prompt"] for h in result.as_history()] == [COMPRESSION_SUMMARY_PROMPT]


@pytest.mark.unit
class TestIncrementalTailExcludesSummaryRows:
    def test_compress_conversation_skips_the_summary_row_in_the_tail(self):
        llm = MagicMock()
        llm.gen.return_value = "<summary>new</summary>"
        svc = CompressionService(llm=llm, model_id="m")
        svc.prompt_builder = MagicMock(version="v1.0")
        svc.prompt_builder.build_prompt.return_value = [{"role": "user", "content": "p"}]
        conv = _compressed_conversation()
        # A mid-execution compression appends its visible row right after the point.
        conv["queries"].insert(2, {"prompt": COMPRESSION_SUMMARY_PROMPT, "response": "S"})

        svc.compress_conversation(conv, compress_up_to_index=4, start_index=2)

        queries, existing = svc.prompt_builder.build_prompt.call_args[0]
        assert [q["prompt"] for q in queries] == ["q2", "q3"]
        assert existing == [POINT]

    def test_only_summary_rows_since_the_point_is_rejected(self):
        svc = CompressionService(llm=MagicMock(), model_id="m")
        conv = _compressed_conversation()
        conv["queries"] = conv["queries"][:2] + [{"prompt": COMPRESSION_SUMMARY_PROMPT, "response": "S"}]
        with pytest.raises(ValueError, match="Nothing to compress"):
            svc.compress_conversation(conv, compress_up_to_index=2, start_index=2)

    @patch(
        "application.api.answer.services.compression.orchestrator.get_provider_from_model_id",
        return_value="openai",
    )
    @patch(
        "application.api.answer.services.compression.orchestrator.get_api_key_for_provider",
        return_value="sk",
    )
    @patch("application.api.answer.services.compression.orchestrator.LLMCreator")
    @patch("application.api.answer.services.compression.orchestrator.CompressionService")
    @patch("application.api.answer.services.compression.orchestrator.settings")
    def test_orchestrator_reuses_summary_when_only_summary_rows_follow_the_point(
        self, mock_settings, MockCompressionService, MockLLMCreator, _key, _provider,
        orchestrator, conversation_service, threshold_checker,
    ):
        mock_settings.COMPRESSION_MODEL_OVERRIDE = None
        conv = _compressed_conversation()
        conv["queries"] = conv["queries"][:2] + [{"prompt": COMPRESSION_SUMMARY_PROMPT, "response": "S"}]
        conversation_service.get_conversation.return_value = conv
        threshold_checker.should_compress.return_value = True
        MockLLMCreator.create_llm.return_value = MagicMock()
        svc = MagicMock()
        svc.get_compressed_context.return_value = ("S", [])
        MockCompressionService.return_value = svc

        result = orchestrator.compress_if_needed("conv1", "user1", "m", {"sub": "user1"})

        assert result.success and not result.compression_performed
        assert result.compressed_summary == "S"
        svc.compress_and_save.assert_not_called()


@pytest.mark.unit
class TestAbsolutePersistIndex:
    def test_compress_conversation_persists_the_given_absolute_index(self):
        llm = MagicMock()
        llm.gen.return_value = "<summary>new</summary>"
        svc = CompressionService(llm=llm, model_id="m")
        svc.prompt_builder = MagicMock(version="v1.0")
        svc.prompt_builder.build_prompt.return_value = [{"role": "user", "content": "p"}]
        conv = {"queries": [{"prompt": "q18", "response": "r"}, {"prompt": "q19", "response": ""}]}

        metadata = svc.compress_conversation(conv, compress_up_to_index=1, persist_query_index=19)

        assert metadata.query_index == 19

    @patch(
        "application.api.answer.services.compression.orchestrator.get_provider_from_model_id",
        return_value="openai",
    )
    @patch(
        "application.api.answer.services.compression.orchestrator.get_api_key_for_provider",
        return_value="sk",
    )
    @patch("application.api.answer.services.compression.orchestrator.LLMCreator")
    @patch("application.api.answer.services.compression.orchestrator.CompressionService")
    @patch("application.api.answer.services.compression.orchestrator.settings")
    def test_mid_execution_builds_on_the_carried_summary_and_persists_the_absolute_index(
        self, mock_settings, MockCompressionService, MockLLMCreator, _key, _provider,
        orchestrator, conversation_service,
    ):
        mock_settings.COMPRESSION_MODEL_OVERRIDE = None
        MockLLMCreator.create_llm.return_value = MagicMock()
        metadata = MagicMock()
        metadata.compression_ratio = 3.0
        metadata.original_token_count = 30
        metadata.compressed_token_count = 10
        metadata.timestamp = "2026-09-03T10:00:00+00:00"
        svc = MagicMock()
        svc.compress_and_save.return_value = metadata
        svc.get_compressed_context.return_value = ("new", [])
        MockCompressionService.return_value = svc
        conversation_service.get_conversation.return_value = {"queries": [], "compression_metadata": {}}
        synthetic = {
            "queries": [{"prompt": "q18", "response": "r"}, {"prompt": "q19", "response": ""}],
            "compression_metadata": {
                "is_compressed": True,
                "compression_points": [{"query_index": -1, "compressed_summary": "prior",
                                        "compressed_token_count": 5, "original_token_count": 5}],
            },
        }

        result = orchestrator.compress_mid_execution(
            "conv1", "user1", "m", {"sub": "user1"}, current_conversation=synthetic,
            persist_query_index=19,
        )

        assert result.success and result.compression_performed
        args, kwargs = svc.compress_and_save.call_args
        assert kwargs["start_index"] == 0          # every synthetic query is newer than the summary
        assert kwargs["persist_query_index"] == 19  # indexed against the database conversation


@pytest.mark.unit
class TestUnusableSavedPoints:
    """A saved point with an empty summary (older versions wrote them) must
    never make a turn drop history."""

    def _conversation_with_empty_point(self):
        return {
            "queries": [
                {"prompt": "q0", "response": "first saved turn"},
                {"prompt": "q1", "response": "second saved turn"},
            ],
            "compression_metadata": {
                "is_compressed": True,
                "last_compression_at": EPOCH,
                "compression_points": [{
                    "timestamp": EPOCH, "query_index": 1, "compressed_summary": "",
                    "original_token_count": 493541, "compressed_token_count": 0,
                }],
            },
            "agent_id": "agent-1",
        }

    def test_reuse_ignores_an_empty_point_and_keeps_history(
        self, orchestrator, conversation_service, threshold_checker
    ):
        conversation_service.get_conversation.return_value = self._conversation_with_empty_point()
        threshold_checker.should_compress.return_value = False

        result = orchestrator.compress_if_needed("conv1", "user1", "m", {"sub": "user1"})

        assert result.success is True
        assert result.compressed_summary is None
        assert [q["prompt"] for q in result.recent_queries] == ["q0", "q1"]
        assert [h["prompt"] for h in result.as_history()] == ["q0", "q1"]

    def test_effective_count_ignores_an_empty_point(self):
        conv = self._conversation_with_empty_point()
        assert TokenCounter.count_effective_conversation_tokens(conv) == (
            TokenCounter.count_conversation_tokens(conv)
        )

    def test_get_compressed_context_ignores_an_empty_point(self):
        summary, recent = CompressionService(llm=None, model_id="m").get_compressed_context(
            self._conversation_with_empty_point()
        )
        assert summary is None
        assert [q["prompt"] for q in recent] == ["q0", "q1"]

    def test_get_compressed_context_falls_back_to_the_latest_usable_point(self):
        conv = _compressed_conversation()
        conv["queries"].append({"prompt": "q4", "response": "r4"})
        conv["compression_metadata"]["compression_points"].append(
            {"timestamp": "2026-09-04T09:00:00+00:00", "query_index": 3,
             "compressed_summary": "   ", "compressed_token_count": 0}
        )
        summary, recent = CompressionService(llm=None, model_id="m").get_compressed_context(conv)
        assert summary == "S"
        assert [q["prompt"] for q in recent] == ["q2", "q3", "q4"]

    @patch(
        "application.api.answer.services.compression.orchestrator.get_provider_from_model_id",
        return_value="openai",
    )
    @patch(
        "application.api.answer.services.compression.orchestrator.get_api_key_for_provider",
        return_value="sk",
    )
    @patch("application.api.answer.services.compression.orchestrator.LLMCreator")
    @patch("application.api.answer.services.compression.orchestrator.CompressionService")
    @patch("application.api.answer.services.compression.orchestrator.settings")
    def test_recompression_starts_after_the_latest_usable_point(
        self, mock_settings, MockCompressionService, MockLLMCreator, _key, _provider,
        orchestrator, conversation_service, threshold_checker,
    ):
        mock_settings.COMPRESSION_MODEL_OVERRIDE = None
        conv = _compressed_conversation()
        conv["queries"].append({"prompt": "q4", "response": "r4"})
        conv["compression_metadata"]["compression_points"].append(
            {"timestamp": "2026-09-04T09:00:00+00:00", "query_index": 3,
             "compressed_summary": "", "compressed_token_count": 0}
        )
        conversation_service.get_conversation.return_value = conv
        threshold_checker.should_compress.return_value = True
        MockLLMCreator.create_llm.return_value = MagicMock()
        metadata = MagicMock()
        metadata.compression_ratio = 3.0
        metadata.original_token_count = 30
        metadata.compressed_token_count = 10
        metadata.timestamp = "2026-09-05T10:00:00+00:00"
        svc = MagicMock()
        svc.compress_and_save.return_value = metadata
        svc.get_compressed_context.return_value = ("S2", [])
        MockCompressionService.return_value = svc

        result = orchestrator.compress_if_needed("conv1", "user1", "m", {"sub": "user1"})

        assert result.compression_performed
        assert svc.compress_and_save.call_args.kwargs["start_index"] == 2


@pytest.mark.unit
class TestUsablePointPredicates:
    """Each rejection predicate of ``is_usable_compression_point`` on its own."""

    def _with_later_point(self, **point):
        conv = _compressed_conversation()
        conv["queries"].append({"prompt": "q4", "response": "r4"})
        conv["compression_metadata"]["compression_points"].append(
            {"timestamp": "2026-09-04T09:00:00+00:00", "query_index": 3, **point}
        )
        return conv

    def test_a_positive_count_does_not_rescue_a_blank_summary(self):
        conv = self._with_later_point(compressed_summary="   ", compressed_token_count=12)
        summary, recent = CompressionService(llm=None, model_id="m").get_compressed_context(conv)
        assert summary == "S"
        assert [q["prompt"] for q in recent] == ["q2", "q3", "q4"]

    def test_a_zero_count_does_not_rescue_a_non_blank_summary(self):
        conv = self._with_later_point(compressed_summary="newer", compressed_token_count=0)
        summary, recent = CompressionService(llm=None, model_id="m").get_compressed_context(conv)
        assert summary == "S"
        assert [q["prompt"] for q in recent] == ["q2", "q3", "q4"]

    def test_a_missing_count_with_a_summary_is_usable(self):
        conv = self._with_later_point(compressed_summary="newer")
        summary, recent = CompressionService(llm=None, model_id="m").get_compressed_context(conv)
        assert summary == "newer"
        assert [q["prompt"] for q in recent] == ["q4"]
