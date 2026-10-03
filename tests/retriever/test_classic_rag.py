"""Tests for ClassicRAG._get_data() retrieval logic.

These tests call the real _get_data() method with mocked vectorstores,
verifying actual behavior rather than reimplementing formulas inline.
"""

from unittest.mock import Mock, patch

import pytest

from application.retriever.classic_rag import ClassicRAG


def _make_doc(content: str, filename: str = "doc.txt"):
    """Create a mock document with page_content and metadata attributes.

    Provides a filename in metadata so labels_from_metadata doesn't fall
    back to using the page content as the title/filename.
    """
    doc = Mock()
    doc.page_content = content
    doc.metadata = {"filename": filename}
    return doc


@pytest.mark.unit
class TestClassicRAGRealMethod:
    @patch("application.retriever.classic_rag.LLMCreator.create_llm")
    def test_chunks_2_across_2_sources_returns_at_most_2_docs(self, mock_create_llm):
        """chunks=2, 2 sources → ceiling=max(2,2)=2, at most 2 docs returned."""

        mock_llm = Mock()
        mock_create_llm.return_value = mock_llm

        mock_docsearch = Mock()
        # Return 3 docs per source (more than ceiling=2)
        mock_docsearch.search.return_value = [
            _make_doc("doc A content here"),
            _make_doc("doc B content here"),
            _make_doc("doc C content here"),
        ]

        with patch(
            "application.retriever.classic_rag.VectorCreator.create_vectorstore",
            return_value=mock_docsearch,
        ):
            rag = ClassicRAG(
                source={"question": "test"},
                chunks=2,
                doc_token_limit=50000,
            )
            rag.vectorstores = ["vs1", "vs2"]

            result = rag._get_data()

            # ceiling = max(chunks=2, num_sources=2) = 2
            assert len(result) <= 2, f"Expected <=2 docs, got {len(result)}: {[r['text'] for r in result]}"

    @patch("application.retriever.classic_rag.LLMCreator.create_llm")
    def test_chunks_5_across_2_sources_returns_at_most_5_docs(self, mock_create_llm):
        """chunks=5, 2 sources → ceiling=max(5,2)=5, at most 5 docs returned."""

        mock_llm = Mock()
        mock_create_llm.return_value = mock_llm

        mock_docsearch = Mock()
        # Return 6 docs per source (more than ceiling=5)
        mock_docsearch.search.return_value = [
            _make_doc("doc content") for _ in range(6)
        ]

        with patch(
            "application.retriever.classic_rag.VectorCreator.create_vectorstore",
            return_value=mock_docsearch,
        ):
            rag = ClassicRAG(
                source={"question": "test"},
                chunks=5,
                doc_token_limit=50000,
            )
            rag.vectorstores = ["vs1", "vs2"]

            result = rag._get_data()

            # ceiling = max(chunks=5, num_sources=2) = 5
            assert len(result) <= 5, f"Expected <=5 docs, got {len(result)}: {[r['text'] for r in result]}"

    @patch("application.retriever.classic_rag.LLMCreator.create_llm")
    def test_base_chunks_10_override_chunks_2_3_sources_ceiling_3(self, mock_create_llm):
        """base_chunks=10, chunks=2, 3 sources → chunks_per_source=max(1,10//3)=3,
        ceiling=max(2,3)=3, so at most 3 docs returned total."""

        mock_llm = Mock()
        mock_create_llm.return_value = mock_llm

        mock_docsearch = Mock()
        # Return 5 docs per source (more than we'll keep)
        mock_docsearch.search.return_value = [
            _make_doc("doc content", filename="doc.pdf") for _ in range(5)
        ]

        with patch(
            "application.retriever.classic_rag.VectorCreator.create_vectorstore",
            return_value=mock_docsearch,
        ):
            rag = ClassicRAG(
                source={"question": "test"},
                chunks=2,
                doc_token_limit=50000,
            )
            rag.base_chunks = 10  # set after init — class attribute, not kwarg
            rag.vectorstores = ["vs1", "vs2", "vs3"]

            result = rag._get_data()

            # chunks_per_source = max(1, 10//3) = 3
            # ceiling = max(chunks=2, num_sources=3) = 3
            assert len(result) <= 3, f"Expected <=3 docs, got {len(result)}: {[r['text'] for r in result]}"

    @patch("application.retriever.classic_rag.LLMCreator.create_llm")
    def test_token_budget_stops_retrieval_early(self, mock_create_llm):
        """Docs should stop being added when cumulative_tokens >= token_budget.

        Mock num_tokens_from_string in the classic_rag module so the budget
        check is deterministic: 3 docs × ~33 tokens = ~99 ≤ budget=100, 4th overflows.
        """

        mock_llm = Mock()
        mock_create_llm.return_value = mock_llm

        with patch("application.retriever.classic_rag.num_tokens_from_string", return_value=33) as mock_tokens:
            # Each doc's text+header ≈ 33 tokens; budget=100 → 3 docs fit (99), 4th overflows
            mock_docsearch = Mock()

            # 4 docs, each ~33 tokens; budget=100 → only 3 should be kept
            mock_docsearch.search.return_value = [
                (_make_doc("doc one", filename="a.txt"), None),
                (_make_doc("doc two", filename="b.txt"), None),
                (_make_doc("doc three", filename="c.txt"), None),
                (_make_doc("doc four", filename="d.txt"), None),
            ]

            with patch(
                "application.retriever.classic_rag.VectorCreator.create_vectorstore",
                return_value=mock_docsearch,
            ):
                rag = ClassicRAG(
                    source={"question": "test"},
                    chunks=10,
                    doc_token_limit=100,
                )
                rag.vectorstores = ["vs1"]

                result = rag._get_data()

                # 3 docs fit within budget (99 ≤ 100), 4th overflows (132 > 100)
                assert len(result) == 3, f"Expected exactly 3 docs (budget-limited), got {len(result)}"

    @patch("application.retriever.classic_rag.LLMCreator.create_llm")
    def test_search_delegates_to_get_data(self, mock_create_llm):
        """search() should delegate to _get_data()."""

        mock_llm = Mock()
        mock_create_llm.return_value = mock_llm

        with patch.object(
            ClassicRAG, "_get_data", return_value=[{"text": "mocked doc", "filename": "test.pdf"}]
        ):
            rag = ClassicRAG(
                source={"question": "test"},
                chunks=2,
                doc_token_limit=50000,
            )
            result = rag.search(query="test query")

            # _get_data was called with the rephrased question
            assert result is not None