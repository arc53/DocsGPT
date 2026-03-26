from unittest.mock import MagicMock, Mock, patch
from uuid import UUID

import pytest


def _make_milvus_store(source_id="test-source"):
    """Helper to create a MilvusStore with mocked deps."""
    with patch(
        "application.vectorstore.base.BaseVectorStore._get_embeddings"
    ) as mock_get_emb, patch(
        "application.vectorstore.milvus.settings"
    ) as mock_settings, patch.dict(
        "sys.modules",
        {
            "langchain_milvus": MagicMock(),
        },
    ):
        mock_emb = Mock()
        mock_get_emb.return_value = mock_emb
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_settings.MILVUS_URI = "http://localhost:19530"
        mock_settings.MILVUS_TOKEN = "token"
        mock_settings.MILVUS_COLLECTION_NAME = "test_collection"

        from langchain_milvus import Milvus

        mock_docsearch = MagicMock()
        Milvus.return_value = mock_docsearch

        from application.vectorstore.milvus import MilvusStore

        store = MilvusStore(source_id=source_id, embeddings_key="key")
        store._docsearch = mock_docsearch

        return store, mock_docsearch


@pytest.mark.unit
class TestMilvusStoreInit:
    def test_source_id_stored(self):
        store, _ = _make_milvus_store(source_id="src1")
        assert store._source_id == "src1"


@pytest.mark.unit
class TestMilvusStoreSearch:
    def test_search(self):
        store, mock_ds = _make_milvus_store(source_id="src1")
        mock_ds.similarity_search.return_value = ["doc1", "doc2"]

        results = store.search("query", k=3)

        mock_ds.similarity_search.assert_called_once()
        call_kwargs = mock_ds.similarity_search.call_args
        assert call_kwargs[1]["query"] == "query"
        assert call_kwargs[1]["k"] == 3
        assert call_kwargs[1]["expr"] == "source_id == 'src1'"
        assert results == ["doc1", "doc2"]


@pytest.mark.unit
class TestMilvusStoreAddTexts:
    def test_add_texts(self):
        store, mock_ds = _make_milvus_store()
        mock_ds.add_texts.return_value = ["id1", "id2"]

        result = store.add_texts(
            ["text1", "text2"], metadatas=[{"a": 1}, {"b": 2}]
        )

        mock_ds.add_texts.assert_called_once()
        call_kwargs = mock_ds.add_texts.call_args
        assert call_kwargs[1]["texts"] == ["text1", "text2"]
        # ids should be UUIDs
        ids = call_kwargs[1]["ids"]
        assert len(ids) == 2
        for uid in ids:
            UUID(uid)  # Validates it's a valid UUID

        assert result == ["id1", "id2"]


@pytest.mark.unit
class TestMilvusStoreSaveLocal:
    def test_save_local_is_noop(self):
        store, _ = _make_milvus_store()
        assert store.save_local() is None


@pytest.mark.unit
class TestMilvusStoreDeleteIndex:
    def test_delete_index_is_noop(self):
        store, _ = _make_milvus_store()
        assert store.delete_index() is None
