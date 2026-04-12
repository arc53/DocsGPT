"""Tests for application/api/answer/services/compression/service.py"""

from unittest.mock import MagicMock, patch

import pytest

from application.api.answer.services.compression.service import CompressionService
from application.api.answer.services.compression.types import CompressionMetadata


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.gen.return_value = "<summary>Compressed summary content</summary>"
    return llm


@pytest.fixture
def mock_conversation_service():
    svc = MagicMock()
    svc.update_compression_metadata = MagicMock()
    return svc


@pytest.fixture
def sample_conversation():
    return {
        "queries": [
            {"prompt": "What is Python?", "response": "A programming language."},
            {"prompt": "Tell me more.", "response": "It's versatile and popular."},
            {
                "prompt": "What about tools?",
                "response": "Python has many tools.",
                "tool_calls": [
                    {
                        "tool_name": "search",
                        "action_name": "web_search",
                        "arguments": {"q": "python tools"},
                        "result": "Found 10 results",
                        "status": "success",
                    }
                ],
            },
        ],
        "compression_metadata": {},
    }


@pytest.mark.unit
class TestCompressionServiceInit:
    @patch("application.api.answer.services.compression.service.settings")
    def test_default_prompt_builder(self, mock_settings, mock_llm):
        mock_settings.COMPRESSION_PROMPT_VERSION = "v1.0"
        with patch(
            "application.api.answer.services.compression.service.CompressionPromptBuilder"
        ):
            svc = CompressionService(llm=mock_llm, model_id="gpt-4")
            assert svc.llm is mock_llm
            assert svc.model_id == "gpt-4"

    def test_custom_prompt_builder(self, mock_llm):
        custom_builder = MagicMock()
        svc = CompressionService(
            llm=mock_llm, model_id="gpt-4", prompt_builder=custom_builder
        )
        assert svc.prompt_builder is custom_builder


@pytest.mark.unit
class TestCompressConversation:
    def test_successful_compression(self, mock_llm, sample_conversation):
        mock_builder = MagicMock()
        mock_builder.build_prompt.return_value = [
            {"role": "system", "content": "Compress"},
            {"role": "user", "content": "Conversation..."},
        ]
        mock_builder.version = "v1.0"

        svc = CompressionService(
            llm=mock_llm, model_id="gpt-4", prompt_builder=mock_builder
        )

        with patch(
            "application.api.answer.services.compression.service.TokenCounter"
        ) as MockTC:
            MockTC.count_query_tokens.return_value = 1000
            MockTC.count_message_tokens.return_value = 100

            result = svc.compress_conversation(sample_conversation, 2)

            assert isinstance(result, CompressionMetadata)
            assert result.query_index == 2
            assert result.compressed_summary == "Compressed summary content"
            assert result.original_token_count == 1000
            assert result.compressed_token_count == 100
            assert result.compression_ratio == 10.0
            assert result.model_used == "gpt-4"
            assert result.compression_prompt_version == "v1.0"

    def test_invalid_index_negative(self, mock_llm, sample_conversation):
        mock_builder = MagicMock()
        mock_builder.version = "v1.0"
        svc = CompressionService(
            llm=mock_llm, model_id="gpt-4", prompt_builder=mock_builder
        )

        with pytest.raises(ValueError, match="Invalid compress_up_to_index"):
            svc.compress_conversation(sample_conversation, -1)

    def test_invalid_index_too_large(self, mock_llm, sample_conversation):
        mock_builder = MagicMock()
        mock_builder.version = "v1.0"
        svc = CompressionService(
            llm=mock_llm, model_id="gpt-4", prompt_builder=mock_builder
        )

        with pytest.raises(ValueError, match="Invalid compress_up_to_index"):
            svc.compress_conversation(sample_conversation, 10)

    def test_with_existing_compressions(self, mock_llm):
        conversation = {
            "queries": [
                {"prompt": "q1", "response": "r1"},
                {"prompt": "q2", "response": "r2"},
            ],
            "compression_metadata": {
                "compression_points": [
                    {
                        "query_index": 0,
                        "compressed_summary": "Previous summary",
                    }
                ]
            },
        }
        mock_builder = MagicMock()
        mock_builder.build_prompt.return_value = [
            {"role": "system", "content": "Compress"},
            {"role": "user", "content": "..."},
        ]
        mock_builder.version = "v1.0"

        svc = CompressionService(
            llm=mock_llm, model_id="gpt-4", prompt_builder=mock_builder
        )

        with patch(
            "application.api.answer.services.compression.service.TokenCounter"
        ) as MockTC:
            MockTC.count_query_tokens.return_value = 500
            MockTC.count_message_tokens.return_value = 50

            result = svc.compress_conversation(conversation, 1)
            assert isinstance(result, CompressionMetadata)
            # Verify existing compressions were passed to prompt builder
            call_args = mock_builder.build_prompt.call_args
            assert call_args[0][1] == [
                {"query_index": 0, "compressed_summary": "Previous summary"}
            ]

    def test_zero_compressed_tokens_ratio(self, mock_llm, sample_conversation):
        mock_builder = MagicMock()
        mock_builder.build_prompt.return_value = [
            {"role": "system", "content": "C"},
            {"role": "user", "content": "..."},
        ]
        mock_builder.version = "v1.0"

        svc = CompressionService(
            llm=mock_llm, model_id="gpt-4", prompt_builder=mock_builder
        )

        with patch(
            "application.api.answer.services.compression.service.TokenCounter"
        ) as MockTC:
            MockTC.count_query_tokens.return_value = 1000
            MockTC.count_message_tokens.return_value = 0

            result = svc.compress_conversation(sample_conversation, 2)
            assert result.compression_ratio == 0

    def test_llm_error_propagates(self, sample_conversation):
        llm = MagicMock()
        llm.gen.side_effect = RuntimeError("LLM error")
        mock_builder = MagicMock()
        mock_builder.build_prompt.return_value = [
            {"role": "system", "content": "C"},
            {"role": "user", "content": "..."},
        ]
        mock_builder.version = "v1.0"

        svc = CompressionService(
            llm=llm, model_id="gpt-4", prompt_builder=mock_builder
        )

        with patch(
            "application.api.answer.services.compression.service.TokenCounter"
        ) as MockTC:
            MockTC.count_query_tokens.return_value = 100
            with pytest.raises(RuntimeError, match="LLM error"):
                svc.compress_conversation(sample_conversation, 2)


@pytest.mark.unit
class TestCompressAndSave:
    def test_saves_metadata_to_db(
        self, mock_llm, mock_conversation_service, sample_conversation
    ):
        mock_builder = MagicMock()
        mock_builder.build_prompt.return_value = [
            {"role": "system", "content": "C"},
            {"role": "user", "content": "..."},
        ]
        mock_builder.version = "v1.0"

        svc = CompressionService(
            llm=mock_llm,
            model_id="gpt-4",
            conversation_service=mock_conversation_service,
            prompt_builder=mock_builder,
        )

        with patch(
            "application.api.answer.services.compression.service.TokenCounter"
        ) as MockTC:
            MockTC.count_query_tokens.return_value = 500
            MockTC.count_message_tokens.return_value = 50

            result = svc.compress_and_save("conv_123", sample_conversation, 2)

            assert isinstance(result, CompressionMetadata)
            mock_conversation_service.update_compression_metadata.assert_called_once_with(
                "conv_123", result.to_dict()
            )

    def test_raises_without_conversation_service(self, mock_llm, sample_conversation):
        mock_builder = MagicMock()
        mock_builder.version = "v1.0"
        svc = CompressionService(
            llm=mock_llm, model_id="gpt-4", prompt_builder=mock_builder
        )

        with pytest.raises(ValueError, match="conversation_service required"):
            svc.compress_and_save("conv_123", sample_conversation, 2)


@pytest.mark.unit
class TestGetCompressedContext:
    def test_no_compression_returns_full_history(self, mock_llm):
        svc = CompressionService(llm=mock_llm, model_id="gpt-4")
        conversation = {
            "queries": [{"prompt": "q1", "response": "r1"}],
            "compression_metadata": {},
        }

        summary, queries = svc.get_compressed_context(conversation)

        assert summary is None
        assert queries == [{"prompt": "q1", "response": "r1"}]

    def test_no_compression_points_returns_full_history(self, mock_llm):
        svc = CompressionService(llm=mock_llm, model_id="gpt-4")
        conversation = {
            "queries": [{"prompt": "q1", "response": "r1"}],
            "compression_metadata": {"is_compressed": True, "compression_points": []},
        }

        summary, queries = svc.get_compressed_context(conversation)
        assert summary is None
        assert len(queries) == 1

    def test_with_compression_returns_summary_and_recent(self, mock_llm):
        svc = CompressionService(llm=mock_llm, model_id="gpt-4")
        conversation = {
            "queries": [
                {"prompt": "q0", "response": "r0"},
                {"prompt": "q1", "response": "r1"},
                {"prompt": "q2", "response": "r2"},
            ],
            "compression_metadata": {
                "is_compressed": True,
                "compression_points": [
                    {
                        "query_index": 1,
                        "compressed_summary": "Summary of q0 and q1",
                        "compressed_token_count": 50,
                        "original_token_count": 500,
                    }
                ],
            },
        }

        summary, queries = svc.get_compressed_context(conversation)

        assert summary == "Summary of q0 and q1"
        assert len(queries) == 1
        assert queries[0]["prompt"] == "q2"

    def test_none_queries_returns_empty(self, mock_llm):
        svc = CompressionService(llm=mock_llm, model_id="gpt-4")
        conversation = {
            "queries": None,
            "compression_metadata": {},
        }

        summary, queries = svc.get_compressed_context(conversation)
        assert summary is None
        assert queries == []

    def test_exception_falls_back_to_full_history(self, mock_llm):
        svc = CompressionService(llm=mock_llm, model_id="gpt-4")
        conversation = {
            "queries": [{"prompt": "q", "response": "r"}],
            "compression_metadata": {
                "is_compressed": True,
                "compression_points": "invalid",  # This will cause an error
            },
        }

        summary, queries = svc.get_compressed_context(conversation)
        assert summary is None
        assert queries == [{"prompt": "q", "response": "r"}]

    def test_exception_with_none_queries_returns_empty(self, mock_llm):
        svc = CompressionService(llm=mock_llm, model_id="gpt-4")
        # Force exception by making compression_points non-iterable
        conversation = {
            "queries": None,
            "compression_metadata": {
                "is_compressed": True,
                "compression_points": "bad",
            },
        }

        summary, queries = svc.get_compressed_context(conversation)
        assert summary is None
        assert queries == []


@pytest.mark.unit
class TestExtractSummary:
    def test_extracts_from_summary_tags(self, mock_llm):
        svc = CompressionService(llm=mock_llm, model_id="gpt-4")
        response = "<analysis>Some analysis</analysis><summary>The actual summary</summary>"
        result = svc._extract_summary(response)
        assert result == "The actual summary"

    def test_removes_analysis_tags_when_no_summary(self, mock_llm):
        svc = CompressionService(llm=mock_llm, model_id="gpt-4")
        response = "<analysis>analysis text</analysis>Raw summary text here"
        result = svc._extract_summary(response)
        assert result == "Raw summary text here"

    def test_returns_full_response_when_no_tags(self, mock_llm):
        svc = CompressionService(llm=mock_llm, model_id="gpt-4")
        response = "Just a plain text response"
        result = svc._extract_summary(response)
        assert result == "Just a plain text response"

    def test_multiline_summary(self, mock_llm):
        svc = CompressionService(llm=mock_llm, model_id="gpt-4")
        response = "<summary>Line 1\nLine 2\nLine 3</summary>"
        result = svc._extract_summary(response)
        assert "Line 1" in result
        assert "Line 3" in result

    def test_strips_whitespace(self, mock_llm):
        svc = CompressionService(llm=mock_llm, model_id="gpt-4")
        response = "<summary>  Trimmed  </summary>"
        result = svc._extract_summary(response)
        assert result == "Trimmed"


@pytest.mark.unit
class TestLogToolCallStats:
    def test_no_tool_calls(self, mock_llm):
        svc = CompressionService(llm=mock_llm, model_id="gpt-4")
        queries = [{"prompt": "q", "response": "r"}]
        # Should not raise
        svc._log_tool_call_stats(queries)

    def test_with_tool_calls(self, mock_llm):
        svc = CompressionService(llm=mock_llm, model_id="gpt-4")
        queries = [
            {
                "prompt": "q",
                "response": "r",
                "tool_calls": [
                    {
                        "tool_name": "search",
                        "action_name": "web",
                        "result": "result text",
                    },
                    {
                        "tool_name": "search",
                        "action_name": "web",
                        "result": "more text",
                    },
                ],
            }
        ]
        # Should not raise - just logs
        svc._log_tool_call_stats(queries)

    def test_empty_queries(self, mock_llm):
        svc = CompressionService(llm=mock_llm, model_id="gpt-4")
        svc._log_tool_call_stats([])

    def test_tool_call_with_none_result(self, mock_llm):
        svc = CompressionService(llm=mock_llm, model_id="gpt-4")
        queries = [
            {
                "prompt": "q",
                "response": "r",
                "tool_calls": [
                    {
                        "tool_name": "t",
                        "action_name": "a",
                        "result": None,
                    }
                ],
            }
        ]
        svc._log_tool_call_stats(queries)
