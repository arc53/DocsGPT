"""Unit tests for OracleVectorStore.

Follows the same mocking pattern as ``test_pgvector.py`` so that all
external dependencies (oracledb, settings) are replaced by MagicMock
objects.  No real Oracle database is required.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest


def _make_store(
    source_id="test-source",
    embeddings_key="key",
    user="test_user",
    password="test_pass",
    dsn="localhost:1521/xepdb1",
):
    """Helper to create an OracleVectorStore with all external deps mocked."""
    with patch(
        "application.vectorstore.base.BaseVectorStore._get_embeddings"
    ) as mock_get_emb, patch(
        "application.vectorstore.oracle.settings"
    ) as mock_settings, patch.dict(
        "sys.modules",
        {
            "oracledb": MagicMock(),
        },
    ):
        mock_emb = Mock()
        mock_emb.embed_query = Mock(return_value=[0.1, 0.2, 0.3])
        mock_emb.embed_documents = Mock(return_value=[[0.1, 0.2, 0.3]])
        mock_emb.dimension = 768
        mock_get_emb.return_value = mock_emb
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_settings.ORACLE_USER = user
        mock_settings.ORACLE_PASSWORD = password
        mock_settings.ORACLE_DSN = dsn
        mock_settings.ORACLE_CONNECTION_STRING = None

        from application.vectorstore.oracle import OracleVectorStore

        # Patch _ensure_table_exists to avoid DB calls during init
        with patch.object(OracleVectorStore, "_ensure_table_exists"):
            store = OracleVectorStore(
                source_id=source_id,
                embeddings_key=embeddings_key,
            )
        # Provide a mock connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        store._connection = mock_conn

        return store, mock_conn, mock_cursor, mock_emb


def _make_store_with_connection_string(
    source_id="test-source",
    embeddings_key="key",
    connection_string="test_user/test_pass@localhost:1521/xepdb1",
):
    """Helper using ORACLE_CONNECTION_STRING instead of individual params."""
    with patch(
        "application.vectorstore.base.BaseVectorStore._get_embeddings"
    ) as mock_get_emb, patch(
        "application.vectorstore.oracle.settings"
    ) as mock_settings, patch.dict(
        "sys.modules",
        {
            "oracledb": MagicMock(),
        },
    ):
        mock_emb = Mock()
        mock_emb.embed_query = Mock(return_value=[0.1, 0.2, 0.3])
        mock_emb.embed_documents = Mock(return_value=[[0.1, 0.2, 0.3]])
        mock_emb.dimension = 768
        mock_get_emb.return_value = mock_emb
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_settings.ORACLE_USER = None
        mock_settings.ORACLE_PASSWORD = None
        mock_settings.ORACLE_DSN = None
        mock_settings.ORACLE_CONNECTION_STRING = connection_string

        from application.vectorstore.oracle import OracleVectorStore

        with patch.object(OracleVectorStore, "_ensure_table_exists"):
            store = OracleVectorStore(
                source_id=source_id,
                embeddings_key=embeddings_key,
            )
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        store._connection = mock_conn

        return store, mock_conn, mock_cursor, mock_emb


# ---------------------------------------------------------------------------
# Init tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOracleVectorStoreInit:
    def test_source_id_cleaned(self):
        store, _, _, _ = _make_store(source_id="application/indexes/abc123/")
        assert store._source_id == "abc123"

    def test_missing_connection_params_raises(self):
        with patch(
            "application.vectorstore.base.BaseVectorStore._get_embeddings"
        ) as mock_get_emb, patch(
            "application.vectorstore.oracle.settings"
        ) as mock_settings, patch.dict(
            "sys.modules",
            {
                "oracledb": MagicMock(),
            },
        ):
            mock_get_emb.return_value = Mock(dimension=768)
            mock_settings.EMBEDDINGS_NAME = "test_model"
            mock_settings.ORACLE_USER = None
            mock_settings.ORACLE_PASSWORD = None
            mock_settings.ORACLE_DSN = None
            mock_settings.ORACLE_CONNECTION_STRING = None

            from application.vectorstore.oracle import OracleVectorStore

            with pytest.raises(ValueError, match="connection parameters are required"):
                OracleVectorStore(source_id="test", embeddings_key="key")

    def test_init_with_connection_string(self):
        """Initialisation via full connection string should succeed."""
        store, _, _, _ = _make_store_with_connection_string()
        assert store._source_id == "test-source"


# ---------------------------------------------------------------------------
# Search tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOracleVectorStoreSearch:
    def test_search_returns_documents(self):
        store, mock_conn, mock_cursor, mock_emb = _make_store()
        mock_cursor.fetchall.return_value = [
            ("hello world", '{"source": "test.txt"}', 0.1),
            ("foo bar", '{"source": "test2.txt"}', 0.2),
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

    def test_search_uses_cosine_distance(self):
        store, _, mock_cursor, _ = _make_store()
        mock_cursor.fetchall.return_value = [("text", None, 0.5)]

        store.search("query")

        sql = mock_cursor.execute.call_args[0][0]
        assert "VECTOR_DISTANCE" in sql
        assert "COSINE" in sql
        assert "FETCH FIRST" in sql


# ---------------------------------------------------------------------------
# add_texts tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOracleVectorStoreAddTexts:
    def test_add_texts_inserts_and_returns_ids(self):
        store, mock_conn, mock_cursor, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = [[0.1, 0.2], [0.3, 0.4]]

        # Simulate RETURNING id … INTO :rid
        def _side_effect(sql, **kwargs):
            rid_var = kwargs.get("rid")
            if rid_var is not None:
                # The mock oracledb cursor var returns (value,) via getvalue()
                call_idx = mock_cursor.execute.call_count
                rid_var.getvalue.return_value = (call_idx,)
            return MagicMock()

        mock_cursor.execute.side_effect = _side_effect
        mock_cursor.var = MagicMock(return_value=MagicMock())

        ids = store.add_texts(["text1", "text2"], [{"a": 1}, {"b": 2}])

        assert len(ids) == 2
        assert mock_cursor.execute.call_count == 2
        mock_conn.commit.assert_called_once()

    def test_add_texts_empty_returns_empty(self):
        store, _, _, _ = _make_store()
        assert store.add_texts([]) == []

    def test_add_texts_default_metadatas(self):
        store, mock_conn, mock_cursor, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = [[0.1, 0.2]]
        mock_cursor.var = MagicMock(return_value=MagicMock())

        ids = store.add_texts(["text1"])
        assert len(ids) == 1

    def test_add_texts_rolls_back_on_error(self):
        store, mock_conn, mock_cursor, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = [[0.1]]
        mock_cursor.execute.side_effect = Exception("insert failed")

        with pytest.raises(Exception, match="insert failed"):
            store.add_texts(["text1"])

        mock_conn.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# delete_index tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOracleVectorStoreDeleteIndex:
    def test_delete_index_deletes_by_source_id(self):
        store, mock_conn, mock_cursor, _ = _make_store(source_id="src123")

        store.delete_index()

        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        assert "DELETE FROM" in sql
        assert mock_cursor.execute.call_args[1]["sid"] == "src123"
        mock_conn.commit.assert_called_once()

    def test_delete_index_rolls_back_on_error(self):
        store, mock_conn, mock_cursor, _ = _make_store()
        mock_cursor.execute.side_effect = Exception("fail")

        with pytest.raises(Exception):
            store.delete_index()

        mock_conn.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# save_local tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOracleVectorStoreSaveLocal:
    def test_save_local_is_noop(self):
        store, _, _, _ = _make_store()
        assert store.save_local() is None


# ---------------------------------------------------------------------------
# get_chunks tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOracleVectorStoreGetChunks:
    def test_get_chunks(self):
        store, _, mock_cursor, _ = _make_store()
        mock_cursor.fetchall.return_value = [
            (1, "text1", '{"key": "val"}'),
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


# ---------------------------------------------------------------------------
# add_chunk tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOracleVectorStoreAddChunk:
    def test_add_chunk(self):
        store, mock_conn, mock_cursor, mock_emb = _make_store(source_id="src1")
        mock_emb.embed_documents.return_value = [[0.1, 0.2]]
        mock_cursor.var = MagicMock(return_value=MagicMock())

        chunk_id = store.add_chunk("hello", metadata={"key": "val"})

        assert chunk_id is not None
        mock_conn.commit.assert_called_once()

    def test_add_chunk_raises_on_empty_embedding(self):
        store, _, _, mock_emb = _make_store()
        mock_emb.embed_documents.return_value = []

        with pytest.raises(ValueError, match="Could not generate embedding"):
            store.add_chunk("text")

    def test_add_chunk_includes_source_id_in_metadata(self):
        store, mock_conn, mock_cursor, mock_emb = _make_store(source_id="src1")
        mock_emb.embed_documents.return_value = [[0.1, 0.2]]
        mock_cursor.var = MagicMock(return_value=MagicMock())

        store.add_chunk("hello", metadata={"key": "val"})

        # Verify source_id is passed as a bind parameter to the INSERT.
        insert_call = mock_cursor.execute.call_args
        params = insert_call[1]
        assert params["sid"] == "src1"


# ---------------------------------------------------------------------------
# delete_chunk tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOracleVectorStoreDeleteChunk:
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


# ---------------------------------------------------------------------------
# Connection management tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOracleVectorStoreConnection:
    def test_get_connection_creates_new(self):
        store, mock_conn, _, _ = _make_store()
        store._connection = None  # Force creation

        mock_oracledb = MagicMock()
        new_conn = MagicMock()
        mock_oracledb.connect.return_value = new_conn
        store._oracledb = mock_oracledb

        conn = store._get_connection()
        mock_oracledb.connect.assert_called_once()
        assert conn is new_conn

    def test_get_connection_reuses_existing(self):
        store, mock_conn, _, _ = _make_store()
        # Connection is already set by _make_store
        conn = store._get_connection()
        assert conn is mock_conn

    def test_get_connection_reconnects_on_failure(self):
        store, mock_conn, mock_cursor, _ = _make_store()
        # Make the existing connection throw on cursor()
        mock_conn.cursor.side_effect = Exception("ORA-03135: connection lost")

        mock_oracledb = MagicMock()
        new_conn = MagicMock()
        mock_oracledb.connect.return_value = new_conn
        store._oracledb = mock_oracledb

        conn = store._get_connection()
        # Should have tried reconnecting
        mock_oracledb.connect.assert_called_once()
        assert conn is new_conn

    def test_ensure_table_exists(self):
        store, mock_conn, mock_cursor, _ = _make_store()
        # Reset mock_connection to simulate first call
        store._ensure_table_exists()

        # Should have executed CREATE TABLE and index DDL statements
        assert mock_cursor.execute.call_count >= 3
        mock_conn.commit.assert_called()

    def test_del_closes_connection(self):
        store, mock_conn, _, _ = _make_store()

        store.__del__()
        mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# Helper / encoding tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOracleVectorStoreHelpers:
    def test_encode_vector(self):
        from application.vectorstore.oracle import OracleVectorStore as OVS

        result = OVS._encode_vector([1.5, -2.3, 0.0])
        assert result == "[1.5, -2.3, 0.0]"

    def test_encode_metadata_none(self):
        from application.vectorstore.oracle import OracleVectorStore as OVS

        assert OVS._encode_metadata(None) is None
        assert OVS._encode_metadata({}) is None

    def test_encode_metadata_dict(self):
        from application.vectorstore.oracle import OracleVectorStore as OVS

        result = OVS._encode_metadata({"key": "val"})
        assert result == '{"key": "val"}'

    def test_decode_metadata_none(self):
        from application.vectorstore.oracle import OracleVectorStore as OVS

        assert OVS._decode_metadata(None) == {}

    def test_decode_metadata_string(self):
        from application.vectorstore.oracle import OracleVectorStore as OVS

        assert OVS._decode_metadata('{"a": 1}') == {"a": 1}

    def test_decode_metadata_dict_passthrough(self):
        from application.vectorstore.oracle import OracleVectorStore as OVS

        assert OVS._decode_metadata({"a": 1}) == {"a": 1}

    def test_decode_metadata_invalid_string(self):
        from application.vectorstore.oracle import OracleVectorStore as OVS

        assert OVS._decode_metadata("not-json") == {}
