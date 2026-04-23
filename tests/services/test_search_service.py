"""Unit tests for application/services/search_service.py.

Tests exercise the service function in isolation — AgentsRepository is
stubbed via a patched ``db_readonly`` context manager, and
``VectorCreator.create_vectorstore`` is patched to return a fake
vectorstore. No Flask app context, no real DB, no real embeddings.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from application.services.search_service import (
    InvalidAPIKey,
    SearchFailed,
    _collect_source_ids,
    search,
)


@contextmanager
def _fake_db_readonly(agent_data):
    """Patch ``db_readonly`` so ``AgentsRepository.find_by_key`` returns ``agent_data``."""
    agents_repo = MagicMock()
    agents_repo.find_by_key.return_value = agent_data

    @contextmanager
    def _yield_conn():
        yield MagicMock()

    with patch(
        "application.services.search_service.db_readonly", _yield_conn
    ), patch(
        "application.services.search_service.AgentsRepository",
        return_value=agents_repo,
    ):
        yield


@pytest.mark.unit
class TestCollectSourceIds:
    def test_empty_when_no_sources(self):
        assert _collect_source_ids({}) == []

    def test_returns_extra_source_ids(self):
        agent = {"extra_source_ids": ["s1", "s2"], "source_id": "legacy"}
        assert _collect_source_ids(agent) == ["s1", "s2"]

    def test_falls_back_to_single_source_id(self):
        agent = {"extra_source_ids": [], "source_id": "s1"}
        assert _collect_source_ids(agent) == ["s1"]

    def test_skips_empty_entries_in_extra(self):
        agent = {"extra_source_ids": ["", None, "s1"], "source_id": "fallback"}
        assert _collect_source_ids(agent) == ["s1"]


@pytest.mark.unit
class TestSearchInvalidAPIKey:
    def test_raises_when_key_unknown(self):
        with _fake_db_readonly(None):
            with pytest.raises(InvalidAPIKey):
                search("does-not-exist", "hello", 5)

    def test_raises_search_failed_on_db_error(self):
        @contextmanager
        def _yield_conn():
            yield MagicMock()

        agents_repo = MagicMock()
        agents_repo.find_by_key.side_effect = RuntimeError("db down")

        with patch(
            "application.services.search_service.db_readonly", _yield_conn
        ), patch(
            "application.services.search_service.AgentsRepository",
            return_value=agents_repo,
        ):
            with pytest.raises(SearchFailed):
                search("any-key", "hello", 5)


@pytest.mark.unit
class TestSearchEmptyWhenNoSources:
    def test_returns_empty_when_agent_has_no_sources(self):
        with _fake_db_readonly({"extra_source_ids": [], "source_id": None}):
            assert search("k", "q", 5) == []

    def test_returns_empty_for_zero_chunks_without_db_lookup(self):
        with patch("application.services.search_service.db_readonly") as mock_db:
            assert search("k", "q", 0) == []
        mock_db.assert_not_called()

    def test_returns_empty_for_negative_chunks_without_db_lookup(self):
        with patch("application.services.search_service.db_readonly") as mock_db:
            assert search("k", "q", -1) == []
        mock_db.assert_not_called()


@pytest.mark.unit
class TestSearchResults:
    def test_returns_hit_shape(self):
        agent = {"source_id": "src-1", "extra_source_ids": []}
        fake_vs = MagicMock()
        fake_vs.search.return_value = [
            {
                "text": "Test content",
                "metadata": {"title": "Test Title", "source": "/path/to/doc"},
            }
        ]
        with _fake_db_readonly(agent), patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            return_value=fake_vs,
        ):
            results = search("k", "q", 5)
        assert results == [
            {"text": "Test content", "title": "Test Title", "source": "/path/to/doc"}
        ]

    def test_handles_langchain_document_format(self):
        agent = {"source_id": "src-1", "extra_source_ids": []}
        lc_doc = MagicMock()
        lc_doc.page_content = "Langchain content"
        lc_doc.metadata = {"title": "LC Title", "source": "/lc/path"}

        fake_vs = MagicMock()
        fake_vs.search.return_value = [lc_doc]

        with _fake_db_readonly(agent), patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            return_value=fake_vs,
        ):
            results = search("k", "q", 5)
        assert len(results) == 1
        assert results[0]["text"] == "Langchain content"
        assert results[0]["title"] == "LC Title"

    def test_respects_chunks_cap(self):
        agent = {"source_id": "src-1", "extra_source_ids": []}
        docs = [
            {"text": f"Content {i}", "metadata": {"title": f"T{i}"}}
            for i in range(10)
        ]
        fake_vs = MagicMock()
        fake_vs.search.return_value = docs

        with _fake_db_readonly(agent), patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            return_value=fake_vs,
        ):
            results = search("k", "q", 3)
        assert len(results) == 3

    def test_deduplicates_results_by_content_prefix(self):
        agent = {"source_id": "src-1", "extra_source_ids": []}
        dup_text = "Duplicate content " * 20
        docs = [
            {"text": dup_text, "metadata": {"title": "T1"}},
            {"text": dup_text, "metadata": {"title": "T2"}},
            {"text": "Unique content", "metadata": {"title": "T3"}},
        ]
        fake_vs = MagicMock()
        fake_vs.search.return_value = docs

        with _fake_db_readonly(agent), patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            return_value=fake_vs,
        ):
            results = search("k", "q", 5)
        assert len(results) == 2

    def test_skips_broken_source_and_returns_from_healthy_ones(self):
        # Two sources — the first raises, the second returns a doc. The
        # caller should still get the healthy source's result.
        agent = {"extra_source_ids": ["broken", "ok"], "source_id": None}
        healthy_vs = MagicMock()
        healthy_vs.search.return_value = [
            {"text": "ok content", "metadata": {"title": "Ok"}}
        ]

        def create_vs(store, source_id, key):
            if source_id == "broken":
                raise RuntimeError("vector index missing")
            return healthy_vs

        with _fake_db_readonly(agent), patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            side_effect=create_vs,
        ):
            results = search("k", "q", 5)
        assert len(results) == 1
        assert results[0]["text"] == "ok content"

    def test_uses_filename_when_title_missing(self):
        agent = {"source_id": "src-1", "extra_source_ids": []}
        fake_vs = MagicMock()
        fake_vs.search.return_value = [
            {"text": "body", "metadata": {"filename": "document.pdf"}}
        ]
        with _fake_db_readonly(agent), patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            return_value=fake_vs,
        ):
            results = search("k", "q", 5)
        assert results[0]["title"] == "document.pdf"

    def test_uses_content_snippet_as_title_last_resort(self):
        agent = {"source_id": "src-1", "extra_source_ids": []}
        fake_vs = MagicMock()
        fake_vs.search.return_value = [
            {"text": "Content without any title metadata at all", "metadata": {}}
        ]
        with _fake_db_readonly(agent), patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            return_value=fake_vs,
        ):
            results = search("k", "q", 5)
        assert results[0]["title"].endswith("...")
        assert "Content without any title" in results[0]["title"]

    def test_skips_empty_source_ids(self):
        # ``source_id=" "`` only — after strip() this leaves no real source.
        agent = {"extra_source_ids": ["  ", ""], "source_id": None}
        with _fake_db_readonly(agent), patch(
            "application.services.search_service.VectorCreator.create_vectorstore"
        ) as mock_create:
            results = search("k", "q", 5)
        mock_create.assert_not_called()
        assert results == []
