from unittest.mock import MagicMock, Mock, patch

import pytest


def _make_lancedb_store(source_id="test-source"):
    """Helper to create a LanceDBVectorStore with mocked deps."""
    with patch(
        "application.vectorstore.lancedb.settings"
    ) as mock_settings:
        mock_settings.LANCEDB_PATH = "/tmp/lancedb"
        mock_settings.LANCEDB_TABLE_NAME = "docs"
        mock_settings.EMBEDDINGS_NAME = "test_model"

        from application.vectorstore.lancedb import LanceDBVectorStore

        store = LanceDBVectorStore(
            path="/tmp/lancedb",
            table_name_prefix="docs",
            source_id=source_id,
            embeddings_key="key",
        )

        return store, mock_settings


@pytest.mark.unit
class TestLanceDBVectorStoreInit:
    def test_table_name_with_source_id(self):
        store, _ = _make_lancedb_store(source_id="src1")
        assert store.table_name == "docs_src1"

    def test_table_name_without_source_id(self):
        with patch("application.vectorstore.lancedb.settings") as mock_settings:
            mock_settings.LANCEDB_PATH = "/tmp"
            mock_settings.LANCEDB_TABLE_NAME = "docs"

            from application.vectorstore.lancedb import LanceDBVectorStore

            store = LanceDBVectorStore(
                path="/tmp", table_name_prefix="docs", source_id=None
            )
            assert store.table_name == "docs"

    def test_init_defaults(self):
        store, _ = _make_lancedb_store()
        assert store.path == "/tmp/lancedb"
        assert store._lance_db is None
        assert store.docsearch is None


@pytest.mark.unit
class TestLanceDBVectorStoreLazyLoading:
    def test_pa_lazy_load(self):
        store, _ = _make_lancedb_store()
        mock_pa = MagicMock()

        with patch("importlib.import_module", return_value=mock_pa) as mock_import:
            result = store.pa
            mock_import.assert_called_with("pyarrow")
            assert result is mock_pa

    def test_pa_cached(self):
        store, _ = _make_lancedb_store()
        mock_pa = MagicMock()
        store._pa = mock_pa

        assert store.pa is mock_pa

    def test_lancedb_lazy_load(self):
        store, _ = _make_lancedb_store()
        mock_ldb = MagicMock()

        with patch("importlib.import_module", return_value=mock_ldb) as mock_import:
            result = store.lancedb
            mock_import.assert_called_with("lancedb")
            assert result is mock_ldb

    def test_lance_db_connection(self):
        store, _ = _make_lancedb_store()
        mock_ldb_module = MagicMock()
        mock_conn = MagicMock()
        mock_ldb_module.connect.return_value = mock_conn
        store._lancedb_module = mock_ldb_module

        result = store.lance_db
        mock_ldb_module.connect.assert_called_once_with("/tmp/lancedb")
        assert result is mock_conn

    def test_lance_db_cached(self):
        store, _ = _make_lancedb_store()
        mock_conn = MagicMock()
        store._lance_db = mock_conn

        assert store.lance_db is mock_conn

    def test_table_opens_existing(self):
        store, _ = _make_lancedb_store()
        mock_conn = MagicMock()
        mock_table = MagicMock()
        mock_conn.table_names.return_value = [store.table_name]
        mock_conn.open_table.return_value = mock_table
        store._lance_db = mock_conn

        result = store.table
        mock_conn.open_table.assert_called_once_with(store.table_name)
        assert result is mock_table

    def test_table_returns_none_for_missing(self):
        store, _ = _make_lancedb_store()
        mock_conn = MagicMock()
        mock_conn.table_names.return_value = []
        store._lance_db = mock_conn

        result = store.table
        assert result is None


@pytest.mark.unit
class TestLanceDBVectorStoreEnsureTableExists:
    def test_creates_table_when_missing(self):
        store, _ = _make_lancedb_store()
        mock_conn = MagicMock()
        mock_conn.table_names.return_value = []
        store._lance_db = mock_conn

        mock_emb = MagicMock()
        mock_emb.dimension = 768
        mock_pa = MagicMock()
        store._pa = mock_pa

        with patch.object(store, "_get_embeddings", return_value=mock_emb):
            store.ensure_table_exists()

        mock_conn.create_table.assert_called_once()

    def test_noop_when_table_exists(self):
        store, _ = _make_lancedb_store()
        mock_table = MagicMock()
        store.docsearch = mock_table
        mock_conn = MagicMock()
        mock_conn.table_names.return_value = [store.table_name]
        mock_conn.open_table.return_value = mock_table
        store._lance_db = mock_conn

        store.ensure_table_exists()
        mock_conn.create_table.assert_not_called()


@pytest.mark.unit
class TestLanceDBVectorStoreAddTexts:
    def test_add_texts(self):
        store, _ = _make_lancedb_store()
        mock_table = MagicMock()
        store.docsearch = mock_table

        mock_emb = MagicMock()
        mock_emb.embed_documents.return_value = [[0.1, 0.2], [0.3, 0.4]]

        with patch.object(store, "_get_embeddings", return_value=mock_emb), patch.object(
            store, "ensure_table_exists"
        ):
            store.add_texts(
                ["text1", "text2"],
                metadatas=[{"a": "1"}, {"b": "2"}],
                source_id="src1",
            )

        mock_table.add.assert_called_once()
        vectors = mock_table.add.call_args[0][0]
        assert len(vectors) == 2
        assert vectors[0]["text"] == "text1"
        assert vectors[0]["vector"] == [0.1, 0.2]

    def test_add_texts_with_source_id_in_metadata(self):
        store, _ = _make_lancedb_store()
        mock_table = MagicMock()
        store.docsearch = mock_table

        mock_emb = MagicMock()
        mock_emb.embed_documents.return_value = [[0.1]]

        with patch.object(store, "_get_embeddings", return_value=mock_emb), patch.object(
            store, "ensure_table_exists"
        ):
            store.add_texts(["text1"], metadatas=[{"k": "v"}], source_id="src1")

        vectors = mock_table.add.call_args[0][0]
        metadata_keys = [m["key"] for m in vectors[0]["metadata"]]
        assert "source_id" in metadata_keys

    def test_add_texts_default_metadata(self):
        store, _ = _make_lancedb_store()
        mock_table = MagicMock()
        store.docsearch = mock_table

        mock_emb = MagicMock()
        mock_emb.embed_documents.return_value = [[0.1]]

        with patch.object(store, "_get_embeddings", return_value=mock_emb), patch.object(
            store, "ensure_table_exists"
        ):
            store.add_texts(["text1"])

        mock_table.add.assert_called_once()


@pytest.mark.unit
class TestLanceDBVectorStoreSearch:
    def test_search(self):
        store, _ = _make_lancedb_store()
        mock_table = MagicMock()
        store.docsearch = mock_table

        mock_emb = MagicMock()
        mock_emb.embed_query.return_value = [0.1, 0.2]

        mock_result = MagicMock()
        mock_result.limit.return_value.to_list.return_value = [
            {"_distance": 0.1, "text": "result1", "metadata": {"k": "v"}},
        ]
        mock_table.search.return_value = mock_result

        with patch.object(store, "_get_embeddings", return_value=mock_emb), patch.object(
            store, "ensure_table_exists"
        ):
            results = store.search("query", k=3)

        assert len(results) == 1
        assert results[0][1] == "result1"
        mock_result.limit.assert_called_once_with(3)


@pytest.mark.unit
class TestLanceDBVectorStoreDeleteIndex:
    def test_delete_index_drops_table(self):
        store, _ = _make_lancedb_store()
        mock_table = MagicMock()
        store.docsearch = mock_table
        mock_conn = MagicMock()
        mock_conn.table_names.return_value = [store.table_name]
        mock_conn.open_table.return_value = mock_table
        store._lance_db = mock_conn

        store.delete_index()

        mock_conn.drop_table.assert_called_once_with(store.table_name)

    def test_delete_index_noop_when_no_table(self):
        store, _ = _make_lancedb_store()
        store.docsearch = None
        mock_conn = MagicMock()
        mock_conn.table_names.return_value = []
        store._lance_db = mock_conn

        store.delete_index()
        mock_conn.drop_table.assert_not_called()


@pytest.mark.unit
class TestLanceDBVectorStoreAssertEmbeddingDimensions:
    def test_matching_dimensions(self):
        store, _ = _make_lancedb_store()
        mock_table = MagicMock()
        mock_table.schema = {"vector": MagicMock()}
        mock_table.schema["vector"].type.value_type.__len__ = Mock(return_value=768)
        store.docsearch = mock_table

        mock_emb = MagicMock()
        mock_emb.dimension = 768

        # Should not raise
        store.assert_embedding_dimensions(mock_emb)

    def test_mismatched_dimensions_raises(self):
        store, _ = _make_lancedb_store()
        mock_table = MagicMock()
        store.docsearch = mock_table

        type_mock = MagicMock()
        type_mock.__len__ = Mock(return_value=512)
        mock_table.schema.__getitem__ = Mock(return_value=MagicMock())
        mock_table.schema["vector"].type.value_type = type_mock

        mock_emb = MagicMock()
        mock_emb.dimension = 768

        with pytest.raises(ValueError, match="Embedding dimension mismatch"):
            store.assert_embedding_dimensions(mock_emb)


@pytest.mark.unit
class TestLanceDBVectorStoreFilterDocuments:
    def test_filter_documents(self):
        store, _ = _make_lancedb_store()
        mock_table = MagicMock()
        mock_table.filter.return_value.to_list.return_value = [{"text": "filtered"}]
        store.docsearch = mock_table

        with patch.object(store, "ensure_table_exists"):
            results = store.filter_documents({"source_id": "src1"})

        assert len(results) == 1

    def test_filter_documents_requires_source_id(self):
        store, _ = _make_lancedb_store()
        mock_table = MagicMock()
        store.docsearch = mock_table

        with patch.object(store, "ensure_table_exists"):
            with pytest.raises(ValueError, match="must contain 'source_id'"):
                store.filter_documents({"other_key": "value"})
