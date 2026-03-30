import io
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def mock_embeddings():
    emb = Mock()
    emb.embed_query = Mock(return_value=[0.1, 0.2, 0.3])
    emb.embed_documents = Mock(return_value=[[0.1, 0.2, 0.3]])
    emb.dimension = 3
    return emb


@pytest.fixture
def mock_storage():
    storage = Mock()
    storage.file_exists = Mock(return_value=True)
    storage.get_file = Mock(return_value=io.BytesIO(b"fake data"))
    storage.save_file = Mock()
    return storage


@pytest.fixture
def mock_docsearch():
    ds = Mock()
    ds.similarity_search = Mock(return_value=[])
    ds.add_texts = Mock(return_value=["id1"])
    ds.add_documents = Mock(return_value=["id1"])
    ds.save_local = Mock()
    ds.delete = Mock()
    ds.index = Mock()
    ds.index.d = 3
    ds.docstore = Mock()
    ds.docstore._dict = {
        "doc1": Mock(page_content="text1", metadata={"source": "a"}),
        "doc2": Mock(page_content="text2", metadata={"source": "b"}),
    }
    return ds


@pytest.mark.unit
class TestFaissStoreInit:
    @patch("application.vectorstore.faiss.StorageCreator")
    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__("application.vectorstore.base", fromlist=["BaseVectorStore"]).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_init_with_docs(self, mock_settings, mock_get_emb, mock_faiss, mock_storage_creator):
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_emb = Mock(dimension=3)
        mock_get_emb.return_value = mock_emb
        mock_ds = Mock()
        mock_ds.index = Mock(d=3)
        mock_faiss.from_documents.return_value = mock_ds
        mock_storage_creator.get_storage.return_value = Mock()

        from application.vectorstore.faiss import FaissStore

        store = FaissStore(source_id="test", embeddings_key="key", docs_init=[Mock()])
        mock_faiss.from_documents.assert_called_once()
        assert store.docsearch is mock_ds

    @patch("application.vectorstore.faiss.StorageCreator")
    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__("application.vectorstore.base", fromlist=["BaseVectorStore"]).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_init_missing_index_files(
        self, mock_settings, mock_get_emb, mock_faiss, mock_storage_creator
    ):
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_emb = Mock(dimension=3)
        mock_get_emb.return_value = mock_emb
        mock_storage = Mock()
        mock_storage.file_exists.return_value = False
        mock_storage_creator.get_storage.return_value = mock_storage

        from application.vectorstore.faiss import FaissStore

        with pytest.raises(Exception, match="Error loading FAISS index"):
            FaissStore(source_id="test", embeddings_key="key")


@pytest.mark.unit
class TestFaissStoreSearch:
    @patch("application.vectorstore.faiss.StorageCreator")
    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__("application.vectorstore.base", fromlist=["BaseVectorStore"]).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_search_delegates_to_docsearch(
        self, mock_settings, mock_get_emb, mock_faiss, mock_storage_creator
    ):
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_emb = Mock(dimension=3)
        mock_get_emb.return_value = mock_emb
        mock_ds = Mock()
        mock_ds.index = Mock(d=3)
        mock_ds.similarity_search.return_value = ["doc1"]
        mock_faiss.from_documents.return_value = mock_ds
        mock_storage_creator.get_storage.return_value = Mock()

        from application.vectorstore.faiss import FaissStore

        store = FaissStore(source_id="t", embeddings_key="k", docs_init=[Mock()])
        result = store.search("query", k=5)
        mock_ds.similarity_search.assert_called_once_with("query", k=5)
        assert result == ["doc1"]


@pytest.mark.unit
class TestFaissStoreAddTexts:
    @patch("application.vectorstore.faiss.StorageCreator")
    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__("application.vectorstore.base", fromlist=["BaseVectorStore"]).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_add_texts_delegates(
        self, mock_settings, mock_get_emb, mock_faiss, mock_storage_creator
    ):
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_emb = Mock(dimension=3)
        mock_get_emb.return_value = mock_emb
        mock_ds = Mock()
        mock_ds.index = Mock(d=3)
        mock_ds.add_texts.return_value = ["id1", "id2"]
        mock_faiss.from_documents.return_value = mock_ds
        mock_storage_creator.get_storage.return_value = Mock()

        from application.vectorstore.faiss import FaissStore

        store = FaissStore(source_id="t", embeddings_key="k", docs_init=[Mock()])
        result = store.add_texts(["text1", "text2"])
        assert result == ["id1", "id2"]


@pytest.mark.unit
class TestFaissStoreGetChunks:
    @patch("application.vectorstore.faiss.StorageCreator")
    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__("application.vectorstore.base", fromlist=["BaseVectorStore"]).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_get_chunks(self, mock_settings, mock_get_emb, mock_faiss, mock_storage_creator):
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_emb = Mock(dimension=3)
        mock_get_emb.return_value = mock_emb

        doc1 = Mock(page_content="text1", metadata={"source": "a"})
        doc2 = Mock(page_content="text2", metadata={"source": "b"})

        mock_ds = Mock()
        mock_ds.index = Mock(d=3)
        mock_ds.docstore._dict = {"id1": doc1, "id2": doc2}
        mock_faiss.from_documents.return_value = mock_ds
        mock_storage_creator.get_storage.return_value = Mock()

        from application.vectorstore.faiss import FaissStore

        store = FaissStore(source_id="t", embeddings_key="k", docs_init=[Mock()])
        chunks = store.get_chunks()

        assert len(chunks) == 2
        texts = {c["text"] for c in chunks}
        assert texts == {"text1", "text2"}

    @patch("application.vectorstore.faiss.StorageCreator")
    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__("application.vectorstore.base", fromlist=["BaseVectorStore"]).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_get_chunks_empty(self, mock_settings, mock_get_emb, mock_faiss, mock_storage_creator):
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_emb = Mock(dimension=3)
        mock_get_emb.return_value = mock_emb
        mock_ds = Mock()
        mock_ds.index = Mock(d=3)
        mock_ds.docstore._dict = {}
        mock_faiss.from_documents.return_value = mock_ds
        mock_storage_creator.get_storage.return_value = Mock()

        from application.vectorstore.faiss import FaissStore

        store = FaissStore(source_id="t", embeddings_key="k", docs_init=[Mock()])
        assert store.get_chunks() == []


@pytest.mark.unit
class TestFaissStoreSaveLocal:
    @patch("application.vectorstore.faiss.StorageCreator")
    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__("application.vectorstore.base", fromlist=["BaseVectorStore"]).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_save_local_with_path(
        self, mock_settings, mock_get_emb, mock_faiss, mock_storage_creator
    ):
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_emb = Mock(dimension=3)
        mock_get_emb.return_value = mock_emb
        mock_ds = Mock()
        mock_ds.index = Mock(d=3)
        mock_faiss.from_documents.return_value = mock_ds
        mock_storage = Mock()
        mock_storage_creator.get_storage.return_value = mock_storage

        from application.vectorstore.faiss import FaissStore

        store = FaissStore(source_id="t", embeddings_key="k", docs_init=[Mock()])

        # Mock _save_to_storage to avoid file I/O
        store._save_to_storage = Mock(return_value=True)

        with patch("os.makedirs"):
            result = store.save_local(path="/tmp/test_save")

        mock_ds.save_local.assert_called_once_with("/tmp/test_save")
        store._save_to_storage.assert_called_once()
        assert result is True


@pytest.mark.unit
class TestFaissStoreDeleteIndex:
    @patch("application.vectorstore.faiss.StorageCreator")
    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__("application.vectorstore.base", fromlist=["BaseVectorStore"]).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_delete_index_delegates(
        self, mock_settings, mock_get_emb, mock_faiss, mock_storage_creator
    ):
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_emb = Mock(dimension=3)
        mock_get_emb.return_value = mock_emb
        mock_ds = Mock()
        mock_ds.index = Mock(d=3)
        mock_faiss.from_documents.return_value = mock_ds
        mock_storage_creator.get_storage.return_value = Mock()

        from application.vectorstore.faiss import FaissStore

        store = FaissStore(source_id="t", embeddings_key="k", docs_init=[Mock()])
        store.delete_index(["id1"])
        mock_ds.delete.assert_called_once_with(["id1"])


@pytest.mark.unit
class TestFaissStoreAssertEmbeddingDimensions:
    @patch("application.vectorstore.faiss.StorageCreator")
    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__("application.vectorstore.base", fromlist=["BaseVectorStore"]).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_dimension_mismatch_raises(
        self, mock_settings, mock_get_emb, mock_faiss, mock_storage_creator
    ):
        mock_settings.EMBEDDINGS_NAME = (
            "huggingface_sentence-transformers/all-mpnet-base-v2"
        )
        mock_emb = Mock(dimension=768)
        mock_get_emb.return_value = mock_emb
        mock_ds = Mock()
        mock_ds.index = Mock(d=512)  # Mismatched dimension
        mock_faiss.from_documents.return_value = mock_ds
        mock_storage_creator.get_storage.return_value = Mock()

        from application.vectorstore.faiss import FaissStore

        with pytest.raises(ValueError, match="Embedding dimension mismatch"):
            FaissStore(source_id="t", embeddings_key="k", docs_init=[Mock()])

    @patch("application.vectorstore.faiss.StorageCreator")
    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__("application.vectorstore.base", fromlist=["BaseVectorStore"]).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_missing_dimension_attr_raises(
        self, mock_settings, mock_get_emb, mock_faiss, mock_storage_creator
    ):
        mock_settings.EMBEDDINGS_NAME = (
            "huggingface_sentence-transformers/all-mpnet-base-v2"
        )
        mock_emb = Mock(spec=[])  # No dimension attribute
        mock_get_emb.return_value = mock_emb
        mock_ds = Mock()
        mock_ds.index = Mock(d=768)
        mock_faiss.from_documents.return_value = mock_ds
        mock_storage_creator.get_storage.return_value = Mock()

        from application.vectorstore.faiss import FaissStore

        with pytest.raises(AttributeError, match="dimension"):
            FaissStore(source_id="t", embeddings_key="k", docs_init=[Mock()])


@pytest.mark.unit
class TestFaissStoreDeleteChunk:
    @patch("application.vectorstore.faiss.StorageCreator")
    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__("application.vectorstore.base", fromlist=["BaseVectorStore"]).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_delete_chunk(self, mock_settings, mock_get_emb, mock_faiss, mock_storage_creator):
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_emb = Mock(dimension=3)
        mock_get_emb.return_value = mock_emb
        mock_ds = Mock()
        mock_ds.index = Mock(d=3)
        mock_faiss.from_documents.return_value = mock_ds
        mock_storage = Mock()
        mock_storage_creator.get_storage.return_value = mock_storage

        from application.vectorstore.faiss import FaissStore

        store = FaissStore(source_id="t", embeddings_key="k", docs_init=[Mock()])
        store._save_to_storage = Mock(return_value=True)

        result = store.delete_chunk("chunk_id")
        mock_ds.delete.assert_called_once_with(["chunk_id"])
        store._save_to_storage.assert_called_once()
        assert result is True


@pytest.mark.unit
class TestGetVectorstore:
    def test_with_path(self):
        from application.vectorstore.faiss import get_vectorstore

        assert get_vectorstore("abc123") == "indexes/abc123"

    def test_without_path(self):
        from application.vectorstore.faiss import get_vectorstore

        assert get_vectorstore("") == "indexes"
        assert get_vectorstore(None) == "indexes"

    def test_with_nested_path(self):
        from application.vectorstore.faiss import get_vectorstore

        assert get_vectorstore("user/source123") == "indexes/user/source123"


@pytest.mark.unit
class TestFaissStoreAddChunk:
    @patch("application.vectorstore.faiss.StorageCreator")
    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__("application.vectorstore.base", fromlist=["BaseVectorStore"]).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_add_chunk_with_metadata(
        self, mock_settings, mock_get_emb, mock_faiss, mock_storage_creator
    ):
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_emb = Mock(dimension=3)
        mock_get_emb.return_value = mock_emb
        mock_ds = Mock()
        mock_ds.index = Mock(d=3)
        mock_ds.add_documents.return_value = ["new_id"]
        mock_faiss.from_documents.return_value = mock_ds
        mock_storage = Mock()
        mock_storage_creator.get_storage.return_value = mock_storage

        from application.vectorstore.faiss import FaissStore

        store = FaissStore(source_id="t", embeddings_key="k", docs_init=[Mock()])
        store._save_to_storage = Mock(return_value=True)

        doc_id = store.add_chunk("new text", metadata={"source": "test"})

        assert doc_id == ["new_id"]
        mock_ds.add_documents.assert_called_once()
        store._save_to_storage.assert_called_once()

    @patch("application.vectorstore.faiss.StorageCreator")
    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__("application.vectorstore.base", fromlist=["BaseVectorStore"]).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_add_chunk_default_metadata(
        self, mock_settings, mock_get_emb, mock_faiss, mock_storage_creator
    ):
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_emb = Mock(dimension=3)
        mock_get_emb.return_value = mock_emb
        mock_ds = Mock()
        mock_ds.index = Mock(d=3)
        mock_ds.add_documents.return_value = ["new_id"]
        mock_faiss.from_documents.return_value = mock_ds
        mock_storage = Mock()
        mock_storage_creator.get_storage.return_value = mock_storage

        from application.vectorstore.faiss import FaissStore

        store = FaissStore(source_id="t", embeddings_key="k", docs_init=[Mock()])
        store._save_to_storage = Mock(return_value=True)

        doc_id = store.add_chunk("new text")

        assert doc_id == ["new_id"]


@pytest.mark.unit
class TestFaissStoreSaveLocalNoPath:
    @patch("application.vectorstore.faiss.StorageCreator")
    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__("application.vectorstore.base", fromlist=["BaseVectorStore"]).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_save_local_without_path(
        self, mock_settings, mock_get_emb, mock_faiss, mock_storage_creator
    ):
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_emb = Mock(dimension=3)
        mock_get_emb.return_value = mock_emb
        mock_ds = Mock()
        mock_ds.index = Mock(d=3)
        mock_faiss.from_documents.return_value = mock_ds
        mock_storage = Mock()
        mock_storage_creator.get_storage.return_value = mock_storage

        from application.vectorstore.faiss import FaissStore

        store = FaissStore(source_id="t", embeddings_key="k", docs_init=[Mock()])
        store._save_to_storage = Mock(return_value=True)

        result = store.save_local()

        # Should NOT call docsearch.save_local with a path
        mock_ds.save_local.assert_not_called()
        store._save_to_storage.assert_called_once()
        assert result is True


@pytest.mark.unit
class TestFaissStoreAssertEmbeddingDimensionsMatch:
    @patch("application.vectorstore.faiss.StorageCreator")
    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__("application.vectorstore.base", fromlist=["BaseVectorStore"]).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_dimension_match_passes(
        self, mock_settings, mock_get_emb, mock_faiss, mock_storage_creator
    ):
        mock_settings.EMBEDDINGS_NAME = (
            "huggingface_sentence-transformers/all-mpnet-base-v2"
        )
        mock_emb = Mock(dimension=768)
        mock_get_emb.return_value = mock_emb
        mock_ds = Mock()
        mock_ds.index = Mock(d=768)  # Matching dimension
        mock_faiss.from_documents.return_value = mock_ds
        mock_storage_creator.get_storage.return_value = Mock()

        from application.vectorstore.faiss import FaissStore

        # Should not raise
        store = FaissStore(source_id="t", embeddings_key="k", docs_init=[Mock()])
        assert store is not None

    @patch("application.vectorstore.faiss.StorageCreator")
    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__("application.vectorstore.base", fromlist=["BaseVectorStore"]).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_non_huggingface_skips_dimension_check(
        self, mock_settings, mock_get_emb, mock_faiss, mock_storage_creator
    ):
        mock_settings.EMBEDDINGS_NAME = "openai_text-embedding-ada-002"
        mock_emb = Mock(dimension=1536)
        mock_get_emb.return_value = mock_emb
        mock_ds = Mock()
        mock_ds.index = Mock(d=999)  # Mismatched but doesn't matter
        mock_faiss.from_documents.return_value = mock_ds
        mock_storage_creator.get_storage.return_value = Mock()

        from application.vectorstore.faiss import FaissStore

        # Should not raise since embedding name is not the huggingface one
        store = FaissStore(source_id="t", embeddings_key="k", docs_init=[Mock()])
        assert store is not None
