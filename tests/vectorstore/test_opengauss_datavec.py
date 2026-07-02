from unittest.mock import MagicMock, Mock, patch

import pytest

from application.vectorstore.opengauss_datavec import OpenGaussDataVecStore


def _make_store(source_id="test-source", embeddings_key="key"):
    """Create an OpenGaussDataVecStore with all external deps mocked."""
    mock_emb = Mock()
    mock_emb.embed_query = Mock(return_value=[0.1, 0.2, 0.3])
    mock_emb.embed_documents = Mock(return_value=[[0.1, 0.2, 0.3]])
    mock_emb.dimension = 768

    with patch.object(OpenGaussDataVecStore, "_load_driver"), \
         patch(
             "application.vectorstore.base.BaseVectorStore._get_embeddings",
             return_value=mock_emb,
         ), \
         patch(
             "application.vectorstore.opengauss_datavec.settings"
         ) as mock_settings, \
         patch.object(OpenGaussDataVecStore, "_ensure_table_exists"):

        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_settings.OPENGAUSS_CONNECTION_STRING = "host=localhost dbname=test"

        store = OpenGaussDataVecStore(
            source_id=source_id, embeddings_key=embeddings_key
        )

    # Set driver mocks as instance attrs (won't leak to other tests)
    store._sql = MagicMock()
    store._pg_extras = MagicMock()

    # Wire up mock connection
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
    store._get_connection = Mock(return_value=mock_conn)

    return store, mock_conn, mock_cursor, mock_emb


@pytest.mark.unit
class TestOpenGaussDataVecStoreInit:
    def test_source_id_stored_as_is(self):
        store, _, _, _ = _make_store(source_id="abc123")
        assert store._source_id == "abc123"

    def test_missing_connection_string_raises(self):
        mock_emb = Mock(dimension=768, embed_query=Mock(return_value=[0.1, 0.2, 0.3]))

        with patch.object(OpenGaussDataVecStore, "_load_driver"), \
             patch(
                 "application.vectorstore.base.BaseVectorStore._get_embeddings",
                 return_value=mock_emb,
             ), \
             patch(
                 "application.vectorstore.opengauss_datavec.settings"
             ) as mock_settings:

            mock_settings.EMBEDDINGS_NAME = "test_model"
            mock_settings.OPENGAUSS_CONNECTION_STRING = None

            with pytest.raises(ValueError, match="OPENGAUSS_CONNECTION_STRING"):
                OpenGaussDataVecStore(source_id="test", embeddings_key="key")


@pytest.mark.unit
class TestOpenGaussDataVecStoreSearch:
    def test_search_returns_documents(self):
        store, _, mock_cursor, mock_emb = _make_store()
        mock_cursor.fetchall.return_value = [
            ("hello world", {"source": "test.txt"}),
            ("foo bar", {"source": "test2.txt"}),
        ]

        results = store.search("query", k=2)

        mock_emb.embed_query.assert_called_with("query")
        assert len(results) == 2
        assert results[0].page_content == "hello world"
        assert results[0].metadata == {"source": "test.txt"}

    def test_search_returns_empty_on_error(self):
        store, _, mock_cursor, _ = _make_store()
        mock_cursor.execute.side_effect = Exception("connection lost")

        results = store.search("query")
        assert results == []

    def test_search_handles_null_metadata(self):
        store, _, mock_cursor, _ = _make_store()
        mock_cursor.fetchall.return_value = [("text", None)]

        results = store.search("query")
        assert len(results) == 1
        assert results[0].metadata == {}

    def test_search_handles_string_metadata(self):
        store, _, mock_cursor, _ = _make_store()
        mock_cursor.fetchall.return_value = [("text", '{"key": "val"}')]

        results = store.search("query")
        assert results[0].metadata == {"key": "val"}

    def test_search_filters_by_source_id(self):
        store, _, mock_cursor, _ = _make_store(source_id="src42")
        mock_cursor.fetchall.return_value = []

        store.search("query")

        params = mock_cursor.execute.call_args[0][1]
        assert params[0] == "src42"


@pytest.mark.unit
class TestOpenGaussDataVecStoreAddTexts:
    def test_add_texts_inserts_and_returns_ids(self):
        store, _, mock_cursor, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = [[0.1, 0.2], [0.3, 0.4]]
        mock_cursor.fetchall.return_value = [(1,), (2,)]

        ids = store.add_texts(["text1", "text2"], [{"a": 1}, {"b": 2}])

        assert ids == ["1", "2"]
        store._pg_extras.execute_values.assert_called_once()

    def test_add_texts_empty_returns_empty(self):
        store, _, _, _ = _make_store()
        assert store.add_texts([]) == []

    def test_add_texts_default_metadatas(self):
        store, _, mock_cursor, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = [[0.1, 0.2]]
        mock_cursor.fetchall.return_value = [(1,)]

        ids = store.add_texts(["text1"])
        assert ids == ["1"]

    def test_add_texts_passes_source_id(self):
        store, _, mock_cursor, mock_emb = _make_store(source_id="src99")
        mock_emb.embed_documents.return_value = [[0.1]]
        mock_cursor.fetchall.return_value = [(1,)]

        store.add_texts(["text1"])

        call_args = store._pg_extras.execute_values.call_args
        rows = call_args[0][2]
        assert rows[0][3] == "src99"


@pytest.mark.unit
class TestOpenGaussDataVecStoreDeleteIndex:
    def test_delete_index_called_with_source_id(self):
        store, _, mock_cursor, _ = _make_store(source_id="src123")

        store.delete_index()

        mock_cursor.execute.assert_called_once()
        params = mock_cursor.execute.call_args[0][1]
        assert params == ("src123",)


@pytest.mark.unit
class TestOpenGaussDataVecStoreSaveLocal:
    def test_save_local_is_noop(self):
        store, _, _, _ = _make_store()
        assert store.save_local() is None


@pytest.mark.unit
class TestOpenGaussDataVecStoreGetChunks:
    def test_get_chunks(self):
        store, _, mock_cursor, _ = _make_store()
        mock_cursor.fetchall.return_value = [
            (1, "text1", {"key": "val"}),
            (2, "text2", None),
        ]

        chunks = store.get_chunks()
        assert len(chunks) == 2
        assert chunks[0] == {"doc_id": "1", "text": "text1", "metadata": {"key": "val"}}
        assert chunks[1] == {"doc_id": "2", "text": "text2", "metadata": {}}

    def test_get_chunks_returns_empty_on_error(self):
        store, _, mock_cursor, _ = _make_store()
        mock_cursor.execute.side_effect = Exception("fail")

        assert store.get_chunks() == []

    def test_get_chunks_filters_by_source_id(self):
        store, _, mock_cursor, _ = _make_store(source_id="src7")
        mock_cursor.fetchall.return_value = []

        store.get_chunks()

        params = mock_cursor.execute.call_args[0][1]
        assert params == ("src7",)


@pytest.mark.unit
class TestOpenGaussDataVecStoreAddChunk:
    def test_add_chunk_delegates_to_add_texts(self):
        store, _, _, _ = _make_store()
        store.add_texts = Mock(return_value=["42"])

        chunk_id = store.add_chunk("hello", metadata={"key": "val"})

        assert chunk_id == "42"
        store.add_texts.assert_called_once_with(["hello"], [{"key": "val"}])

    def test_add_chunk_default_metadata(self):
        store, _, _, _ = _make_store()
        store.add_texts = Mock(return_value=["1"])

        store.add_chunk("text")

        store.add_texts.assert_called_once_with(["text"], [{}])

    def test_add_chunk_raises_on_empty_result(self):
        store, _, _, _ = _make_store()
        store.add_texts = Mock(return_value=[])

        with pytest.raises(IndexError):
            store.add_chunk("text")


@pytest.mark.unit
class TestOpenGaussDataVecStoreDeleteChunk:
    def test_delete_chunk_success(self):
        store, _, mock_cursor, _ = _make_store()
        mock_cursor.rowcount = 1

        result = store.delete_chunk("42")
        assert result is True

    def test_delete_chunk_not_found(self):
        store, _, mock_cursor, _ = _make_store()
        mock_cursor.rowcount = 0

        result = store.delete_chunk("999")
        assert result is False

    def test_delete_chunk_returns_false_on_error(self):
        store, _, mock_cursor, _ = _make_store()
        mock_cursor.execute.side_effect = Exception("fail")

        result = store.delete_chunk("42")
        assert result is False

    def test_delete_chunk_passes_int_id_and_source_id(self):
        store, _, mock_cursor, _ = _make_store(source_id="src5")
        mock_cursor.rowcount = 1

        store.delete_chunk("42")

        params = mock_cursor.execute.call_args[0][1]
        assert params == (42, "src5")


@pytest.mark.unit
class TestOpenGaussDataVecStoreEnsureTable:
    def _build_with_table(self, mock_emb):
        """Build a store WITHOUT patching _ensure_table_exists."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)

        with patch.object(OpenGaussDataVecStore, "_load_driver"), \
             patch.object(OpenGaussDataVecStore, "_psycopg2", MagicMock()), \
             patch.object(OpenGaussDataVecStore, "_sql", MagicMock()), \
             patch.object(OpenGaussDataVecStore, "_pg_extras", MagicMock()), \
             patch(
                 "application.vectorstore.base.BaseVectorStore._get_embeddings",
                 return_value=mock_emb,
             ), \
             patch(
                 "application.vectorstore.opengauss_datavec.settings"
             ) as mock_settings, \
             patch.object(
                 OpenGaussDataVecStore, "_get_connection", return_value=mock_conn
             ):

            mock_settings.EMBEDDINGS_NAME = "test_model"
            mock_settings.OPENGAUSS_CONNECTION_STRING = "host=localhost dbname=test"

            store = OpenGaussDataVecStore(source_id="test", embeddings_key="key")

        return store, mock_cursor

    def test_ensure_table_executes_create_statements(self):
        mock_emb = Mock(dimension=768, embed_query=Mock(return_value=[0.1, 0.2, 0.3]))
        _, mock_cursor = self._build_with_table(mock_emb)

        # CREATE TABLE + 2 indexes (ivfflat + source_id) = 3 execute calls
        assert mock_cursor.execute.call_count == 3

    def test_uses_actual_dimension_when_declared_is_wrong(self):
        mock_emb = Mock(dimension=768, embed_query=Mock(return_value=[0.1] * 1536))
        store, _ = self._build_with_table(mock_emb)

        assert store._embedding_dimension == 1536
        assert mock_emb.dimension == 1536

    def test_probes_when_dimension_missing(self):
        mock_emb = Mock(spec=["embed_query"])
        mock_emb.embed_query = Mock(return_value=[0.1, 0.2, 0.3, 0.4])
        store, _ = self._build_with_table(mock_emb)

        assert store._embedding_dimension == 4
