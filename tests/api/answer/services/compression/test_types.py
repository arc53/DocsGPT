"""Tests for application/api/answer/services/compression/types.py"""

from datetime import datetime, timezone

import pytest

from application.api.answer.services.compression.types import (
    CompressionMetadata,
    CompressionResult,
)


@pytest.mark.unit
class TestCompressionMetadata:
    def _make_metadata(self, **overrides):
        defaults = dict(
            timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
            query_index=5,
            compressed_summary="Summary of conversation",
            original_token_count=5000,
            compressed_token_count=500,
            compression_ratio=10.0,
            model_used="gpt-4",
            compression_prompt_version="v1.0",
        )
        defaults.update(overrides)
        return CompressionMetadata(**defaults)

    def test_to_dict_contains_all_fields(self):
        meta = self._make_metadata()
        d = meta.to_dict()

        assert d["timestamp"] == datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert d["query_index"] == 5
        assert d["compressed_summary"] == "Summary of conversation"
        assert d["original_token_count"] == 5000
        assert d["compressed_token_count"] == 500
        assert d["compression_ratio"] == 10.0
        assert d["model_used"] == "gpt-4"
        assert d["compression_prompt_version"] == "v1.0"

    def test_to_dict_returns_dict_type(self):
        meta = self._make_metadata()
        assert isinstance(meta.to_dict(), dict)

    def test_to_dict_field_count(self):
        meta = self._make_metadata()
        d = meta.to_dict()
        assert len(d) == 8

    def test_attributes_accessible(self):
        meta = self._make_metadata(query_index=10, compression_ratio=5.5)
        assert meta.query_index == 10
        assert meta.compression_ratio == 5.5

    def test_zero_compressed_tokens(self):
        meta = self._make_metadata(compressed_token_count=0, compression_ratio=0)
        d = meta.to_dict()
        assert d["compressed_token_count"] == 0
        assert d["compression_ratio"] == 0


@pytest.mark.unit
class TestCompressionResult:
    def test_success_with_compression(self):
        meta = CompressionMetadata(
            timestamp=datetime.now(timezone.utc),
            query_index=3,
            compressed_summary="summary",
            original_token_count=1000,
            compressed_token_count=100,
            compression_ratio=10.0,
            model_used="gpt-4",
            compression_prompt_version="v1.0",
        )
        queries = [{"prompt": "q1", "response": "r1"}]
        result = CompressionResult.success_with_compression("summary", queries, meta)

        assert result.success is True
        assert result.compressed_summary == "summary"
        assert result.recent_queries == queries
        assert result.metadata is meta
        assert result.compression_performed is True
        assert result.error is None

    def test_success_no_compression(self):
        queries = [{"prompt": "q1", "response": "r1"}]
        result = CompressionResult.success_no_compression(queries)

        assert result.success is True
        assert result.compressed_summary is None
        assert result.recent_queries == queries
        assert result.metadata is None
        assert result.compression_performed is False
        assert result.error is None

    def test_failure(self):
        result = CompressionResult.failure("something went wrong")

        assert result.success is False
        assert result.error == "something went wrong"
        assert result.compression_performed is False
        assert result.compressed_summary is None
        assert result.recent_queries == []
        assert result.metadata is None

    def test_as_history_extracts_prompt_response(self):
        queries = [
            {"prompt": "Hello", "response": "Hi", "extra": "ignored"},
            {"prompt": "How?", "response": "Fine"},
        ]
        result = CompressionResult.success_no_compression(queries)
        history = result.as_history()

        assert len(history) == 2
        assert history[0] == {"prompt": "Hello", "response": "Hi"}
        assert history[1] == {"prompt": "How?", "response": "Fine"}

    def test_as_history_empty_queries(self):
        result = CompressionResult.success_no_compression([])
        assert result.as_history() == []

    def test_default_recent_queries_is_empty_list(self):
        result = CompressionResult(success=True)
        assert result.recent_queries == []
        assert result.as_history() == []

    def test_success_no_compression_with_empty_list(self):
        result = CompressionResult.success_no_compression([])
        assert result.success is True
        assert result.recent_queries == []
