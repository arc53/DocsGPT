from unittest.mock import MagicMock, Mock, patch

import pytest

from application.retriever.base import BaseRetriever
from application.retriever.retriever_creator import RetrieverCreator


# ── BaseRetriever ──────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestBaseRetriever:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseRetriever()

    def test_subclass_must_implement_search(self):
        class Incomplete(BaseRetriever):
            pass

        with pytest.raises(TypeError):
            Incomplete()

    def test_concrete_subclass_works(self):
        class Concrete(BaseRetriever):
            def search(self, *args, **kwargs):
                return "ok"

        instance = Concrete()
        assert instance.search() == "ok"


# ── RetrieverCreator ───────────────────────────────────────────────────────────


@pytest.mark.unit
class TestRetrieverCreator:
    def test_create_classic(self):
        mock_cls = Mock(return_value="rag_instance")
        original = RetrieverCreator.retrievers.copy()
        RetrieverCreator.retrievers["classic"] = mock_cls
        try:
            result = RetrieverCreator.create_retriever("classic", "arg1", key="val")
            mock_cls.assert_called_once_with("arg1", key="val")
            assert result == "rag_instance"
        finally:
            RetrieverCreator.retrievers.update(original)

    def test_create_default(self):
        mock_cls = Mock(return_value="rag_instance")
        original = RetrieverCreator.retrievers.copy()
        RetrieverCreator.retrievers["default"] = mock_cls
        try:
            result = RetrieverCreator.create_retriever("default")
            mock_cls.assert_called_once_with()
            assert result == "rag_instance"
        finally:
            RetrieverCreator.retrievers.update(original)

    def test_create_none_type_uses_default(self):
        mock_cls = Mock(return_value="rag_instance")
        original = RetrieverCreator.retrievers.copy()
        RetrieverCreator.retrievers["default"] = mock_cls
        try:
            result = RetrieverCreator.create_retriever(None)
            mock_cls.assert_called_once()
            assert result == "rag_instance"
        finally:
            RetrieverCreator.retrievers.update(original)

    def test_case_insensitive(self):
        mock_cls = Mock(return_value="rag_instance")
        original = RetrieverCreator.retrievers.copy()
        RetrieverCreator.retrievers["classic"] = mock_cls
        try:
            RetrieverCreator.create_retriever("CLASSIC")
            mock_cls.assert_called_once()
        finally:
            RetrieverCreator.retrievers.update(original)

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="No retievers class found"):
            RetrieverCreator.create_retriever("nonexistent")


# ── ClassicRAG ─────────────────────────────────────────────────────────────────


@pytest.fixture
def _patch_llm_creator(mock_llm, monkeypatch):
    """Patch LLMCreator.create_llm to return the shared mock_llm fixture."""
    monkeypatch.setattr(
        "application.retriever.classic_rag.LLMCreator.create_llm",
        Mock(return_value=mock_llm),
    )
    return mock_llm


def _make_rag(source=None, _patch_llm_creator=None, **overrides):
    """Helper – builds a ClassicRAG with sensible defaults."""
    from application.retriever.classic_rag import ClassicRAG

    defaults = dict(
        source=source or {"question": "hello"},
        chat_history=None,
        prompt="",
        chunks=2,
        doc_token_limit=50000,
        model_id="test-model",
        user_api_key=None,
        agent_id=None,
        llm_name="openai",
        api_key="fake",
        decoded_token={"sub": "user1"},
    )
    defaults.update(overrides)
    return ClassicRAG(**defaults)


@pytest.mark.unit
class TestClassicRAGInit:
    def test_basic_init(self, _patch_llm_creator):
        rag = _make_rag()
        assert rag.original_question == "hello"
        assert rag.chunks == 2
        assert rag.vectorstores == []

    def test_active_docs_as_list(self, _patch_llm_creator):
        rag = _make_rag(source={"question": "q", "active_docs": ["a", "b"]})
        assert rag.vectorstores == ["a", "b"]

    def test_active_docs_as_string(self, _patch_llm_creator):
        rag = _make_rag(source={"question": "q", "active_docs": "single"})
        assert rag.vectorstores == ["single"]

    def test_active_docs_none(self, _patch_llm_creator):
        rag = _make_rag(source={"question": "q", "active_docs": None})
        assert rag.vectorstores == []

    def test_chunks_string_converted(self, _patch_llm_creator):
        rag = _make_rag(chunks="5")
        assert rag.chunks == 5

    def test_chunks_invalid_string_defaults(self, _patch_llm_creator):
        rag = _make_rag(chunks="abc")
        assert rag.chunks == 2

    def test_decoded_token_none(self, _patch_llm_creator):
        rag = _make_rag(decoded_token=None)
        assert rag.decoded_token is None


@pytest.mark.unit
class TestClassicRAGValidateVectorstore:
    def test_removes_empty_ids(self, _patch_llm_creator):
        rag = _make_rag(source={"question": "q", "active_docs": ["ok", "", "  ", "good"]})
        assert rag.vectorstores == ["ok", "good"]

    def test_empty_vectorstores_no_error(self, _patch_llm_creator):
        rag = _make_rag(source={"question": "q"})
        assert rag.vectorstores == []


@pytest.mark.unit
class TestClassicRAGRephraseQuery:
    def test_no_history_returns_original(self, _patch_llm_creator):
        rag = _make_rag(
            source={"question": "original", "active_docs": ["vs1"]},
            chat_history=[],
        )
        assert rag.question == "original"

    def test_no_vectorstores_returns_original(self, _patch_llm_creator):
        rag = _make_rag(
            source={"question": "original"},
            chat_history=[{"prompt": "hi", "response": "hello"}],
        )
        assert rag.question == "original"

    def test_chunks_zero_returns_original(self, _patch_llm_creator):
        rag = _make_rag(
            source={"question": "original", "active_docs": ["vs1"]},
            chat_history=[{"prompt": "hi", "response": "hello"}],
            chunks=0,
        )
        assert rag.question == "original"

    def test_rephrase_called_with_history(self, _patch_llm_creator, mock_llm):
        mock_llm.gen = Mock(return_value="rephrased question")
        rag = _make_rag(
            source={"question": "original", "active_docs": ["vs1"]},
            chat_history=[{"prompt": "hi", "response": "hello"}],
        )
        assert rag.question == "rephrased question"
        mock_llm.gen.assert_called_once()

    def test_rephrase_llm_returns_empty_falls_back(self, _patch_llm_creator, mock_llm):
        mock_llm.gen = Mock(return_value="")
        rag = _make_rag(
            source={"question": "original", "active_docs": ["vs1"]},
            chat_history=[{"prompt": "hi", "response": "hello"}],
        )
        assert rag.question == "original"

    def test_rephrase_llm_exception_falls_back(self, _patch_llm_creator, mock_llm):
        mock_llm.gen = Mock(side_effect=RuntimeError("boom"))
        rag = _make_rag(
            source={"question": "original", "active_docs": ["vs1"]},
            chat_history=[{"prompt": "hi", "response": "hello"}],
        )
        assert rag.question == "original"


@pytest.mark.unit
class TestClassicRAGLLMCreatorWiring:
    """ClassicRAG must forward model_id + model_user_id to LLMCreator so
    the registry-resolution path runs (BYOM api_key/base_url overrides
    and upstream_model_id translation). Without these the rephrase
    client dispatches the registry UUID to the plugin's default endpoint
    with the instance API key."""

    def test_passes_model_id_and_user_id_to_llmcreator(self, mock_llm, monkeypatch):
        captured = Mock(return_value=mock_llm)
        monkeypatch.setattr(
            "application.retriever.classic_rag.LLMCreator.create_llm", captured
        )

        _make_rag(
            model_id="byom-uuid",
            model_user_id="owner",
            decoded_token={"sub": "caller"},
        )

        assert captured.call_count == 1
        kwargs = captured.call_args.kwargs
        assert kwargs["model_id"] == "byom-uuid"
        assert kwargs["model_user_id"] == "owner"
        # Caller identity still flows so non-BYOM paths keep working.
        assert kwargs["decoded_token"] == {"sub": "caller"}

    def test_default_model_user_id_is_none(self, mock_llm, monkeypatch):
        captured = Mock(return_value=mock_llm)
        monkeypatch.setattr(
            "application.retriever.classic_rag.LLMCreator.create_llm", captured
        )

        _make_rag()  # no model_user_id override

        assert captured.call_args.kwargs["model_user_id"] is None


@pytest.mark.unit
class TestClassicRAGGetData:
    def test_chunks_zero_returns_empty(self, _patch_llm_creator):
        rag = _make_rag(chunks=0)
        assert rag._get_data() == []

    def test_no_vectorstores_returns_empty(self, _patch_llm_creator):
        rag = _make_rag(source={"question": "q"})
        assert rag._get_data() == []

    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_returns_docs_with_metadata(self, mock_tokens, mock_vc, _patch_llm_creator):
        mock_docsearch = MagicMock()
        mock_doc = MagicMock()
        mock_doc.page_content = "content here"
        mock_doc.metadata = {
            "title": "path/to/Title",
            "filename": "/docs/file.txt",
            "source": "http://example.com",
        }
        mock_docsearch.search.return_value = [mock_doc]
        mock_vc.create_vectorstore.return_value = mock_docsearch

        rag = _make_rag(source={"question": "q", "active_docs": ["vs1"]})
        docs = rag._get_data()

        assert len(docs) == 1
        assert docs[0]["text"] == "content here"
        assert docs[0]["title"] == "Title"
        assert docs[0]["filename"] == "file.txt"
        assert docs[0]["source"] == "http://example.com"

    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_dict_style_docs(self, mock_tokens, mock_vc, _patch_llm_creator):
        mock_docsearch = MagicMock()
        mock_docsearch.search.return_value = [
            {"text": "dict content", "metadata": {"title": "Dict Title"}}
        ]
        mock_vc.create_vectorstore.return_value = mock_docsearch

        rag = _make_rag(source={"question": "q", "active_docs": ["vs1"]})
        docs = rag._get_data()

        assert len(docs) == 1
        assert docs[0]["text"] == "dict content"

    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=100000)
    def test_token_budget_respected(self, mock_tokens, mock_vc, _patch_llm_creator):
        mock_docsearch = MagicMock()
        mock_doc = MagicMock()
        mock_doc.page_content = "big content"
        mock_doc.metadata = {"title": "t"}
        mock_docsearch.search.return_value = [mock_doc, mock_doc, mock_doc]
        mock_vc.create_vectorstore.return_value = mock_docsearch

        rag = _make_rag(
            source={"question": "q", "active_docs": ["vs1"]},
            doc_token_limit=100,
        )
        docs = rag._get_data()
        # tokens (100000) exceed budget (90), so no docs should be added
        assert len(docs) == 0

    @patch("application.retriever.classic_rag.VectorCreator")
    def test_vectorstore_error_continues(self, mock_vc, _patch_llm_creator):
        mock_vc.create_vectorstore.side_effect = RuntimeError("connection failed")

        rag = _make_rag(source={"question": "q", "active_docs": ["vs1"]})
        docs = rag._get_data()
        assert docs == []

    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_multiple_vectorstores(self, mock_tokens, mock_vc, _patch_llm_creator):
        mock_docsearch = MagicMock()
        mock_doc = MagicMock()
        mock_doc.page_content = "content"
        mock_doc.metadata = {"title": "t", "source": "s"}
        mock_docsearch.search.return_value = [mock_doc]
        mock_vc.create_vectorstore.return_value = mock_docsearch

        rag = _make_rag(source={"question": "q", "active_docs": ["vs1", "vs2"]})
        docs = rag._get_data()
        assert len(docs) == 2

    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_doc_missing_filename_uses_title(self, mock_tokens, mock_vc, _patch_llm_creator):
        mock_docsearch = MagicMock()
        mock_doc = MagicMock()
        mock_doc.page_content = "content"
        mock_doc.metadata = {"title": "MyTitle"}
        mock_docsearch.search.return_value = [mock_doc]
        mock_vc.create_vectorstore.return_value = mock_docsearch

        rag = _make_rag(source={"question": "q", "active_docs": ["vs1"]})
        docs = rag._get_data()
        assert docs[0]["filename"] == "MyTitle"

    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_non_string_title_converted(self, mock_tokens, mock_vc, _patch_llm_creator):
        mock_docsearch = MagicMock()
        mock_doc = MagicMock()
        mock_doc.page_content = "content"
        mock_doc.metadata = {"title": 42}
        mock_docsearch.search.return_value = [mock_doc]
        mock_vc.create_vectorstore.return_value = mock_docsearch

        rag = _make_rag(source={"question": "q", "active_docs": ["vs1"]})
        docs = rag._get_data()
        assert docs[0]["title"] == "42"


@pytest.mark.unit
class TestClassicRAGSearch:
    @patch("application.retriever.classic_rag.VectorCreator")
    @patch("application.retriever.classic_rag.num_tokens_from_string", return_value=10)
    def test_search_with_query_override(self, mock_tokens, mock_vc, _patch_llm_creator, mock_llm):
        mock_docsearch = MagicMock()
        mock_doc = MagicMock()
        mock_doc.page_content = "result"
        mock_doc.metadata = {"title": "t"}
        mock_docsearch.search.return_value = [mock_doc]
        mock_vc.create_vectorstore.return_value = mock_docsearch
        mock_llm.gen = Mock(return_value="")

        rag = _make_rag(source={"question": "original", "active_docs": ["vs1"]})
        docs = rag.search(query="override query")
        assert rag.original_question == "override query"
        assert len(docs) == 1

    def test_search_without_query_uses_default(self, _patch_llm_creator):
        rag = _make_rag(source={"question": "q"})
        docs = rag.search()
        assert docs == []
