"""Unit tests for the Valkey vector store implementation."""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest


def _make_store(source_id="test-source", embeddings_key="key"):
    """Helper to create a ValkeyStore with all external deps mocked."""
    with patch(
        "application.vectorstore.base.BaseVectorStore._get_embeddings"
    ) as mock_get_emb, patch(
        "application.vectorstore.valkey.settings"
    ) as mock_settings, patch(
        "application.vectorstore.valkey.ValkeyStore._create_client"
    ) as mock_create_client, patch(
        "application.vectorstore.valkey.ValkeyStore._ensure_index_exists"
    ):
        mock_emb = Mock()
        mock_emb.embed_query = Mock(return_value=[0.1, 0.2, 0.3])
        mock_emb.embed_documents = Mock(return_value=[[0.1, 0.2, 0.3]])
        mock_emb.dimension = 768
        mock_get_emb.return_value = mock_emb

        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_settings.VALKEY_HOST = "localhost"
        mock_settings.VALKEY_PORT = 6379
        mock_settings.VALKEY_PASSWORD = None
        mock_settings.VALKEY_USE_TLS = False
        mock_settings.VALKEY_INDEX_NAME = "docsgpt"
        mock_settings.VALKEY_PREFIX = "doc:"

        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        from application.vectorstore.valkey import ValkeyStore

        store = ValkeyStore(source_id=source_id, embeddings_key=embeddings_key)

    return store, mock_client, mock_emb


@pytest.mark.unit
class TestValkeyStoreInit:
    def test_source_id_cleaned(self):
        store, _, _ = _make_store(source_id="application/indexes/abc123/")
        assert store._source_id == "abc123"

    def test_source_id_simple(self):
        store, _, _ = _make_store(source_id="my-source")
        assert store._source_id == "my-source"


@pytest.mark.unit
class TestValkeyStoreSearch:
    def test_search_returns_documents(self):
        store, mock_client, mock_emb = _make_store()

        # ft.search returns [total_count, {key: {field: value}}, ...]
        mock_response = [
            2,
            {b"doc:id1": {b"content": b"hello world", b"source_id": b"test-source", b"metadata": b'{"source": "test.txt"}'}},
            {b"doc:id2": {b"content": b"foo bar", b"source_id": b"test-source", b"metadata": b'{"source": "test2.txt"}'}},
        ]

        with patch("application.vectorstore.valkey.ft.search", return_value=mock_response):
            results = store.search("query", k=2)

        mock_emb.embed_query.assert_called_once_with("query")
        assert len(results) == 2
        assert results[0].page_content == "hello world"
        assert results[0].metadata == {"source": "test.txt"}
        assert results[1].page_content == "foo bar"

    def test_search_returns_empty_on_error(self):
        store, mock_client, _ = _make_store()

        with patch("application.vectorstore.valkey.ft.search", side_effect=Exception("connection lost")):
            results = store.search("query")
            assert results == []

    def test_search_returns_empty_on_no_results(self):
        store, mock_client, _ = _make_store()

        with patch("application.vectorstore.valkey.ft.search", return_value=[0]):
            results = store.search("query")
            assert results == []

    def test_search_handles_string_fields(self):
        store, mock_client, _ = _make_store()

        mock_response = [
            1,
            {"doc:id1": {"content": "hello", "source_id": "test-source", "metadata": "{}"}},
        ]

        with patch("application.vectorstore.valkey.ft.search", return_value=mock_response):
            results = store.search("query", k=1)

        assert len(results) == 1
        assert results[0].page_content == "hello"


@pytest.mark.unit
class TestValkeyStoreAddTexts:
    def test_add_texts_returns_ids(self):
        store, mock_client, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_client.hset = Mock(return_value=3)

        ids = store.add_texts(["text1", "text2"], [{"a": 1}, {"b": 2}])

        assert len(ids) == 2
        assert mock_client.hset.call_count == 2

    def test_add_texts_empty_returns_empty(self):
        store, _, _ = _make_store()
        assert store.add_texts([]) == []

    def test_add_texts_default_metadatas(self):
        store, mock_client, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = [[0.1, 0.2, 0.3]]
        mock_client.hset = Mock(return_value=3)

        ids = store.add_texts(["text1"])
        assert len(ids) == 1

    def test_add_texts_raises_on_error(self):
        store, mock_client, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = [[0.1, 0.2, 0.3]]
        mock_client.hset = Mock(side_effect=Exception("write failed"))

        with pytest.raises(Exception, match="write failed"):
            store.add_texts(["text1"])

    def test_add_texts_stores_correct_fields(self):
        store, mock_client, mock_emb = _make_store(source_id="src1")
        mock_emb.embed_documents.return_value = [[0.1, 0.2, 0.3]]
        mock_client.hset = Mock(return_value=3)

        store.add_texts(["hello"], [{"key": "val"}])

        call_args = mock_client.hset.call_args
        key = call_args[0][0]
        fields = call_args[0][1]

        assert key.startswith("doc:")
        assert fields["content"] == "hello"
        assert fields["source_id"] == "src1"
        assert json.loads(fields["metadata"]) == {"key": "val"}
        assert isinstance(fields["embedding"], bytes)


@pytest.mark.unit
class TestValkeyStoreDeleteIndex:
    def test_delete_index_deletes_matching_docs(self):
        store, mock_client, _ = _make_store(source_id="src123")

        mock_response = [
            2,
            {b"doc:id1": {b"content": b"text1"}},
            {b"doc:id2": {b"content": b"text2"}},
        ]

        with patch("application.vectorstore.valkey.ft.search", return_value=mock_response):
            mock_client.delete = Mock(return_value=1)
            store.delete_index()

        assert mock_client.delete.call_count == 2

    def test_delete_index_handles_error(self):
        store, mock_client, _ = _make_store()

        with patch("application.vectorstore.valkey.ft.search", side_effect=Exception("fail")):
            # Should not raise
            store.delete_index()


@pytest.mark.unit
class TestValkeyStoreSaveLocal:
    def test_save_local_is_noop(self):
        store, _, _ = _make_store()
        assert store.save_local() is None


@pytest.mark.unit
class TestValkeyStoreGetChunks:
    def test_get_chunks(self):
        store, mock_client, _ = _make_store()

        mock_response = [
            2,
            {b"doc:uuid1": {b"content": b"text1", b"source_id": b"test-source", b"metadata": b'{"key": "val"}'}},
            {b"doc:uuid2": {b"content": b"text2", b"source_id": b"test-source", b"metadata": b"{}"}},
        ]

        with patch("application.vectorstore.valkey.ft.search", return_value=mock_response):
            chunks = store.get_chunks()

        assert len(chunks) == 2
        assert chunks[0] == {"doc_id": "uuid1", "text": "text1", "metadata": {"key": "val"}}
        assert chunks[1] == {"doc_id": "uuid2", "text": "text2", "metadata": {}}

    def test_get_chunks_returns_empty_on_error(self):
        store, mock_client, _ = _make_store()

        with patch("application.vectorstore.valkey.ft.search", side_effect=Exception("fail")):
            assert store.get_chunks() == []


@pytest.mark.unit
class TestValkeyStoreAddChunk:
    def test_add_chunk(self):
        store, mock_client, mock_emb = _make_store(source_id="src1")
        mock_emb.embed_documents.return_value = [[0.1, 0.2, 0.3]]
        mock_client.hset = Mock(return_value=3)

        chunk_id = store.add_chunk("hello", metadata={"key": "val"})

        assert isinstance(chunk_id, str)
        assert len(chunk_id) > 0
        mock_client.hset.assert_called_once()

    def test_add_chunk_raises_on_empty_embedding(self):
        store, _, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = []

        with pytest.raises(ValueError, match="Could not generate embedding"):
            store.add_chunk("text")

    def test_add_chunk_includes_source_id_in_metadata(self):
        store, mock_client, mock_emb = _make_store(source_id="src1")
        mock_emb.embed_documents.return_value = [[0.1, 0.2, 0.3]]
        mock_client.hset = Mock(return_value=3)

        store.add_chunk("hello", metadata={"key": "val"})

        call_args = mock_client.hset.call_args
        fields = call_args[0][1]
        metadata = json.loads(fields["metadata"])
        assert metadata["source_id"] == "src1"
        assert metadata["key"] == "val"


@pytest.mark.unit
class TestValkeyStoreDeleteChunk:
    def test_delete_chunk_success(self):
        store, mock_client, _ = _make_store()
        mock_client.delete = Mock(return_value=1)

        result = store.delete_chunk("uuid-123")
        assert result is True
        mock_client.delete.assert_called_once_with(["doc:uuid-123"])

    def test_delete_chunk_not_found(self):
        store, mock_client, _ = _make_store()
        mock_client.delete = Mock(return_value=0)

        result = store.delete_chunk("nonexistent")
        assert result is False

    def test_delete_chunk_returns_false_on_error(self):
        store, mock_client, _ = _make_store()
        mock_client.delete = Mock(side_effect=Exception("fail"))

        result = store.delete_chunk("uuid-123")
        assert result is False
