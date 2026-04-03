from unittest.mock import MagicMock, Mock, patch

import pytest


def _make_qdrant_store(source_id="test-source"):
    """Helper to create a QdrantStore with all external deps mocked."""
    mock_models = MagicMock()
    mock_qdrant_langchain = MagicMock()

    with patch(
        "application.vectorstore.base.BaseVectorStore._get_embeddings"
    ) as mock_get_emb, patch(
        "application.vectorstore.qdrant.settings"
    ) as mock_settings, patch.dict(
        "sys.modules",
        {
            "qdrant_client": MagicMock(),
            "qdrant_client.models": mock_models,
            "langchain_community": MagicMock(),
            "langchain_community.vectorstores": MagicMock(),
            "langchain_community.vectorstores.qdrant": mock_qdrant_langchain,
        },
    ):
        mock_emb = Mock()
        mock_emb.embed_query = Mock(return_value=[0.1, 0.2, 0.3])
        mock_emb.embed_documents = Mock(return_value=[[0.1, 0.2, 0.3]])
        mock_emb.client = [None, Mock(word_embedding_dimension=768)]
        mock_get_emb.return_value = mock_emb

        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_settings.QDRANT_COLLECTION_NAME = "test_collection"
        mock_settings.QDRANT_LOCATION = ":memory:"
        mock_settings.QDRANT_URL = None
        mock_settings.QDRANT_PORT = 6333
        mock_settings.QDRANT_GRPC_PORT = 6334
        mock_settings.QDRANT_HTTPS = False
        mock_settings.QDRANT_PREFER_GRPC = False
        mock_settings.QDRANT_API_KEY = None
        mock_settings.QDRANT_PREFIX = None
        mock_settings.QDRANT_TIMEOUT = None
        mock_settings.QDRANT_PATH = None
        mock_settings.QDRANT_DISTANCE_FUNC = "Cosine"

        mock_docsearch = MagicMock()
        mock_collections = MagicMock()
        mock_collections.collections = [MagicMock(name="test_collection")]
        mock_docsearch.client.get_collections.return_value = mock_collections
        mock_qdrant_langchain.Qdrant.construct_instance.return_value = mock_docsearch

        from application.vectorstore.qdrant import QdrantStore

        store = QdrantStore(source_id=source_id, embeddings_key="key")

        return store, mock_docsearch, mock_settings


@pytest.mark.unit
class TestQdrantStoreInit:
    def test_source_id_cleaned(self):
        store, _, _ = _make_qdrant_store(source_id="application/indexes/abc123/")
        assert store._source_id == "abc123"

    def test_filter_constructed(self):
        store, _, _ = _make_qdrant_store(source_id="src1")
        assert store._filter is not None


@pytest.mark.unit
class TestQdrantStoreSearch:
    def test_search_delegates(self):
        store, mock_ds, _ = _make_qdrant_store()
        mock_ds.similarity_search.return_value = ["result1"]

        results = store.search("query", k=5)

        mock_ds.similarity_search.assert_called_once()
        assert results == ["result1"]


@pytest.mark.unit
class TestQdrantStoreAddTexts:
    def test_add_texts_delegates(self):
        store, mock_ds, _ = _make_qdrant_store()
        mock_ds.add_texts.return_value = ["id1"]

        result = store.add_texts(["text1"], metadatas=[{"a": 1}])
        mock_ds.add_texts.assert_called_once_with(["text1"], metadatas=[{"a": 1}])
        assert result == ["id1"]


@pytest.mark.unit
class TestQdrantStoreSaveLocal:
    def test_save_local_is_noop(self):
        store, _, _ = _make_qdrant_store()
        assert store.save_local() is None


@pytest.mark.unit
class TestQdrantStoreDeleteIndex:
    def test_delete_index(self):
        store, mock_ds, _ = _make_qdrant_store()

        with patch("application.vectorstore.qdrant.settings") as ms:
            ms.QDRANT_COLLECTION_NAME = "test_collection"
            store.delete_index()

        mock_ds.client.delete.assert_called_once_with(
            collection_name="test_collection",
            points_selector=store._filter,
        )


@pytest.mark.unit
class TestQdrantStoreGetChunks:
    def test_get_chunks(self):
        store, mock_ds, _ = _make_qdrant_store()

        record1 = MagicMock()
        record1.id = "id1"
        record1.payload = {
            "page_content": "text1",
            "metadata": {"source": "test"},
        }
        record2 = MagicMock()
        record2.id = "id2"
        record2.payload = {
            "page_content": "text2",
            "metadata": {"source": "test2"},
        }

        # First call returns records with offset, second returns empty with None offset
        mock_ds.client.scroll.side_effect = [
            ([record1, record2], None),
        ]

        chunks = store.get_chunks()

        assert len(chunks) == 2
        assert chunks[0] == {
            "doc_id": "id1",
            "text": "text1",
            "metadata": {"source": "test"},
        }

    def test_get_chunks_pagination(self):
        store, mock_ds, _ = _make_qdrant_store()

        record1 = MagicMock()
        record1.id = "id1"
        record1.payload = {"page_content": "text1", "metadata": {}}

        record2 = MagicMock()
        record2.id = "id2"
        record2.payload = {"page_content": "text2", "metadata": {}}

        mock_ds.client.scroll.side_effect = [
            ([record1], "offset_token"),
            ([record2], None),
        ]

        chunks = store.get_chunks()
        assert len(chunks) == 2
        assert mock_ds.client.scroll.call_count == 2

    def test_get_chunks_returns_empty_on_error(self):
        store, mock_ds, _ = _make_qdrant_store()
        mock_ds.client.scroll.side_effect = Exception("fail")

        assert store.get_chunks() == []


@pytest.mark.unit
class TestQdrantStoreAddChunk:
    def test_add_chunk(self):
        store, mock_ds, _ = _make_qdrant_store(source_id="src1")
        mock_ds.add_documents.return_value = ["new-id"]

        result = store.add_chunk("hello", metadata={"key": "val"})

        assert result == "new-id"
        mock_ds.add_documents.assert_called_once()
        doc = mock_ds.add_documents.call_args[0][0][0]
        assert doc.page_content == "hello"
        assert doc.metadata["source_id"] == "src1"
        assert doc.metadata["key"] == "val"

    def test_add_chunk_default_metadata(self):
        store, mock_ds, _ = _make_qdrant_store(source_id="src1")
        mock_ds.add_documents.return_value = ["id"]

        store.add_chunk("text")

        doc = mock_ds.add_documents.call_args[0][0][0]
        assert doc.metadata["source_id"] == "src1"

    def test_add_chunk_fallback_id(self):
        store, mock_ds, _ = _make_qdrant_store()
        mock_ds.add_documents.return_value = []

        result = store.add_chunk("text")
        # Should return the uuid that was generated
        assert result is not None
        assert isinstance(result, str)


@pytest.mark.unit
class TestQdrantStoreDeleteChunk:
    def test_delete_chunk_success(self):
        store, mock_ds, _ = _make_qdrant_store()

        with patch("application.vectorstore.qdrant.settings") as ms:
            ms.QDRANT_COLLECTION_NAME = "test_collection"
            result = store.delete_chunk("chunk-id")

        mock_ds.client.delete.assert_called_once_with(
            collection_name="test_collection",
            points_selector=["chunk-id"],
        )
        assert result is True

    def test_delete_chunk_returns_false_on_error(self):
        store, mock_ds, _ = _make_qdrant_store()

        with patch("application.vectorstore.qdrant.settings") as ms:
            ms.QDRANT_COLLECTION_NAME = "test_collection"
            mock_ds.client.delete.side_effect = Exception("fail")
            result = store.delete_chunk("bad-id")

        assert result is False
