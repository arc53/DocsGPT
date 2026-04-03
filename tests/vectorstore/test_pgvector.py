from unittest.mock import MagicMock, Mock, patch

import pytest


def _make_store(
    source_id="test-source",
    embeddings_key="key",
    connection_string="postgresql://user:pass@localhost/db",
):
    """Helper to create a PGVectorStore with all external deps mocked."""
    with patch(
        "application.vectorstore.base.BaseVectorStore._get_embeddings"
    ) as mock_get_emb, patch(
        "application.vectorstore.pgvector.settings"
    ) as mock_settings, patch.dict(
        "sys.modules",
        {
            "psycopg2": MagicMock(),
            "psycopg2.extras": MagicMock(),
            "pgvector": MagicMock(),
            "pgvector.psycopg2": MagicMock(),
        },
    ):
        mock_emb = Mock()
        mock_emb.embed_query = Mock(return_value=[0.1, 0.2, 0.3])
        mock_emb.embed_documents = Mock(return_value=[[0.1, 0.2, 0.3]])
        mock_emb.dimension = 768
        mock_get_emb.return_value = mock_emb
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_settings.PGVECTOR_CONNECTION_STRING = connection_string

        from application.vectorstore.pgvector import PGVectorStore

        # Patch _ensure_table_exists to avoid DB calls during init
        with patch.object(PGVectorStore, "_ensure_table_exists"):
            store = PGVectorStore(
                source_id=source_id,
                embeddings_key=embeddings_key,
                connection_string=connection_string,
            )
        # Provide a mock connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.closed = False
        store._connection = mock_conn

        return store, mock_conn, mock_cursor, mock_emb


@pytest.mark.unit
class TestPGVectorStoreInit:
    def test_source_id_cleaned(self):
        store, _, _, _ = _make_store(source_id="application/indexes/abc123/")
        assert store._source_id == "abc123"

    def test_missing_connection_string_raises(self):
        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings"
        ) as mock_get_emb, patch(
            "application.vectorstore.pgvector.settings"
        ) as mock_settings, patch.dict(
            "sys.modules",
            {
                "psycopg2": MagicMock(),
                "psycopg2.extras": MagicMock(),
                "pgvector": MagicMock(),
                "pgvector.psycopg2": MagicMock(),
            },
        ):
            mock_get_emb.return_value = Mock(dimension=768)
            mock_settings.EMBEDDINGS_NAME = "test_model"
            mock_settings.PGVECTOR_CONNECTION_STRING = None

            from application.vectorstore.pgvector import PGVectorStore

            with pytest.raises(ValueError, match="connection string is required"):
                PGVectorStore(
                    source_id="test", embeddings_key="key", connection_string=None
                )


@pytest.mark.unit
class TestPGVectorStoreSearch:
    def test_search_returns_documents(self):
        store, mock_conn, mock_cursor, mock_emb = _make_store()
        mock_cursor.fetchall.return_value = [
            ("hello world", {"source": "test.txt"}, 0.1),
            ("foo bar", {"source": "test2.txt"}, 0.2),
        ]

        results = store.search("query", k=2)

        mock_emb.embed_query.assert_called_once_with("query")
        assert len(results) == 2
        assert results[0].page_content == "hello world"
        assert results[0].metadata == {"source": "test.txt"}

    def test_search_returns_empty_on_error(self):
        store, mock_conn, mock_cursor, _ = _make_store()
        mock_cursor.execute.side_effect = Exception("connection lost")

        results = store.search("query")
        assert results == []

    def test_search_handles_null_metadata(self):
        store, _, mock_cursor, _ = _make_store()
        mock_cursor.fetchall.return_value = [("text", None, 0.5)]

        results = store.search("query")
        assert len(results) == 1
        assert results[0].metadata == {}


@pytest.mark.unit
class TestPGVectorStoreAddTexts:
    def test_add_texts_inserts_and_returns_ids(self):
        store, mock_conn, mock_cursor, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = [[0.1, 0.2], [0.3, 0.4]]
        mock_cursor.fetchone.side_effect = [(1,), (2,)]

        ids = store.add_texts(["text1", "text2"], [{"a": 1}, {"b": 2}])

        assert ids == ["1", "2"]
        assert mock_cursor.execute.call_count == 2
        mock_conn.commit.assert_called_once()

    def test_add_texts_empty_returns_empty(self):
        store, _, _, _ = _make_store()
        assert store.add_texts([]) == []

    def test_add_texts_default_metadatas(self):
        store, mock_conn, mock_cursor, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = [[0.1, 0.2]]
        mock_cursor.fetchone.return_value = (1,)

        ids = store.add_texts(["text1"])
        assert ids == ["1"]

    def test_add_texts_rolls_back_on_error(self):
        store, mock_conn, mock_cursor, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = [[0.1]]
        mock_cursor.execute.side_effect = Exception("insert failed")

        with pytest.raises(Exception, match="insert failed"):
            store.add_texts(["text1"])

        mock_conn.rollback.assert_called_once()


@pytest.mark.unit
class TestPGVectorStoreDeleteIndex:
    def test_delete_index_deletes_by_source_id(self):
        store, mock_conn, mock_cursor, _ = _make_store(source_id="src123")

        store.delete_index()

        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        assert "DELETE FROM" in sql
        assert mock_cursor.execute.call_args[0][1] == ("src123",)
        mock_conn.commit.assert_called_once()

    def test_delete_index_rolls_back_on_error(self):
        store, mock_conn, mock_cursor, _ = _make_store()
        mock_cursor.execute.side_effect = Exception("fail")

        with pytest.raises(Exception):
            store.delete_index()

        mock_conn.rollback.assert_called_once()


@pytest.mark.unit
class TestPGVectorStoreSaveLocal:
    def test_save_local_is_noop(self):
        store, _, _, _ = _make_store()
        assert store.save_local() is None


@pytest.mark.unit
class TestPGVectorStoreGetChunks:
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


@pytest.mark.unit
class TestPGVectorStoreAddChunk:
    def test_add_chunk(self):
        store, mock_conn, mock_cursor, mock_emb = _make_store(source_id="src1")
        mock_emb.embed_documents.return_value = [[0.1, 0.2]]
        mock_cursor.fetchone.return_value = (42,)

        chunk_id = store.add_chunk("hello", metadata={"key": "val"})

        assert chunk_id == "42"
        mock_conn.commit.assert_called_once()

    def test_add_chunk_raises_on_empty_embedding(self):
        store, _, _, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = []

        with pytest.raises(ValueError, match="Could not generate embedding"):
            store.add_chunk("text")

    def test_add_chunk_includes_source_id_in_metadata(self):
        store, mock_conn, mock_cursor, mock_emb = _make_store(source_id="src1")
        mock_emb.embed_documents.return_value = [[0.1, 0.2]]
        mock_cursor.fetchone.return_value = (1,)

        store.add_chunk("hello", metadata={"key": "val"})

        # Verify source_id is passed as a parameter to the INSERT
        insert_call = mock_cursor.execute.call_args
        params = insert_call[0][1]
        # source_id is the 4th param in the insert
        assert params[3] == "src1"


@pytest.mark.unit
class TestPGVectorStoreDeleteChunk:
    def test_delete_chunk_success(self):
        store, mock_conn, mock_cursor, _ = _make_store()
        mock_cursor.rowcount = 1

        result = store.delete_chunk("42")
        assert result is True
        mock_conn.commit.assert_called_once()

    def test_delete_chunk_not_found(self):
        store, mock_conn, mock_cursor, _ = _make_store()
        mock_cursor.rowcount = 0

        result = store.delete_chunk("999")
        assert result is False

    def test_delete_chunk_returns_false_on_error(self):
        store, _, mock_cursor, _ = _make_store()
        mock_cursor.execute.side_effect = Exception("fail")

        result = store.delete_chunk("42")
        assert result is False


@pytest.mark.unit
class TestPGVectorStoreConnection:
    def test_get_connection_creates_new_when_closed(self):
        store, mock_conn, _, _ = _make_store()
        mock_conn.closed = True

        mock_psycopg2 = MagicMock()
        new_conn = MagicMock()
        mock_psycopg2.connect.return_value = new_conn
        store._psycopg2 = mock_psycopg2

        conn = store._get_connection()
        mock_psycopg2.connect.assert_called_once()
        assert conn is new_conn

    def test_get_connection_reuses_open(self):
        store, mock_conn, _, _ = _make_store()
        mock_conn.closed = False

        conn = store._get_connection()
        assert conn is mock_conn

    def test_ensure_table_exists(self):
        store, mock_conn, mock_cursor, _ = _make_store()
        # Call _ensure_table_exists directly
        store._ensure_table_exists()

        # Should execute CREATE EXTENSION, CREATE TABLE, and CREATE INDEX statements
        assert mock_cursor.execute.call_count >= 3
        mock_conn.commit.assert_called()

    def test_del_closes_connection(self):
        store, mock_conn, _, _ = _make_store()
        mock_conn.closed = False

        store.__del__()
        mock_conn.close.assert_called_once()
