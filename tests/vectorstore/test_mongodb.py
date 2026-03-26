from unittest.mock import MagicMock, Mock, patch

import pytest


def _make_mongodb_store(source_id="test-source"):
    """Helper to create a MongoDBVectorStore with all external deps mocked."""
    with patch(
        "application.vectorstore.base.BaseVectorStore._get_embeddings"
    ) as mock_get_emb, patch(
        "application.vectorstore.mongodb.settings"
    ) as mock_settings, patch.dict(
        "sys.modules", {"pymongo": MagicMock()}
    ):
        mock_emb = Mock()
        mock_emb.embed_query = Mock(return_value=[0.1, 0.2, 0.3])
        mock_emb.embed_documents = Mock(return_value=[[0.1, 0.2, 0.3]])
        mock_get_emb.return_value = mock_emb
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_settings.MONGO_URI = "mongodb://localhost:27017"

        from application.vectorstore.mongodb import MongoDBVectorStore

        store = MongoDBVectorStore(
            source_id=source_id,
            embeddings_key="key",
            collection="test_docs",
            database="test_db",
        )

        mock_collection = MagicMock()
        store._collection = mock_collection

        return store, mock_collection, mock_emb


@pytest.mark.unit
class TestMongoDBVectorStoreInit:
    def test_source_id_cleaned(self):
        store, _, _ = _make_mongodb_store(source_id="application/indexes/abc123/")
        assert store._source_id == "abc123"


@pytest.mark.unit
class TestMongoDBVectorStoreSearch:
    def test_search_builds_pipeline(self):
        store, mock_collection, mock_emb = _make_mongodb_store()

        doc1 = {
            "_id": "id1",
            "text": "hello world",
            "embedding": [0.1, 0.2],
            "source": "test",
        }
        mock_collection.aggregate.return_value = iter([doc1])

        results = store.search("query", k=3)

        mock_emb.embed_query.assert_called_once_with("query")
        mock_collection.aggregate.assert_called_once()
        pipeline = mock_collection.aggregate.call_args[0][0]
        assert pipeline[0]["$vectorSearch"]["limit"] == 3
        assert pipeline[0]["$vectorSearch"]["numCandidates"] == 30

        assert len(results) == 1
        assert str(results[0]) == "hello world"

    def test_search_removes_id_text_embedding_from_metadata(self):
        store, mock_collection, _ = _make_mongodb_store()

        doc = {
            "_id": "id1",
            "text": "content",
            "embedding": [0.1],
            "custom_key": "custom_val",
        }
        mock_collection.aggregate.return_value = iter([doc])

        results = store.search("q", k=1)
        metadata = results[0].metadata
        assert "_id" not in metadata
        assert "text" not in metadata
        assert "embedding" not in metadata
        assert metadata["custom_key"] == "custom_val"


@pytest.mark.unit
class TestMongoDBVectorStoreAddTexts:
    def test_add_texts_batches(self):
        store, mock_collection, mock_emb = _make_mongodb_store()
        # Generate 150 texts to trigger batching at 100
        texts = [f"text_{i}" for i in range(150)]
        metadatas = [{"i": i} for i in range(150)]
        mock_emb.embed_documents.return_value = [[0.1]] * 100  # per batch

        mock_collection.insert_many.return_value = Mock(
            inserted_ids=list(range(100))
        )

        store.add_texts(texts, metadatas)

        # Should have been called twice: batch of 100, then batch of 50
        assert mock_collection.insert_many.call_count == 2

    def test_add_texts_default_metadata(self):
        store, mock_collection, mock_emb = _make_mongodb_store()
        mock_emb.embed_documents.return_value = [[0.1]]
        mock_collection.insert_many.return_value = Mock(inserted_ids=["id1"])

        store.add_texts(["text1"])
        mock_collection.insert_many.assert_called_once()

    def test_add_texts_empty(self):
        store, mock_collection, mock_emb = _make_mongodb_store()
        mock_emb.embed_documents.return_value = []
        mock_collection.insert_many.return_value = Mock(inserted_ids=[])

        result = store.add_texts([], [])
        # _insert_texts returns [] for empty input
        assert result == []


@pytest.mark.unit
class TestMongoDBVectorStoreInsertTexts:
    def test_insert_texts_empty_returns_empty(self):
        store, _, _ = _make_mongodb_store()
        result = store._insert_texts([], [])
        assert result == []

    def test_insert_texts_builds_correct_documents(self):
        store, mock_collection, mock_emb = _make_mongodb_store()
        mock_emb.embed_documents.return_value = [[0.1, 0.2]]
        mock_collection.insert_many.return_value = Mock(inserted_ids=["id1"])

        store._insert_texts(["hello"], [{"source": "test"}])

        inserted_docs = mock_collection.insert_many.call_args[0][0]
        assert len(inserted_docs) == 1
        assert inserted_docs[0]["text"] == "hello"
        assert inserted_docs[0]["embedding"] == [0.1, 0.2]
        assert inserted_docs[0]["source"] == "test"


@pytest.mark.unit
class TestMongoDBVectorStoreDeleteIndex:
    def test_delete_index_calls_delete_many(self):
        store, mock_collection, _ = _make_mongodb_store(source_id="src1")

        store.delete_index()

        mock_collection.delete_many.assert_called_once_with({"source_id": "src1"})


@pytest.mark.unit
class TestMongoDBVectorStoreGetChunks:
    def test_get_chunks(self):
        store, mock_collection, _ = _make_mongodb_store()

        docs = [
            {
                "_id": "id1",
                "text": "chunk1",
                "embedding": [0.1],
                "source_id": "src",
                "extra": "val",
            },
            {
                "_id": "id2",
                "text": "chunk2",
                "embedding": [0.2],
                "source_id": "src",
            },
        ]
        mock_collection.find.return_value = iter(docs)

        chunks = store.get_chunks()

        assert len(chunks) == 2
        assert chunks[0]["doc_id"] == "id1"
        assert chunks[0]["text"] == "chunk1"
        assert chunks[0]["metadata"] == {"extra": "val"}
        assert "embedding" not in chunks[0]["metadata"]
        assert "source_id" not in chunks[0]["metadata"]

    def test_get_chunks_skips_empty_text(self):
        store, mock_collection, _ = _make_mongodb_store()

        docs = [
            {"_id": "id1", "text": None, "embedding": [0.1], "source_id": "src"},
        ]
        mock_collection.find.return_value = iter(docs)

        chunks = store.get_chunks()
        assert len(chunks) == 0

    def test_get_chunks_returns_empty_on_error(self):
        store, mock_collection, _ = _make_mongodb_store()
        mock_collection.find.side_effect = Exception("connection error")

        assert store.get_chunks() == []


@pytest.mark.unit
class TestMongoDBVectorStoreAddChunk:
    def test_add_chunk(self):
        store, mock_collection, mock_emb = _make_mongodb_store(source_id="src1")
        mock_emb.embed_documents.return_value = [[0.1, 0.2]]
        mock_collection.insert_one.return_value = Mock(inserted_id="new_id")

        result = store.add_chunk("hello chunk", metadata={"key": "val"})

        assert result == "new_id"
        inserted = mock_collection.insert_one.call_args[0][0]
        assert inserted["text"] == "hello chunk"
        assert inserted["source_id"] == "src1"
        assert inserted["key"] == "val"

    def test_add_chunk_default_metadata(self):
        store, mock_collection, mock_emb = _make_mongodb_store()
        mock_emb.embed_documents.return_value = [[0.1]]
        mock_collection.insert_one.return_value = Mock(inserted_id="id")

        store.add_chunk("text")

        inserted = mock_collection.insert_one.call_args[0][0]
        assert "source_id" in inserted

    def test_add_chunk_raises_on_empty_embedding(self):
        store, _, mock_emb = _make_mongodb_store()
        mock_emb.embed_documents.return_value = []

        with pytest.raises(ValueError, match="Could not generate embedding"):
            store.add_chunk("text")


@pytest.mark.unit
class TestMongoDBVectorStoreDeleteChunk:
    def test_delete_chunk_success(self):
        store, mock_collection, _ = _make_mongodb_store()
        mock_collection.delete_one.return_value = Mock(deleted_count=1)

        with patch("application.vectorstore.mongodb.ObjectId", create=True):
            # We need to mock bson.objectid.ObjectId
            with patch.dict("sys.modules", {"bson": MagicMock(), "bson.objectid": MagicMock()}):
                from unittest.mock import MagicMock as MM
                mock_oid = MM()
                with patch(
                    "bson.objectid.ObjectId", return_value=mock_oid
                ):
                    result = store.delete_chunk("507f1f77bcf86cd799439011")

        assert result is True

    def test_delete_chunk_returns_false_on_error(self):
        store, mock_collection, _ = _make_mongodb_store()
        mock_collection.delete_one.side_effect = Exception("fail")

        result = store.delete_chunk("bad_id")
        assert result is False
