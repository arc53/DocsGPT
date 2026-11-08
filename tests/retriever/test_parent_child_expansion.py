"""Tests for parent-child expansion and deduplication in ClassicRAG._get_data().

Covers:
- expand_to_parent helper (unit)
- child chunk is replaced by parent_text in the returned entry
- matched_text carries the original child text
- token budget is calculated on the expanded (parent) text
- sibling children sharing the same parent_text are deduplicated
- docs without parent_text are unaffected (no regression)
- HybridRetriever inherits the behaviour without its own changes
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from docsgpt.retriever.base import expand_to_parent


# ---------------------------------------------------------------------------
# Unit tests for the helper itself
# ---------------------------------------------------------------------------


class TestExpandToParent:
    def test_returns_parent_when_present(self):
        meta = {"parent_text": "big parent window"}
        assert expand_to_parent(meta, "small child") == "big parent window"

    def test_returns_child_when_no_key(self):
        assert expand_to_parent({"source": "foo.txt"}, "child text") == "child text"

    def test_returns_child_when_key_is_empty_string(self):
        assert expand_to_parent({"parent_text": ""}, "child text") == "child text"

    def test_returns_child_when_key_is_none(self):
        assert expand_to_parent({"parent_text": None}, "child text") == "child text"

    def test_returns_child_when_key_is_non_string(self):
        assert expand_to_parent({"parent_text": 123}, "child text") == "child text"

    def test_returns_child_when_metadata_is_none(self):
        assert expand_to_parent(None, "child text") == "child text"

    def test_returns_child_when_metadata_is_empty(self):
        assert expand_to_parent({}, "child text") == "child text"


# ---------------------------------------------------------------------------
# Helpers shared by ClassicRAG integration tests
# ---------------------------------------------------------------------------

PARENT_TEXT = "This is the full parent window with lots of context."
CHILD_TEXT_A = "parent window with"
CHILD_TEXT_B = "lots of context."


def _make_lc_doc(page_content: str, metadata: dict):
    """Minimal LangChain-style Document stand-in."""
    doc = SimpleNamespace()
    doc.page_content = page_content
    doc.metadata = metadata
    return doc


def _make_rag(docs, vectorstore_id="src-1", chunks=10, doc_token_limit=50_000):
    """Return a ClassicRAG instance wired to return ``docs`` from one fake store."""
    from docsgpt.retriever.classic_rag import ClassicRAG

    rag = ClassicRAG.__new__(ClassicRAG)
    rag.chunks = chunks
    rag.base_chunks = None
    rag.candidate_k = None
    rag.candidate_tokens = None
    rag.doc_token_limit = doc_token_limit
    rag.vectorstores = [vectorstore_id]
    rag.include_scores = False
    rag.last_outcome = None
    rag._rephrased_question = "q"
    rag.question = "q"
    rag.original_question = "q"
    rag.per_source_retrieval = {}

    # Fake connector labels (no-op)
    cc = MagicMock()
    cc.prefetch = MagicMock()
    cc.for_source = MagicMock(return_value={})
    rag.__dict__["_connector_label_cache"] = cc

    def _plan_sources(chunks_per_source):
        return [{"id": vectorstore_id, "src_k": chunks, "question": "q"}]

    def _fetch_all(plans):
        return [(docs, "cosine")]

    rag._plan_sources = _plan_sources
    rag._fetch_all = _fetch_all
    return rag


# ---------------------------------------------------------------------------
# Integration tests: ClassicRAG._get_data()
# ---------------------------------------------------------------------------


class TestClassicRAGParentExpansion:
    def test_entry_text_is_parent(self):
        """The returned entry['text'] must be the parent window, not the child."""
        doc = _make_lc_doc(CHILD_TEXT_A, {"parent_text": PARENT_TEXT, "source": "doc.txt"})
        rag = _make_rag([doc])
        results = rag._get_data()
        assert results, "Expected at least one result"
        assert results[0]["text"] == PARENT_TEXT

    def test_matched_text_is_child(self):
        """The original child chunk must survive under 'matched_text'."""
        doc = _make_lc_doc(CHILD_TEXT_A, {"parent_text": PARENT_TEXT, "source": "doc.txt"})
        rag = _make_rag([doc])
        results = rag._get_data()
        assert results[0]["matched_text"] == CHILD_TEXT_A

    def test_no_parent_text_unaffected(self):
        """A doc with no parent_text key must pass through unchanged."""
        doc = _make_lc_doc("standalone chunk", {"source": "other.txt"})
        rag = _make_rag([doc])
        results = rag._get_data()
        assert results[0]["text"] == "standalone chunk"
        assert "matched_text" not in results[0]

    def test_sibling_children_deduplicated(self):
        """Two children with the same parent_text must yield exactly one entry."""
        doc_a = _make_lc_doc(CHILD_TEXT_A, {"parent_text": PARENT_TEXT, "source": "doc.txt"})
        doc_b = _make_lc_doc(CHILD_TEXT_B, {"parent_text": PARENT_TEXT, "source": "doc.txt"})
        rag = _make_rag([doc_a, doc_b])
        results = rag._get_data()
        texts = [r["text"] for r in results]
        assert texts.count(PARENT_TEXT) == 1, f"Expected 1 occurrence, got {texts}"

    def test_first_child_wins_after_dedup(self):
        """The highest-ranked child (first in list) is kept; its sibling is dropped."""
        doc_a = _make_lc_doc(CHILD_TEXT_A, {"parent_text": PARENT_TEXT, "source": "doc.txt"})
        doc_b = _make_lc_doc(CHILD_TEXT_B, {"parent_text": PARENT_TEXT, "source": "doc.txt"})
        rag = _make_rag([doc_a, doc_b])
        results = rag._get_data()
        assert results[0]["matched_text"] == CHILD_TEXT_A

    def test_deduplicates_when_parent_matches_child_text(self):
        """Parent identity comes from metadata even if its text equals a child."""
        doc_a = _make_lc_doc(PARENT_TEXT, {"parent_text": PARENT_TEXT, "source": "doc.txt"})
        doc_b = _make_lc_doc(CHILD_TEXT_B, {"parent_text": PARENT_TEXT, "source": "doc.txt"})
        results = _make_rag([doc_a, doc_b])._get_data()
        assert len(results) == 1

    def test_different_parents_both_kept(self):
        """Children with different parent windows must each produce one entry."""
        doc_a = _make_lc_doc("child 1", {"parent_text": "parent window one", "source": "doc.txt"})
        doc_b = _make_lc_doc("child 2", {"parent_text": "parent window two", "source": "doc.txt"})
        rag = _make_rag([doc_a, doc_b])
        results = rag._get_data()
        assert len(results) == 2
        returned_texts = {r["text"] for r in results}
        assert returned_texts == {"parent window one", "parent window two"}

    def test_budget_uses_expanded_text(self):
        """Token budget must count the parent window length, not the child."""
        # Create a parent that is exactly long enough to exceed a tiny budget
        # when properly counted but not when counting only the short child.
        long_parent = "word " * 200  # ~200 tokens
        short_child = "word"         # ~1 token
        # Set token limit to 50 — big enough for the child alone but not the parent.
        # With correct expansion the doc must be excluded.
        doc = _make_lc_doc(short_child, {"parent_text": long_parent, "source": "doc.txt"})
        rag = _make_rag([doc], doc_token_limit=50)
        results = rag._get_data()
        # The parent is ~200 tokens; 90% of 50 = 45 token budget → excluded.
        assert results == [], f"Expected exclusion due to parent size; got {results}"

    def test_unselected_first_sibling_does_not_hide_a_later_child_that_fits(self):
        """A parent is marked seen only after one of its entries is accepted."""
        parent = "shared parent window"
        first = _make_lc_doc(
            "first child",
            {"parent_text": parent, "source": "doc.txt", "filename": "oversized " * 120},
        )
        second = _make_lc_doc(
            "second child",
            {"parent_text": parent, "source": "doc.txt", "filename": "small.txt"},
        )

        results = _make_rag([first, second], doc_token_limit=112)._get_data()

        assert len(results) == 1
        assert results[0]["text"] == parent
        assert results[0]["matched_text"] == "second child"

    def test_cross_source_dedup_independent(self):
        """Same parent_text from two different sources must NOT be deduplicated."""
        meta = {"parent_text": PARENT_TEXT, "source": "doc.txt"}
        doc_a = _make_lc_doc(CHILD_TEXT_A, meta)
        doc_b = _make_lc_doc(CHILD_TEXT_A, meta)

        # Wire two vectorstores each returning one doc
        from docsgpt.retriever.classic_rag import ClassicRAG

        rag = ClassicRAG.__new__(ClassicRAG)
        rag.chunks = 10
        rag.base_chunks = None
        rag.candidate_k = None
        rag.candidate_tokens = None
        rag.doc_token_limit = 50_000
        rag.vectorstores = ["src-1", "src-2"]
        rag.include_scores = False
        rag.last_outcome = None
        rag._rephrased_question = "q"
        rag.question = "q"
        rag.original_question = "q"
        rag.per_source_retrieval = {}

        cc = MagicMock()
        cc.prefetch = MagicMock()
        cc.for_source = MagicMock(return_value={})
        rag.__dict__["_connector_label_cache"] = cc

        def _plan_sources(chunks_per_source):
            return [
                {"id": "src-1", "src_k": 10, "question": "q"},
                {"id": "src-2", "src_k": 10, "question": "q"},
            ]

        def _fetch_all(plans):
            return [([doc_a], "cosine"), ([doc_b], "cosine")]

        rag._plan_sources = _plan_sources
        rag._fetch_all = _fetch_all

        results = rag._get_data()
        # Each source is an independent namespace, so both entries are kept.
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Integration tests: GraphRAGRetriever._graph_docs_for_source()
# ---------------------------------------------------------------------------


class TestGraphRAGParentExpansion:
    @patch("docsgpt.retriever.graph_rag.GraphStore")
    @patch("docsgpt.retriever.graph_rag.graphrag_available", return_value=True)
    def test_graphrag_substitutes_parent_text(self, _avail, mock_store_cls):
        from docsgpt.retriever.graph_rag import GraphRAGRetriever
        from docsgpt.storage.db.source_config import GraphRetrievalConfig

        rag = GraphRAGRetriever.__new__(GraphRAGRetriever)
        rag.chunks = 5
        rag.candidate_k = None
        rag.candidate_tokens = None
        rag.doc_token_limit = 50_000
        rag.vectorstores = ["src1"]
        rag._source_top_k = lambda s: 5
        rag._graph_options = lambda s: GraphRetrievalConfig(passage_nodes=False, blend_vector=False)

        cc = MagicMock()
        cc.for_source = MagicMock(return_value={})
        rag.__dict__["_connector_label_cache"] = cc

        rag._ppr_scores = MagicMock(return_value={"n1": 1.0})
        rag._rank_chunks = MagicMock(return_value=["c1"])

        store = MagicMock()
        store.get_chunk_texts.return_value = {
            "c1": {
                "text": "child text",
                "metadata": {"parent_text": "parent window text", "source": "f.txt"},
            }
        }

        docs = rag._graph_docs_for_source(store, "src1", None)
        assert len(docs) == 1
        assert docs[0]["text"] == "parent window text"
        assert docs[0]["matched_text"] == "child text"

    @patch("docsgpt.retriever.graph_rag.GraphStore")
    @patch("docsgpt.retriever.graph_rag.graphrag_available", return_value=True)
    def test_graphrag_deduplicates_shared_parent(self, _avail, mock_store_cls):
        from docsgpt.retriever.graph_rag import GraphRAGRetriever
        from docsgpt.storage.db.source_config import GraphRetrievalConfig

        rag = GraphRAGRetriever.__new__(GraphRAGRetriever)
        rag.chunks = 5
        rag.candidate_k = None
        rag.candidate_tokens = None
        rag.doc_token_limit = 50_000
        rag.vectorstores = ["src1"]
        rag._source_top_k = lambda s: 5
        rag._graph_options = lambda s: GraphRetrievalConfig(passage_nodes=False, blend_vector=False)

        cc = MagicMock()
        cc.for_source = MagicMock(return_value={})
        rag.__dict__["_connector_label_cache"] = cc

        rag._ppr_scores = MagicMock(return_value={"n1": 1.0})
        rag._rank_chunks = MagicMock(return_value=["c1", "c2"])

        store = MagicMock()
        store.get_chunk_texts.return_value = {
            "c1": {
                "text": "child text 1",
                "metadata": {"parent_text": "shared parent", "source": "f.txt"},
            },
            "c2": {
                "text": "child text 2",
                "metadata": {"parent_text": "shared parent", "source": "f.txt"},
            },
        }

        docs = rag._graph_docs_for_source(store, "src1", None)
        assert len(docs) == 1
        assert docs[0]["text"] == "shared parent"
        assert docs[0]["matched_text"] == "child text 1"


